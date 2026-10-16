"""Acceptance tests for durable PDF queue state and deduplication."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bot import exporter
from core.db.models import Base, ExportRequest, User
from core.db.session import _migrate_sqlite
from server.api.v1 import api


class PdfQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        with patch("core.db.session.engine", self.engine):
            _migrate_sqlite()
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            self.user = User(max_user_id=920001, consent_at=datetime.now(timezone.utc))
            db.add(self.user)
            db.commit()
            self.user_id = self.user.id

    def tearDown(self):
        self.engine.dispose()

    def test_only_one_active_request_per_user(self):
        with self.sessions() as db:
            user = db.get(User, self.user_id)
            first = api.request_pdf_in_chat(user=user, db=db)
            repeated = [api.request_pdf_in_chat(user=user, db=db) for _ in range(99)]
        self.assertEqual(first["status"], "queued")
        self.assertTrue(all(row["status"] == "queued" for row in repeated))
        self.assertEqual({row["request_id"] for row in repeated}, {first["request_id"]})
        with self.sessions() as db:
            self.assertEqual(db.query(ExportRequest).filter_by(user_id=self.user_id).count(), 1)

    def test_database_rejects_a_second_active_request(self):
        with self.sessions() as db:
            db.add(ExportRequest(user_id=self.user_id))
            db.commit()
        with self.sessions() as db:
            db.add(ExportRequest(user_id=self.user_id))
            with self.assertRaises(IntegrityError):
                db.commit()

    async def run_tick(self, now, send):
        async def stop(_):
            raise asyncio.CancelledError()

        with (
            patch.object(exporter, "SessionLocal", self.sessions),
            patch.object(exporter, "utcnow", return_value=now),
            patch.object(exporter, "send_health_pdf", side_effect=send),
            patch.object(exporter.asyncio, "sleep", stop),
            patch.object(exporter.log, "exception"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await exporter.export_watcher_loop(object())

    async def test_temporary_outage_recovers_without_extra_request(self):
        start = datetime(2026, 10, 17, 10)
        with self.sessions() as db:
            db.add(ExportRequest(user_id=self.user_id, created_at=start))
            db.commit()
        attempts_seen = []

        async def fail(*args):
            with self.sessions() as db:
                attempts_seen.append(db.query(ExportRequest).one().attempts)
            raise OSError("MAX unavailable")

        async def succeed(*args):
            with self.sessions() as db:
                attempts_seen.append(db.query(ExportRequest).one().attempts)

        await self.run_tick(start, fail)
        await self.run_tick(start + timedelta(seconds=29), fail)
        self.assertEqual(attempts_seen, [0])
        await self.run_tick(start + timedelta(seconds=30), fail)
        await self.run_tick(start + timedelta(seconds=149), succeed)
        self.assertEqual(attempts_seen, [0, 1])
        await self.run_tick(start + timedelta(seconds=150), succeed)
        await self.run_tick(start + timedelta(seconds=153), succeed)
        self.assertEqual(attempts_seen, [0, 1, 2])
        with self.sessions() as db:
            row = db.query(ExportRequest).one()
            self.assertEqual((row.status, row.attempts), ("sent", 3))
            self.assertEqual(row.sent_at, start + timedelta(seconds=150))
            self.assertIsNone(row.next_attempt_at)
            self.assertIsNone(row.last_error)

    async def test_exhausted_attempts_are_visible_and_allow_manual_retry(self):
        now = datetime(2026, 10, 17, 10)
        with self.sessions() as db:
            first = api.request_pdf_in_chat(user=db.get(User, self.user_id), db=db)
        attempts_seen = []

        async def fail(*args):
            with self.sessions() as db:
                attempts_seen.append(db.query(ExportRequest).one().attempts)
            raise OSError("MAX unavailable")

        for attempt, delay in enumerate((30, 120, 300, 900, None), start=1):
            await self.run_tick(now, fail)
            with self.sessions() as db:
                row = db.query(ExportRequest).one()
                self.assertEqual(row.attempts, attempt)
                self.assertIsNone(row.sent_at)
                if delay is not None:
                    self.assertEqual(row.status, "retry")
                    self.assertEqual(row.next_attempt_at, now + timedelta(seconds=delay))
                else:
                    self.assertEqual(row.status, "failed")
                    self.assertIsNone(row.next_attempt_at)
            if delay is not None:
                now += timedelta(seconds=delay)

        await self.run_tick(now + timedelta(seconds=3), fail)
        self.assertEqual(attempts_seen, [0, 1, 2, 3, 4])
        with self.sessions() as db:
            user = db.get(User, self.user_id)
            status = api.pdf_in_chat_status(user=user, db=db)
            self.assertEqual(status["status"], "failed")
            self.assertTrue(status["can_retry"])
            self.assertIn("PDF в чат", status["hint"])
            retried = api.request_pdf_in_chat(user=user, db=db)
            self.assertNotEqual(retried["request_id"], first["request_id"])
            self.assertEqual(retried["status"], "queued")
            self.assertEqual(db.get(ExportRequest, retried["request_id"]).attempts, 0)

    def test_startup_preserves_retries_until_current_attempt_limit(self):
        scheduled = datetime(2026, 10, 17, 11)
        with self.sessions() as db:
            for attempts in (3, 4, 5):
                user = User(max_user_id=920010 + attempts)
                db.add(user)
                db.flush()
                db.add(ExportRequest(
                    user_id=user.id, attempts=attempts, status="retry",
                    next_attempt_at=scheduled,
                ))
            db.commit()
        with patch("core.db.session.engine", self.engine):
            _migrate_sqlite()
            _migrate_sqlite()
        with self.sessions() as db:
            rows = {row.attempts: row for row in db.query(ExportRequest).all()}
            for attempts in (3, 4):
                self.assertEqual(rows[attempts].status, "retry")
                self.assertEqual(rows[attempts].next_attempt_at, scheduled)
            self.assertEqual(rows[5].status, "failed")
            self.assertIsNone(rows[5].next_attempt_at)

    async def test_attempt_is_incremented_after_failed_attempt_and_backoff_is_set(self):
        with self.sessions() as db:
            db.add(ExportRequest(user_id=self.user_id))
            db.commit()

        async def fail_send(*args, **kwargs):
            raise OSError("MAX unavailable")

        async def stop(_):
            raise asyncio.CancelledError()

        with (
            patch.object(exporter, "SessionLocal", self.sessions),
            patch.object(exporter, "send_health_pdf", side_effect=fail_send),
            patch.object(exporter.asyncio, "sleep", stop),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await exporter.export_watcher_loop(object())

        with self.sessions() as db:
            row = db.query(ExportRequest).one()
            self.assertEqual(row.attempts, 1)
            self.assertEqual(row.status, "retry")
            self.assertIsNotNone(row.next_attempt_at)
            self.assertIn("OSError", row.last_error)

    async def test_success_marks_sent_after_attempt(self):
        with self.sessions() as db:
            db.add(ExportRequest(user_id=self.user_id))
            db.commit()

        async def succeed(*args, **kwargs):
            return None

        async def stop(_):
            raise asyncio.CancelledError()

        with (
            patch.object(exporter, "SessionLocal", self.sessions),
            patch.object(exporter, "send_health_pdf", side_effect=succeed),
            patch.object(exporter.asyncio, "sleep", stop),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await exporter.export_watcher_loop(object())

        with self.sessions() as db:
            row = db.query(ExportRequest).one()
            self.assertEqual((row.attempts, row.status), (1, "sent"))
            self.assertIsNotNone(row.sent_at)


if __name__ == "__main__":
    unittest.main()
