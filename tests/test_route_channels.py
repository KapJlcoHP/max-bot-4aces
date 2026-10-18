"""Real chat handlers and PDF generation; isolated database, no MAX transport."""

import importlib
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import Settings, get_settings
from core.db.demo import fill_demo, wipe_data
from core.db.models import Base, HealthRecord, Route, RouteStep, User
from core.schemas import HealthReportOut


class RouteChannelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        settings = Settings.model_construct(database_url="sqlite://", max_bot_token="",
                                            test_api_token="", miniapp_public_url="", yandex_maps_api_key="")
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.enterContext(patch("core.config.Settings", return_value=settings))
        self.enterContext(patch("pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_files",
                                side_effect=AssertionError("No .env access")))
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("No network")))
        self.actions = importlib.import_module("bot.handlers.actions")
        self.scheduler = importlib.import_module("bot.scheduler")
        self.enterContext(patch("bot.throttle._hits", {}))
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.enterContext(patch.object(self.actions, "SessionLocal", self.sessions))
        with self.sessions() as db:
            user = User(max_user_id=980001, consent_at=datetime(2026, 10, 18), tz="Europe/Moscow")
            db.add(user)
            db.flush()
            route = Route(user_id=user.id, situation_key="custom", title="Synthetic")
            db.add(route)
            db.flush()
            booking = RouteStep(route_id=route.id, position=1, title="Записаться на обследование",
                                kind="booking", status="current", deadline=date(2035, 10, 18),
                                appointment_date=date(2035, 10, 24))
            target = RouteStep(route_id=route.id, position=2, title="Исследование",
                               kind="investigation", status="pending", deadline=date(2035, 10, 24))
            db.add_all([booking, target])
            db.flush()
            booking.booking_target_step_id = target.id
            db.commit()
            self.uid, self.route_id, self.bid, self.tid = user.id, route.id, booking.id, target.id

    def event(self, callback=False, step_id=None):
        return SimpleNamespace(
            callback=SimpleNamespace(user=SimpleNamespace(user_id=980001), payload=f"sdone_{step_id or self.bid}"),
            message=SimpleNamespace(sender=SimpleNamespace(user_id=980001), answer=AsyncMock()),
            answer=AsyncMock(), bot=SimpleNamespace(me=SimpleNamespace(username="synthetic_test_bot")),
        )

    async def test_status_distinguishes_task_deadline_from_obtained_event_date(self):
        event = self.event()
        await self.actions.status_command(event)
        text = event.message.answer.await_args.args[0]
        self.assertIn("Срок действия «записаться» (не дата события): 18.10", text)
        self.assertIn("Дата полученного события: 24.10.2035", text)
        self.assertIn("только когда оно станет текущим", text)
        buttons = event.message.answer.await_args.kwargs["attachments"][0].model_dump(mode="json")["payload"]["buttons"]
        self.assertIn("Я записался", buttons[0][0]["text"])
        self.assertEqual(buttons[1][0]["payload"], f"step_{self.bid}")

    async def test_chat_booking_completes_only_booking_and_does_not_transfer_date(self):
        event = self.event(callback=True)
        await self.actions.cb_step_done(event)
        self.assertIn("Подтверждена только запись", event.answer.await_args.kwargs["new_text"])
        button = event.answer.await_args.kwargs["attachments"][0].model_dump(mode="json")["payload"]["buttons"][0][0]
        self.assertEqual(button["payload"], f"step_{self.tid}")
        with self.sessions() as db:
            self.assertEqual(db.get(RouteStep, self.bid).status, "done")
            self.assertEqual(db.get(RouteStep, self.tid).status, "current")
            self.assertEqual(db.get(RouteStep, self.tid).deadline, date(2035, 10, 24))

    async def test_visit_chat_completion_is_explicit_without_assignments_and_links_to_history(self):
        with self.sessions() as db:
            row = db.get(RouteStep, self.bid)
            row.kind, row.booking_target_step_id, row.appointment_date = "visit", None, None
            db.commit()
        event = self.event(callback=True)
        await self.actions.cb_step_done(event)
        self.assertIn("без внесения назначений", event.answer.await_args.kwargs["new_text"])
        button = event.answer.await_args.kwargs["attachments"][0].model_dump(mode="json")["payload"]["buttons"][0][0]
        self.assertEqual(button["payload"], f"step_{self.bid}")
        with self.sessions() as db:
            self.assertEqual(db.query(RouteStep).count(), 2)
            self.assertEqual(db.get(RouteStep, self.bid).status, "done")

    async def test_chat_cannot_complete_pending_target_or_another_users_step(self):
        event = self.event(callback=True, step_id=self.tid)
        await self.actions.cb_step_done(event)
        self.assertIn("текущий шаг", event.answer.await_args.kwargs["notification"])
        with self.sessions() as db:
            self.assertEqual(db.get(RouteStep, self.tid).status, "pending")
        event = self.event(callback=True, step_id=999999)
        await self.actions.cb_step_done(event)
        self.assertIn("не найден", event.answer.await_args.kwargs["notification"])

    def test_push_wording_and_snapshot_refresh_for_booking_metadata(self):
        now = datetime(2035, 10, 18, 9, 0)
        with self.sessions() as db:
            pushes = [p for p in self.scheduler.collect_due(db, now) if p.kind == "step"]
            self.assertEqual(len(pushes), 1)
            push = pushes[0]
            self.assertIn("не дата события", push.text)
            self.assertIn("24.10.2035", push.text)
            self.assertIn("Я записался", push.actions[0][0])
            row = db.get(RouteStep, self.bid)
            row.appointment_date += timedelta(days=1)
            db.commit()
            self.assertFalse(self.scheduler.revalidate_step_push(db, push, now))
            fresh = [p for p in self.scheduler.collect_due(db, now) if p.kind == "step"]
            self.assertIn("25.10.2035", fresh[0].text)

    def test_demo_marker_survives_edits_and_route_removal_until_wipe(self):
        with self.sessions() as db:
            user = db.get(User, self.uid)
            wipe_data(db, user)
            fill_demo(db, user)
            self.assertTrue(user.contains_demo_data)
            db.add(HealthRecord(user_id=user.id, type="weight", at=datetime(2026, 1, 1), weight_kg=70))
            db.delete(db.query(Route).filter_by(user_id=user.id).one())
            db.commit()
            db.refresh(user)
            self.assertTrue(user.contains_demo_data)
            self.assert_demo_pdf_marker(db, user, True)
            wipe_data(db, user)
            self.assertFalse(user.contains_demo_data)
            self.assert_demo_pdf_marker(db, user, False)

    def assert_demo_pdf_marker(self, db, user, expected):
        pdf = importlib.import_module("server.health_pdf")
        original = pdf.Paragraph
        labels = []

        def paragraph(text, *args, **kwargs):
            labels.append(text)
            return original(text, *args, **kwargs)

        with patch.object(pdf, "Paragraph", side_effect=paragraph):
            result = pdf.build_health_pdf(db, user, HealthReportOut(), {})
        self.assertTrue(result.startswith(b"%PDF"))
        self.assertEqual("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ" in labels, expected)


if __name__ == "__main__":
    unittest.main()
