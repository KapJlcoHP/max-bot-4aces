"""Регрессионные проверки блокеров этапа 1."""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.db.models import Base, HealthRecord, NotificationLog, Organization, Route, RouteStep, User
from core.db.demo import fill_demo
from core.db.seed import build_route_for, seed_organizations
from core.schemas import CustomStepIn, HealthReportOut, ReportNote, RouteStartIn
from server.deps import validate_init_data
from server.health_pdf import _record_line, build_health_pdf


class Stage1RegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            max_user_id=710001,
            first_name="Пациент <тест>",
            last_name="Иванов & сын",
            consent_at=datetime.now(timezone.utc),
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_custom_step_keeps_time_and_place(self):
        route = build_route_for(
            self.db,
            self.user,
            "custom",
            custom_steps=[{
                "title": "Сдать анализы",
                "deadline": date(2026, 10, 20),
                "deadline_time": "14:30",
                "place": "Лаборатория №2",
            }],
        )

        step = route.steps[0]
        self.assertEqual(step.deadline_time, "14:30")
        self.assertEqual(step.place, "Лаборатория №2")

    def test_custom_step_api_keeps_dto_time_and_place(self):
        from server.api.v1 import api

        route = api.start_route(
            RouteStartIn(
                situation_key="custom",
                custom_steps=[CustomStepIn(
                    title="Сдать анализы", deadline_time="14:30", place="Лаборатория №2",
                )],
            ),
            user=self.user,
            db=self.db,
        )

        self.assertEqual(route.steps[0].deadline_time, "14:30")
        self.assertEqual(route.steps[0].place, "Лаборатория №2")

    def test_route_start_replaces_active_route_instead_of_returning_409(self):
        from server.api.v1 import api

        first = api.start_route(RouteStartIn(situation_key="custom"), user=self.user, db=self.db)
        second = api.start_route(RouteStartIn(situation_key="chronic"), user=self.user, db=self.db)

        self.assertNotEqual(first.id, second.id)
        self.assertTrue(second.active)

    def test_demo_default_region_matches_organization_region(self):
        # Проверяем контракт справочника, на котором ломался список организаций.
        fill_demo(self.db, self.user)
        seed_organizations(self.db)
        self.assertGreater(
            self.db.query(Organization).filter(Organization.region == self.user.region).count(),
            0,
        )

    def test_non_ascii_hash_is_rejected_as_bad_auth_not_server_error(self):
        raw = "auth_date=1791720000&user=%7B%22id%22%3A1%7D&hash=подделка"
        with patch("server.deps.get_settings", return_value=SimpleNamespace(max_bot_token="token")):
            self.assertIsNone(validate_init_data(raw))

    def test_pdf_escapes_markup_in_note_and_profile(self):
        self.db.add(HealthRecord(
            user_id=self.user.id,
            type="mood",
            at=datetime.now(),
            mood="Нормально",
            note="АД < 120/80 & пульс <b>70</b>",
        ))
        self.db.commit()
        report = HealthReportOut(notes=[ReportNote(
            at=datetime.now(),
            note="АД < 120/80 & пульс <b>70</b>",
        )])

        pdf = build_health_pdf(self.db, self.user, report, {"mood": True})

        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_report_and_settings_use_the_same_diary_defaults(self):
        from server.api.v1 import api

        self.db.add(HealthRecord(
            user_id=self.user.id, type="sugar", at=datetime.now(), sugar_mmol=5.5,
        ))
        self.db.commit()

        settings = api.health_settings(user=self.user, db=self.db)
        report = api.health_report(user=self.user, db=self.db)

        self.assertEqual({s.diary: s.enabled for s in settings.diaries}, {
            "bp": True, "weight": True, "sugar": False, "mood": True,
        })
        self.assertEqual(report.sugar_count, 0)

    def test_moving_deadline_removes_old_step_notification_dedup(self):
        from server.api.v1 import api

        route = Route(user_id=self.user.id, situation_key="custom", title="Маршрут")
        self.db.add(route)
        self.db.flush()
        step = RouteStep(
            route_id=route.id, position=1, title="Визит", status="current",
            deadline=date(2026, 10, 20),
        )
        self.db.add(step)
        self.db.flush()
        self.db.add(NotificationLog(
            user_id=self.user.id, kind="step", ref_id=step.id, lead="day",
        ))
        self.db.commit()

        api.update_step(
            step.id,
            body=SimpleNamespace(deadline=date(2026, 10, 21)),
            user=self.user,
            db=self.db,
        )

        self.assertEqual(self.db.query(NotificationLog).filter_by(ref_id=step.id).count(), 0)

    def test_pdf_renders_stored_utc_in_users_local_timezone(self):
        row = HealthRecord(
            user_id=self.user.id,
            type="mood",
            at=datetime(2026, 10, 11, 9, 0),  # 12:00 in Europe/Moscow
            mood="Хорошо",
        )
        self.user.tz = "Europe/Moscow"
        self.db.add(row)
        self.db.commit()

        when, _ = _record_line(row, self.user.tz)

        self.assertIn("12:00", when)

    def test_export_endpoint_passes_test_token_to_authentication(self):
        from server.api.v1 import api

        request = SimpleNamespace(headers={"X-Test-Token": "secret-token"})
        with (
            patch.object(api, "get_authenticated_user", return_value=self.user) as auth,
            patch.object(api, "health_report", return_value=HealthReportOut()),
            patch.object(api, "_get_diary_settings", return_value={}),
            patch.object(api, "build_health_pdf", return_value=b"%PDF-1.7"),
        ):
            response = api.export_health_pdf(request, t=None, db=self.db)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"%PDF-1.7")
        self.assertEqual(auth.call_args.kwargs["test_token"], "secret-token")

    def test_pdf_worker_opens_its_own_session(self):
        from bot import exporter

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as db:
            worker_user = User(max_user_id=710002)
            db.add(worker_user)
            db.commit()
            worker_user_id = worker_user.id

        with patch.object(exporter, "SessionLocal", sessions):
            with patch.object(exporter, "_build_pdf", return_value=(b"%PDF", "demo.pdf")) as build:
                result = exporter._build_pdf_in_thread(worker_user_id)

        self.assertEqual(result, (b"%PDF", "demo.pdf"))
        self.assertEqual(build.call_args.args[1].id, worker_user_id)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
