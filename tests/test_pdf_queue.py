"""Acceptance tests for durable PDF queue state and deduplication."""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bot import exporter
from core.db.models import Base, ExportRequest, User
from server.api.v1 import api


class PdfQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
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
            second = api.request_pdf_in_chat(user=user, db=db)
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "queued")
        self.assertEqual(first["request_id"], second["request_id"])
        with self.sessions() as db:
            self.assertEqual(db.query(ExportRequest).filter_by(user_id=self.user_id).count(), 1)

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
