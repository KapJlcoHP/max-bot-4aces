"""Editorial templates and their creation semantics, isolated synthetic DBs only."""

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from core.db import demo, seed
from core.db.models import (
    Base, HealthRecord, MedCourse, MedIntake, Reminder, Route, RouteStep, User,
)
from core.schemas import StepDto
from core.services import ServiceError
from core.time import user_local


EXPECTED = {
    "doctor": [("D-BOOK", "booking"), ("D-PREP", "task"), ("D-VISIT", "visit")],
    "chronic": [("C-PLAN", "task"), ("C-BOOK", "booking"), ("C-PREP", "task"), ("C-VISIT", "visit")],
    "rehab": [("R-REQ", "task"), ("R-DOCS", "task"), ("R-BOOK", "booking"), ("R-VISIT", "visit")],
    "checkup": [("K-REQ", "task"), ("K-BOOK", "booking"), ("K-PREP", "task"), ("K-FIRST", "task")],
    "mse": [("M-BOOK", "booking"), ("M-VISIT", "visit"), ("M-NEXT", "task")],
    "certificate": [("F-REQ", "task"), ("F-REQUEST", "task"), ("F-GET", "task"), ("F-CHECK", "task")],
    "hospital": [("H-REQ", "task"), ("H-BOOK", "booking"), ("H-PREP", "task"), ("H-ADMIT", "task"), ("H-DOCS", "task")],
    "exam": [("E-REQ", "task"), ("E-BOOK", "booking"), ("E-PREP", "task"), ("E-EXAM", "investigation"), ("E-RESULT", "task")],
    "family": [("FAMILY-EXTERNAL", "task")],
}
LINKS = {"D-BOOK": "D-VISIT", "C-BOOK": "C-VISIT", "R-BOOK": "R-VISIT", "K-BOOK": "K-FIRST",
         "M-BOOK": "M-VISIT", "H-BOOK": "H-ADMIT", "E-BOOK": "E-EXAM"}


class RouteContentSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = self.new_user()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def new_user(self, **values):
        user = User(max_user_id=980000 + self.db.query(User).count(), **values)
        self.db.add(user)
        self.db.commit()
        return user

    def snapshot(self):
        return {table.name: self.db.execute(select(table).order_by(table.c.id)).all()
                for table in Base.metadata.sorted_tables}

    def test_all_definitions_have_only_editorial_base_actions_and_explicit_links(self):
        scenarios = seed.load_scenarios()
        self.assertEqual(set(scenarios), set(EXPECTED))
        self.assertEqual({item["key"] for item in seed.load_catalog()}, set(EXPECTED) - {"family"})
        sources = seed.load_sources()
        for key, scenario in scenarios.items():
            with self.subTest(scenario=key):
                self.assertEqual([(step["key"], step["kind"]) for step in scenario["steps"]], EXPECTED[key])
                for step in scenario["steps"]:
                    self.assertEqual(step.get("booking_target_key"), LINKS.get(step["key"]))
                    self.assertIn(step["source_id"], sources)
                    self.assertFalse({"in_days", "deadline", "deadline_time", "time", "appointment_date"} & set(step))
        text = json.dumps(scenarios, ensure_ascii=False)
        for obsolete in ("кабинет №102", "каб. 304", "8:00 до 11:00", "5 рабочих дней", "натощак", "Нотариальная доверенность"):
            self.assertNotIn(obsolete, text)
        family = scenarios["family"]
        self.assertIn("Демонстрационная заготовка. Семейный доступ и общие уведомления не подключены", family["steps"][0]["description"])
        self.assertEqual(family["checklist"], [])
        catalog = {item["key"]: item for item in seed.load_catalog()}
        self.assertIn("выписку или копию", catalog["certificate"]["title"])
        self.assertIn("выписные документы", catalog["hospital"]["description"])
        self.assertIn("согласованные мероприятия", catalog["checkup"]["description"])
        self.assertTrue(all(source["checked_at"] is None for source in sources.values()))

    def test_all_new_definitions_roundtrip_kinds_keys_links_and_null_schedules(self):
        for key, expected in EXPECTED.items():
            with self.subTest(scenario=key):
                route = seed.build_route_for(self.db, self.user, key)
                self.db.expire_all()
                steps = self.db.get(Route, route.id).steps
                self.assertEqual([(s.template_key, s.kind) for s in steps], expected)
                by_key = {s.template_key: s for s in steps}
                self.assertEqual([s.position for s in steps], list(range(1, len(steps) + 1)))
                self.assertEqual([s.status for s in steps], ["current"] + ["pending"] * (len(steps) - 1))
                for stored in steps:
                    target = by_key.get(LINKS.get(stored.template_key))
                    self.assertEqual(stored.booking_target_step_id, target.id if target else None)
                    self.assertIsNone(stored.deadline)
                    self.assertIsNone(stored.deadline_time)
                    self.assertIsNone(stored.appointment_date)
                    self.assertEqual(stored.source, "template")
                    dto = StepDto.model_validate(stored)
                    self.assertEqual((dto.kind, dto.template_key, dto.booking_target_step_id, dto.appointment_date),
                                     (stored.kind, stored.template_key, stored.booking_target_step_id, None))

    def test_excluded_targets_are_unlinked_without_guessing_another_event(self):
        for key, scenario in seed.load_scenarios().items():
            for index, spec in enumerate(scenario["steps"], 1):
                if spec["key"] not in LINKS.values():
                    continue
                with self.subTest(scenario=key):
                    route = seed.build_route_for(self.db, self.user, key, exclude_positions=[index], custom_steps=[
                        {"client_key": "same-name", "kind": spec["kind"], "title": spec["title"]},
                    ])
                    booking = next(s for s in route.steps if s.kind == "booking")
                    self.assertIsNone(booking.booking_target_step_id)

    def test_custom_placement_uses_original_positions_and_equal_names_never_identity(self):
        route = seed.build_route_for(self.db, self.user, "chronic", exclude_positions=[1], custom_steps=[
            {"client_key": "custom-book", "kind": "booking", "booking_target_key": "custom-exam", "before_position": 4, "title": "Одинаково"},
            {"client_key": "custom-exam", "kind": "investigation", "before_position": 4, "title": "Одинаково"},
            {"client_key": "result", "kind": "task", "before_position": 4, "title": "Одинаково"},
            {"client_key": "other", "kind": "visit", "title": "Контрольный приём у врача"},
        ])
        steps = route.steps
        self.assertEqual([s.template_key for s in steps], ["C-BOOK", "C-PREP", None, None, None, "C-VISIT", None])
        self.assertEqual(steps[0].booking_target_step_id, steps[5].id)
        self.assertEqual(steps[2].booking_target_step_id, steps[3].id)
        self.assertEqual([s.source for s in steps[2:5]], ["user"] * 3)
        self.assertEqual([s.position for s in steps], list(range(1, 8)))

    def test_invalid_or_excluded_placement_and_ambiguous_keys_leave_existing_route_untouched(self):
        seed.build_route_for(self.db, self.user, "doctor")
        before = self.snapshot()
        invalid = [
            {"before_position": 0}, {"before_position": 9}, {"before_position": 2},
            {"client_key": "D-VISIT"}, {"client_key": ""},
        ]
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaises(ServiceError):
                seed.build_route_for(self.db, self.user, "doctor", exclude_positions=[2], custom_steps=[{"title": "Свой", **extra}])
            self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ServiceError):
            seed.build_route_for(self.db, self.user, "custom", custom_steps=[
                {"client_key": "duplicate", "title": "Один"}, {"client_key": "duplicate", "title": "Другой"}])
        self.assertEqual(self.snapshot(), before)

    def test_custom_route_preserves_array_order_and_appointment_is_only_metadata(self):
        obtained, scheduled = date(2031, 4, 5), date(2031, 4, 6)
        route = seed.build_route_for(self.db, self.user, "custom", custom_steps=[
            {"client_key": "booking", "kind": "booking", "booking_target_key": "event", "title": "Одинаково", "appointment_date": obtained},
            {"client_key": "prep", "kind": "task", "title": "Подготовка"},
            {"client_key": "event", "kind": "visit", "title": "Одинаково", "deadline": scheduled, "deadline_time": "13:25"},
        ])
        self.db.expire_all()
        steps = self.db.get(Route, route.id).steps
        self.assertEqual([s.title for s in steps], ["Одинаково", "Подготовка", "Одинаково"])
        self.assertEqual([s.source for s in steps], ["user"] * 3)
        self.assertTrue(all(s.template_key is None for s in steps))
        self.assertEqual(steps[0].booking_target_step_id, steps[2].id)
        self.assertEqual(steps[0].appointment_date, obtained)
        dto = StepDto.model_validate(steps[0])
        self.assertEqual((dto.kind, dto.appointment_date, dto.booking_target_step_id, dto.source),
                         ("booking", obtained, steps[2].id, "user"))
        self.assertEqual((steps[2].deadline, steps[2].deadline_time), (scheduled, "13:25"))

    def test_invalid_booking_targets_are_rejected_instead_of_repaired(self):
        cases = [
            [{"client_key": "b", "kind": "booking", "booking_target_key": "missing"}],
            [{"client_key": "b", "kind": "booking", "booking_target_key": "b"}],
            [{"client_key": "e", "kind": "visit"}, {"kind": "booking", "booking_target_key": "e"}],
            [{"kind": "booking", "booking_target_key": "e"}, {"client_key": "e", "kind": "unknown"}],
            [{"kind": "booking", "booking_target_key": "e"}, {"client_key": "e", "kind": "booking"}],
            [{"kind": "task", "booking_target_key": "e"}, {"client_key": "e", "kind": "visit"}],
            [{"kind": "visit", "appointment_date": date(2031, 5, 2)}],
            [{"kind": "booking", "deadline_time": "14:00"}],
            [{"kind": "booking", "time": "14:00"}],
            [{"before_position": 1}],
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ServiceError):
                seed.build_route_for(self.db, self.user, "custom", custom_steps=[{"title": "Шаг", **s} for s in case])
            self.assertEqual(self.db.query(Route).count(), 0)
        for kind in ("visit", "investigation", "task", "process"):
            route = seed.build_route_for(self.db, self.user, "custom", custom_steps=[
                {"title": "Запись", "kind": "booking", "booking_target_key": "event"},
                {"title": "Событие", "kind": kind, "client_key": "event"},
            ])
            self.assertEqual(route.steps[0].booking_target_step_id, route.steps[1].id)

    def test_new_templates_do_not_rewrite_old_route_history(self):
        old = Route(user_id=self.user.id, situation_key="doctor", title="Старый маршрут")
        self.db.add(old)
        self.db.flush()
        historical = RouteStep(route_id=old.id, position=7, title="Сдать анализы", kind="unknown", status="done",
                               source="doctor", description="Мой прежний текст", deadline=date(2020, 1, 3), deadline_time="11:15",
                               completed_at=datetime(2020, 1, 3, 9), reminder_revision=4)
        self.db.add(historical)
        self.db.commit()
        initial = {column.name: getattr(historical, column.name) for column in RouteStep.__table__.columns}
        seed.build_route_for(self.db, self.user, "doctor")
        self.db.refresh(historical)
        self.assertEqual({column.name: getattr(historical, column.name) for column in RouteStep.__table__.columns}, initial)

    def test_demo_is_coherent_at_call_time_in_multiple_timezones_and_repeat_is_noop(self):
        cases = [
            (datetime(2031, 5, 2, 14, 59, tzinfo=timezone.utc), "Asia/Tokyo", date(2031, 5, 2)),
            (datetime(2031, 5, 2, 15, 1, tzinfo=timezone.utc), "Asia/Tokyo", date(2031, 5, 3)),
            (datetime(2031, 5, 2, 15, 1, tzinfo=timezone.utc), "America/Los_Angeles", date(2031, 5, 2)),
            (datetime(2031, 5, 2, 0, 1, tzinfo=timezone.utc), "Pacific/Kiritimati", date(2031, 5, 2)),
            (datetime(2031, 5, 2, 0, 1, tzinfo=timezone.utc), "Pacific/Pago_Pago", date(2031, 5, 1)),
        ]
        for instant, tz, today in cases:
            with self.subTest(tz=tz, today=today):
                user = self.new_user(tz=tz)
                with patch.object(demo, "datetime", wraps=datetime) as clock:
                    clock.now.side_effect = lambda zone: instant.astimezone(zone)
                    demo.fill_demo(self.db, user)
                self.assertTrue(demo.is_demo_data(self.db, user.id))
                route = self.db.query(Route).filter_by(user_id=user.id).one()
                steps = route.steps
                self.assertIn("Демо", route.title)
                self.assertEqual(len(steps), 8)
                self.assertEqual([s.status for s in steps], ["done"] * 7 + ["current"])
                self.assertEqual([s.kind for s in steps], ["task", "booking", "task", "visit", "investigation", "task", "booking", "visit"])
                self.assertEqual(steps[1].booking_target_step_id, steps[3].id)
                self.assertEqual(steps[-2].booking_target_step_id, steps[-1].id)
                self.assertEqual(steps[-2].appointment_date, today + timedelta(days=7))
                self.assertEqual(steps[-1].deadline, today + timedelta(days=7))
                self.assertIsNone(steps[-1].completed_at)
                self.assertTrue(all(s.source == "doctor" for s in steps[4:]))
                for step in steps[:-1]:
                    self.assertLess(step.deadline, today)
                    self.assertLess(user_local(step.completed_at, tz), instant.astimezone(user_local(step.completed_at, tz).tzinfo))
                    self.assertIn("синтетические", step.description)
                self.assertLess(steps[3].deadline, steps[4].deadline)
                records = self.db.query(HealthRecord).filter_by(user_id=user.id).all()
                self.assertEqual(len(records), 68)
                self.assertEqual(max(user_local(r.at, tz).date() for r in records), today - timedelta(days=1))
                self.assertTrue(all(r.at < instant.replace(tzinfo=None) for r in records))
                courses = self.db.query(MedCourse).filter_by(user_id=user.id).all()
                self.assertTrue(all(user_local(c.created_at, tz).date() > steps[3].deadline for c in courses))
                self.assertTrue(all(c.name.startswith("Демо:") for c in courses))
                intakes = self.db.query(MedIntake).filter_by(user_id=user.id).all()
                self.assertEqual(len(intakes), 86)
                self.assertTrue(all(r.taken_at < instant.replace(tzinfo=None) for r in intakes))
                for intake in intakes:
                    local = user_local(intake.taken_at, tz)
                    self.assertEqual((local.date(), local.strftime("%H:%M")), (intake.day, intake.at_time))
                reminders = self.db.query(Reminder).filter_by(user_id=user.id).all()
                self.assertTrue(all("независимое" in r.title for r in reminders))
                self.assertTrue(all(r.at > instant.replace(tzinfo=None) for r in reminders))
                initial = self.snapshot()
                with patch.object(demo, "datetime", wraps=datetime) as clock:
                    clock.now.side_effect = lambda zone: (instant + timedelta(days=3)).astimezone(zone)
                    demo.fill_demo(self.db, user)
                self.assertEqual(self.snapshot(), initial)


if __name__ == "__main__":
    unittest.main()
