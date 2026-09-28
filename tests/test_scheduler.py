"""Проверки времени и повторной записи доставленных уведомлений."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bot.scheduler import collect_due, mark_sent, scheduler_loop
from core.db.models import (
    Base,
    HealthRecord,
    HealthSetting,
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
        for user in users:
            self.db.add(Reminder(user_id=user.id, title="Visit", at=datetime(2026, 9, 29, 10)))
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
        self.db.add(Reminder(user_id=user.id, title="Visit", at=due_at))
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


class DeliveryRetryTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
