"""Regression tests for date-bound medication callback buttons."""

import importlib
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import Settings, get_settings
from core.db.models import Base, MedCourse, MedIntake, User


class MedicationCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        settings = Settings.model_construct(
            database_url="sqlite://",
            max_bot_token="",
            test_api_token="",
            miniapp_public_url="",
            yandex_maps_api_key="",
        )
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.enterContext(patch("core.config.Settings", return_value=settings))
        self.enterContext(patch(
            "pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_files",
            side_effect=AssertionError("Medication callback tests must not read .env files"),
        ))
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.actions = importlib.import_module("bot.handlers.actions")
        self.enterContext(patch.object(self.actions, "SessionLocal", self.sessions))
        self.enterContext(patch.object(self.actions, "_DIALOGS", {}))
        self.throttle = importlib.import_module("bot.throttle")
        self.enterContext(patch.object(self.throttle, "_hits", {}))
        with self.sessions() as db:
            user = User(
                max_user_id=950001,
                consent_at=datetime(2026, 10, 1),
                tz="UTC",
            )
            db.add(user)
            db.flush()
            self.user_id = user.id
            self.max_user_id = user.max_user_id
            course = MedCourse(user_id=user.id, name="Препарат", times=["09:00"])
            db.add(course)
            db.commit()
            self.course_id = course.id

    def event(self, payload):
        return SimpleNamespace(
            callback=SimpleNamespace(
                user=SimpleNamespace(user_id=self.max_user_id),
                payload=payload,
            ),
            answer=AsyncMock(),
        )

    async def test_stale_callback_uses_push_date_instead_of_today(self):
        event = self.event(f"mtake_{self.course_id}_20261017_0900")

        await self.actions.cb_med_taken(event, data={"test": True})

        with self.sessions() as db:
            intake = db.query(MedIntake).one()
            self.assertEqual(intake.day, date(2026, 10, 17))
            self.assertNotEqual(intake.day, date(2026, 10, 18))
        event.answer.assert_awaited_once()
        self.assertEqual(event.answer.await_args.kwargs["new_text"], "✅ Принято: Препарат, 09:00")

    async def test_legacy_callback_without_date_does_not_write_today(self):
        event = self.event(f"mtake_{self.course_id}_0900")

        await self.actions.cb_med_taken(event, data={"test": True})

        with self.sessions() as db:
            self.assertEqual(db.query(MedIntake).count(), 0)
        event.answer.assert_awaited_once()
        self.assertIn("устарела", event.answer.await_args.kwargs["notification"])

    async def test_disabled_course_rejects_old_callback_without_intake(self):
        with self.sessions() as db:
            course = db.get(MedCourse, self.course_id)
            course.enabled = False
            db.commit()

        event = self.event(f"mtake_{self.course_id}_20261017_0900")
        await self.actions.cb_med_taken(event, data={"test": True})

        with self.sessions() as db:
            self.assertEqual(db.query(MedIntake).count(), 0)
        event.answer.assert_awaited_once()
        self.assertIn("отключён", event.answer.await_args.kwargs["notification"])

    async def test_completed_course_rejects_callback_after_until_date(self):
        with self.sessions() as db:
            course = db.get(MedCourse, self.course_id)
            course.until = date(2026, 10, 16)
            db.commit()

        event = self.event(f"mtake_{self.course_id}_20261017_0900")
        await self.actions.cb_med_taken(event, data={"test": True})

        with self.sessions() as db:
            self.assertEqual(db.query(MedIntake).count(), 0)
        event.answer.assert_awaited_once()
        self.assertIn("завершён", event.answer.await_args.kwargs["notification"])


if __name__ == "__main__":
    unittest.main()
