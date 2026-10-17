"""Standard step reminders follow status and the user's calendar, not noon defaults."""

import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bot.scheduler import collect_due, mark_sent
from core.db.models import Base, NotificationLog, Route, RouteStep, User
from core.schemas import StepUpdateIn
from core.services import complete_route_step
from server.api.v1.route import update_step


class StepNotificationMatrixTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.user = User(
            max_user_id=870001, tz="Europe/Moscow", step_day_before_time="08:30",
            consent_at=datetime(2026, 10, 18),
        )
        self.db.add(self.user)
        self.db.flush()
        self.route = Route(user_id=self.user.id, situation_key="custom", title="Test")
        self.db.add(self.route)
        self.db.flush()
        self.step = RouteStep(
            route_id=self.route.id, position=1, title="Visit", status="current",
            deadline=date(2026, 10, 24), source="user",
        )
        self.db.add(self.step)
        self.db.commit()

    def pushes(self, local_clock):
        instant = datetime.fromisoformat(local_clock).replace(tzinfo=ZoneInfo(self.user.tz))
        return [p for p in collect_due(self.db, now=instant.astimezone(timezone.utc)) if p.kind == "step"]

    def test_standard_matrix_in_multiple_timezones(self):
        cases = [
            (None, None, "2026-10-23T08:30", []),
            (None, None, "2026-10-24T12:00", []),
            (date(2026, 10, 24), None, "2026-10-23T08:29", []),
            (date(2026, 10, 24), None, "2026-10-23T08:30", ["day"]),
            (date(2026, 10, 24), None, "2026-10-23T23:59", ["day"]),
            (date(2026, 10, 24), None, "2026-10-24T08:29", []),
            (date(2026, 10, 24), None, "2026-10-24T08:30", ["now"]),
            (date(2026, 10, 24), None, "2026-10-24T11:30", ["now"]),
            (date(2026, 10, 24), None, "2026-10-24T23:59", ["now"]),
            (date(2026, 10, 24), None, "2026-10-25T00:00", []),
            (date(2026, 10, 24), "14:00", "2026-10-23T08:29", []),
            (date(2026, 10, 24), "14:00", "2026-10-23T08:30", ["day"]),
            (date(2026, 10, 24), "14:00", "2026-10-24T00:00", []),
            (date(2026, 10, 24), "14:00", "2026-10-24T12:59", []),
            (date(2026, 10, 24), "14:00", "2026-10-24T13:00", ["hour"]),
            (date(2026, 10, 24), "14:00", "2026-10-24T14:00", ["now"]),
            (date(2026, 10, 24), "14:00", "2026-10-25T00:00", []),
        ]
        for tz in ("Europe/Moscow", "America/Los_Angeles", "Asia/Tokyo"):
            self.user.tz = tz
            for day, clock, now, expected in cases:
                with self.subTest(tz=tz, day=day, clock=clock, now=now):
                    self.step.deadline, self.step.deadline_time = day, clock
                    self.db.commit()
                    self.assertEqual([p.lead for p in self.pushes(now)], expected)

    def test_pending_and_done_steps_never_send(self):
        for status in ("pending", "done"):
            self.step.status = status
            self.step.deadline_time = "14:00"
            self.db.commit()
            for now in ("2026-10-23T08:30", "2026-10-24T13:00", "2026-10-24T14:00"):
                with self.subTest(status=status, now=now):
                    self.assertEqual(self.pushes(now), [])

    def test_future_dated_pending_does_not_bypass_unscheduled_current(self):
        self.step.deadline = None
        self.db.add(RouteStep(
            route_id=self.route.id, position=2, title="Future", status="pending",
            deadline=date(2026, 10, 24), deadline_time="14:00",
        ))
        self.db.commit()
        self.assertEqual(self.pushes("2026-10-23T08:30"), [])

    def test_date_only_text_does_not_invent_event_time_or_expired_deadline(self):
        pushes = self.pushes("2026-10-24T08:30")
        self.assertEqual(len(pushes), 1)
        self.assertNotIn("12:00", pushes[0].text)
        self.assertNotIn("срок наступил", pushes[0].text.lower())
        self.assertNotIn("просроч", pushes[0].text.lower())
        self.assertIn("сегодня", pushes[0].text.lower())

    def test_global_and_profile_switches_gate_standard_matrix(self):
        for clock, now, setting in (
            (None, "2026-10-23T08:30", "notify_day_before"),
            (None, "2026-10-24T08:30", "notify_at_deadline"),
            ("14:00", "2026-10-24T13:00", "notify_hour_before"),
            ("14:00", "2026-10-24T14:00", "notify_at_deadline"),
        ):
            with self.subTest(clock=clock, setting=setting):
                self.step.deadline_time = clock
                setattr(self.user, setting, False)
                self.db.commit()
                self.assertEqual(self.pushes(now), [])
                setattr(self.user, setting, True)
                self.user.notifications_on = False
                self.db.commit()
                self.assertEqual(self.pushes(now), [])
                self.user.notifications_on = True
                self.db.commit()
                self.assertEqual(len(self.pushes(now)), 1)

    def test_date_only_delivery_is_deduplicated_and_clear_cancels_it(self):
        pushes = self.pushes("2026-10-24T08:30")
        self.assertEqual(len(pushes), 1)
        mark_sent(self.db, pushes[0])
        self.assertEqual(self.pushes("2026-10-24T11:30"), [])
        self.assertEqual(self.db.query(NotificationLog).count(), 1)
        update_step(self.step.id, StepUpdateIn(deadline=None), user=self.user, db=self.db)
        self.assertEqual(self.db.query(NotificationLog).count(), 0)
        self.assertEqual(self.pushes("2026-10-24T12:00"), [])

    def test_changed_time_renews_delivery_but_same_normalized_time_does_not(self):
        self.step.deadline_time = "14:00"
        self.db.commit()
        push = self.pushes("2026-10-24T13:00")[0]
        mark_sent(self.db, push)
        update_step(self.step.id, StepUpdateIn(deadline_time="14:00:00"), user=self.user, db=self.db)
        self.assertEqual(self.pushes("2026-10-24T13:00"), [])
        update_step(self.step.id, StepUpdateIn(deadline_time="16:00"), user=self.user, db=self.db)
        self.assertEqual(self.pushes("2026-10-24T13:00"), [])
        self.assertEqual([p.lead for p in self.pushes("2026-10-24T15:00")], ["hour"])

    def test_early_timed_event_does_not_overlap_day_and_hour_windows(self):
        self.step.deadline_time = "00:30"
        self.db.commit()
        self.assertEqual([p.lead for p in self.pushes("2026-10-23T23:30")], ["hour"])

    def test_day_lead_is_not_sent_after_its_calendar_day(self):
        self.step.deadline_time = "14:00"
        self.db.commit()
        self.assertEqual(self.pushes("2026-10-24T08:30"), [])

    def test_next_step_starts_its_current_window_only_after_predecessor_completes(self):
        self.step.deadline = None
        following = RouteStep(
            route_id=self.route.id, position=2, title="Next", status="pending",
            deadline=date(2026, 10, 24), deadline_time="14:00", source="user",
        )
        self.db.add(following)
        self.db.commit()
        self.assertEqual(self.pushes("2026-10-24T13:00"), [])
        complete_route_step(self.db, self.user.id, self.step.id)
        pushes = self.pushes("2026-10-24T13:00")
        self.assertEqual([(p.ref_id, p.lead) for p in pushes], [(following.id, "hour")])
        mark_sent(self.db, pushes[0])
        self.assertEqual(self.pushes("2026-10-24T13:00"), [])


if __name__ == "__main__":
    unittest.main()
