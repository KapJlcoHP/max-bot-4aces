"""Проверки времени и повторной записи доставленных уведомлений."""

import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bot.scheduler import collect_due, mark_sent, scheduler_loop
from core.db.models import (
    Base,
    HealthRecord,
    HealthSetting,
    MedCourse,
    NotificationLog,
    Reminder,
    Route,
    RouteStep,
    User,
)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_each_user_gets_their_own_local_time(self):
        users = [
            User(max_user_id=101, tz="Europe/Moscow"),
            User(max_user_id=102, tz="America/New_York"),
        ]
        self.db.add_all(users)
        self.db.flush()
        # DateTime в БД — UTC-naive форма: 10:00 Moscow = 07:00 UTC,
        # 10:00 New York = 14:00 UTC.
        self.db.add(Reminder(user_id=users[0].id, title="Visit", at=datetime(2026, 9, 29, 7)))
        self.db.add(Reminder(user_id=users[1].id, title="Visit", at=datetime(2026, 9, 29, 14)))
        self.db.commit()

        with patch("bot.scheduler._user_now", side_effect=[datetime(2026, 9, 29, 10), datetime(2026, 9, 29, 3)]) as clock:
            pushes = collect_due(self.db)

        self.assertEqual(clock.call_count, 2)
        self.assertEqual([push.lead for push in pushes if push.user_id == users[0].id], ["now"])
        self.assertEqual([push.lead for push in pushes if push.user_id == users[1].id], ["day"])

    def test_step_and_reminder_have_separate_delivery_windows(self):
        due_at = datetime(2026, 9, 29, 10)
        user = User(max_user_id=201)
        self.db.add(user)
        self.db.flush()
        route = Route(user_id=user.id, situation_key="test", title="Test")
        self.db.add(route)
        self.db.flush()
        self.db.add(RouteStep(route_id=route.id, position=1, title="Step", status="current", deadline=due_at.date(), deadline_time="10:00"))
        self.db.add(Reminder(user_id=user.id, title="Visit", at=datetime(2026, 9, 29, 7)))
        self.db.commit()

        for now, expected in (
            (due_at - timedelta(days=1), "day"),
            (due_at - timedelta(hours=1), "hour"),
            (due_at, "now"),
        ):
            with self.subTest(expected=expected):
                pushes = collect_due(self.db, now=now)
                self.assertEqual([(push.kind, push.lead) for push in pushes], [("step", expected), ("reminder", expected)])

    def test_diary_record_is_checked_with_local_day_bounds(self):
        user = User(max_user_id=301, tz="Europe/Moscow")
        self.db.add(user)
        self.db.flush()
        self.db.add(HealthSetting(user_id=user.id, diary="bp", enabled=True, push_time="01:00"))
        # 21:30 UTC on Sep 28 is 00:30 on Sep 29 in Moscow.
        self.db.add(HealthRecord(user_id=user.id, type="bp", at=datetime(2026, 9, 28, 21, 30, tzinfo=timezone.utc), systolic=120, diastolic=80))
        self.db.commit()

        self.assertEqual(collect_due(self.db, now=datetime(2026, 9, 29, 1)), [])

    def test_disabled_diary_does_not_send_a_saved_reminder(self):
        user = User(max_user_id=305, tz="Europe/Moscow")
        self.db.add(user)
        self.db.flush()
        self.db.add(HealthSetting(user_id=user.id, diary="bp", enabled=False, push_time="01:00"))
        self.db.commit()

        self.assertEqual(collect_due(self.db, now=datetime(2026, 9, 29, 1)), [])

    def test_disabled_step_leads_are_not_collected(self):
        due_at = datetime(2026, 9, 29, 10)
        user = User(max_user_id=306, tz="UTC")
        self.db.add(user)
        self.db.flush()
        route = Route(user_id=user.id, situation_key="test", title="Test")
        self.db.add(route)
        self.db.flush()
        self.db.add(RouteStep(
            route_id=route.id,
            position=1,
            title="Step",
            status="current",
            deadline=due_at.date(),
            deadline_time="10:00",
        ))
        self.db.commit()

        for setting, now in (
            ("notify_day_before", due_at - timedelta(days=1)),
            ("notify_hour_before", due_at - timedelta(hours=1)),
            ("notify_at_deadline", due_at),
        ):
            with self.subTest(setting=setting):
                setattr(user, setting, False)
                self.db.commit()
                self.assertEqual(collect_due(self.db, now=now), [])
                setattr(user, setting, True)
                self.db.commit()

        # The global switch still gates all step notifications.
        user.notifications_on = False
        self.db.commit()
        self.assertEqual(collect_due(self.db, now=due_at - timedelta(days=1)), [])

    def test_step_day_lead_uses_user_selected_time(self):
        due_at = datetime(2026, 9, 29, 10)
        user = User(max_user_id=307, tz="UTC", step_day_before_time="17:00")
        self.db.add(user)
        self.db.flush()
        route = Route(user_id=user.id, situation_key="test", title="Test")
        self.db.add(route)
        self.db.flush()
        self.db.add(RouteStep(
            route_id=route.id,
            position=1,
            title="Step",
            status="current",
            deadline=due_at.date(),
            deadline_time="10:00",
        ))
        self.db.commit()

        self.assertEqual(collect_due(self.db, now=datetime(2026, 9, 28, 16)), [])
        self.assertEqual(
            [(push.kind, push.lead) for push in collect_due(self.db, now=datetime(2026, 9, 28, 17))],
            [("step", "day")],
        )

    def test_notification_dedup_is_scoped_to_user(self):
        users = [User(max_user_id=302, tz="UTC"), User(max_user_id=303, tz="UTC")]
        self.db.add_all(users)
        self.db.flush()
        for user in users:
            self.db.add(MedCourse(user_id=user.id, name="Medicine", times=["10:00"]))
        self.db.commit()
        pushes = collect_due(self.db, now=datetime(2026, 9, 29, 10))
        self.assertEqual(len([p for p in pushes if p.kind == "med"]), 2)
        mark_sent(self.db, next(p for p in pushes if p.user_id == users[0].id))
        remaining = collect_due(self.db, now=datetime(2026, 9, 29, 10))
        self.assertEqual([p.user_id for p in remaining if p.kind == "med"], [users[1].id])

    def test_moving_step_deadline_clears_old_dedup(self):
        from core.schemas import StepUpdateIn
        from server.api.v1 import api

        user = User(max_user_id=304, consent_at=datetime.now(timezone.utc))
        self.db.add(user)
        self.db.flush()
        route = Route(user_id=user.id, situation_key="test", title="Test")
        self.db.add(route)
        self.db.flush()
        step = RouteStep(
            route_id=route.id, position=1, title="Step", status="current",
            deadline=date(2026, 9, 30), deadline_time="10:00",
        )
        self.db.add(step)
        self.db.commit()
        for lead in ("day", "hour", "now"):
            self.db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead=lead))
        # Одинаковый ref_id у другого типа уведомления не должен затрагиваться.
        self.db.add(NotificationLog(user_id=user.id, kind="reminder", ref_id=step.id, lead="day"))
        self.db.commit()

        api.update_step(step.id, StepUpdateIn(deadline=date(2026, 10, 2)), user=user, db=self.db)
        self.assertEqual(self.db.query(NotificationLog).filter_by(
            user_id=user.id, kind="step", ref_id=step.id,
        ).count(), 0)
        self.assertEqual(self.db.query(NotificationLog).filter_by(kind="reminder").count(), 1)

        for now, expected in (
            (datetime(2026, 10, 1, 10), "day"),
            (datetime(2026, 10, 2, 9), "hour"),
            (datetime(2026, 10, 2, 10), "now"),
        ):
            with self.subTest(lead=expected):
                pushes = collect_due(self.db, now=now)
                self.assertEqual([(p.kind, p.lead) for p in pushes], [("step", expected)])
                mark_sent(self.db, pushes[0])
                self.assertEqual(collect_due(self.db, now=now), [])

        # Повторное сохранение той же даты не должно разрешать дубли отправки.
        api.update_step(step.id, StepUpdateIn(deadline=date(2026, 10, 2)), user=user, db=self.db)
        self.assertEqual(self.db.query(NotificationLog).filter_by(kind="step").count(), 3)
        self.assertEqual(collect_due(self.db, now=datetime(2026, 10, 2, 10)), [])


class DeliveryRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_medicine_is_delivered_once_after_ten_minute_network_outage(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        due_at = datetime(2026, 10, 17, 10)
        now = due_at
        with sessions() as db:
            user = User(max_user_id=403, tz="UTC")
            db.add(user)
            db.flush()
            course = MedCourse(user_id=user.id, name="Medicine", times=["10:00"])
            db.add(course)
            db.commit()
            user_id, max_user_id, course_id = user.id, user.max_user_id, course.id

        attempts = []
        delivered = []
        log_counts_during_outage = []

        class Bot:
            async def send_message(self, **kwargs):
                attempts.append(now)
                if now < due_at + timedelta(minutes=10):
                    with sessions() as db:
                        log_counts_during_outage.append(db.query(NotificationLog).count())
                    raise OSError("temporary network outage")
                delivered.append(kwargs)

        async def advance_clock(seconds):
            nonlocal now
            now += timedelta(seconds=seconds)
            if now >= due_at + timedelta(minutes=12):
                raise asyncio.CancelledError()

        with (
            patch("bot.scheduler.SessionLocal", sessions),
            patch("bot.scheduler._user_now", side_effect=lambda user: now),
            patch("bot.scheduler.asyncio.sleep", advance_clock),
            patch("bot.scheduler.log.exception"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler_loop(Bot(), None)

        self.assertEqual(attempts, [due_at + timedelta(minutes=i) for i in range(11)])
        self.assertEqual(log_counts_during_outage, [0] * 10)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["user_id"], max_user_id)
        with sessions() as db:
            logged = db.query(NotificationLog).one()
            self.assertEqual(
                (logged.user_id, logged.kind, logged.ref_id, logged.lead),
                (user_id, "med", course_id, "20261017-1000"),
            )
            self.assertEqual(collect_due(db, now=now), [])

    async def test_sent_message_is_not_resent_after_temporary_database_failure(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        due_at = datetime(2026, 9, 29, 10)
        with sessions() as db:
            user = User(max_user_id=401)
            db.add(user)
            db.flush()
            db.add(Reminder(user_id=user.id, title="Visit", at=due_at))
            db.commit()

        class Bot:
            calls = 0

            async def send_message(self, **kwargs):
                self.calls += 1

        bot = Bot()
        attempts = 0
        real_mark_sent = mark_sent

        def flaky_mark_sent(db, push):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary database failure")
            real_mark_sent(db, push)

        ticks = 0

        async def stop_after_two_ticks(_):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                raise asyncio.CancelledError()

        with (
            patch("bot.scheduler.SessionLocal", sessions),
            patch("bot.scheduler._user_now", return_value=due_at),
            patch("bot.scheduler.mark_sent", side_effect=flaky_mark_sent),
            patch("bot.scheduler.asyncio.sleep", stop_after_two_ticks),
            patch("bot.scheduler.log.exception"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler_loop(bot, None)

        with sessions() as db:
            self.assertEqual(db.query(NotificationLog).count(), 1)
        self.assertEqual(bot.calls, 1)
        self.assertEqual(attempts, 2)
        engine.dispose()

    async def test_network_failures_never_mark_push_as_delivered(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        due_at = datetime(2026, 9, 29, 10)
        with sessions() as db:
            user = User(max_user_id=402, tz="UTC")
            db.add(user)
            db.flush()
            db.add(Reminder(user_id=user.id, title="Visit", at=due_at))
            db.commit()

        class Bot:
            calls = 0

            async def send_message(self, **kwargs):
                self.calls += 1
                raise OSError("temporary network outage")

        bot = Bot()
        ticks = 0

        async def stop_after_six_ticks(_):
            nonlocal ticks
            ticks += 1
            if ticks == 6:
                raise asyncio.CancelledError()

        with (
            patch("bot.scheduler.SessionLocal", sessions),
            patch("bot.scheduler._user_now", return_value=due_at),
            patch("bot.scheduler.asyncio.sleep", stop_after_six_ticks),
            patch("bot.scheduler.log.exception"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler_loop(bot, None)

        with sessions() as db:
            self.assertEqual(db.query(NotificationLog).count(), 0)
        self.assertEqual(bot.calls, 6)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
