"""Real diary handlers with private settings, database and MAX transport isolated."""

import importlib
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import Settings, get_settings
from core.db.models import Base, HealthRecord, User


class DiaryTextHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # model_construct bypasses BaseSettings sources entirely: no .env or
        # inherited credentials are read, even on the first handler import.
        settings = Settings.model_construct(
            database_url="sqlite://",
            max_bot_token="",
            test_api_token="",
            miniapp_public_url="",
            yandex_maps_api_key="",
        )
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        # Keep get_settings itself real so modules imported here do not retain
        # a mocked function after this test's patches are restored.
        self.enterContext(patch("core.config.Settings", return_value=settings))
        self.enterContext(patch(
            "pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_files",
            side_effect=AssertionError("Diary handler tests must not read .env files"),
        ))
        self.enterContext(patch(
            "socket.socket.connect",
            side_effect=AssertionError("Diary handler tests must not use the network"),
        ))
        self.actions = importlib.import_module("bot.handlers.actions")
        self.throttle = importlib.import_module("bot.throttle")
        self.enterContext(patch.object(self.actions, "_DIALOGS", {}))
        self.enterContext(patch.object(self.throttle, "_hits", {}))

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.enterContext(patch.object(self.actions, "SessionLocal", self.sessions))
        with self.sessions() as db:
            user = User(max_user_id=940001, consent_at=datetime(2026, 10, 18))
            db.add(user)
            db.commit()
            self.user_id = user.id
            self.max_user_id = user.max_user_id

    def event(self, text, username="diary_test_bot"):
        return SimpleNamespace(
            message=SimpleNamespace(
                sender=SimpleNamespace(user_id=self.max_user_id),
                body=SimpleNamespace(text=text),
                answer=AsyncMock(),
            ),
            bot=SimpleNamespace(me=SimpleNamespace(username=username)),
        )

    def assert_single_record(self, diary, **values):
        # A separate session proves the real service committed the record.
        with self.sessions() as db:
            row = db.query(HealthRecord).one()
            self.assertEqual(row.user_id, self.user_id)
            self.assertEqual(row.type, diary)
            for key, value in values.items():
                self.assertEqual(getattr(row, key), value)

    async def assert_saved(self, diary, text, saved, *, context=None, **values):
        self.actions._DIALOGS.setdefault(self.max_user_id, {"diary": diary, **(context or {})})
        event = self.event(text)
        previous_hits = len(self.throttle._hits.get(self.max_user_id, []))
        # Router.register returns the original throttled callable. Exercise it,
        # including dispatcher kwargs filtering, rather than __wrapped__.
        await self.actions.diary_text_input(event, data={"test": True})

        self.assert_single_record(diary, **values)
        self.assertNotIn(self.max_user_id, self.actions._DIALOGS)
        self.assertEqual(len(self.throttle._hits[self.max_user_id]), previous_hits + 1)
        event.message.answer.assert_awaited_once()
        args, kwargs = event.message.answer.await_args
        self.assertEqual(args, (f"✅ Записал: {saved}. 💙",))
        attachments = kwargs["attachments"]
        self.assertEqual(len(attachments), 1)
        markup = attachments[0].model_dump(mode="json")
        self.assertEqual(markup["type"], "inline_keyboard")
        buttons = markup["payload"]["buttons"]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(len(buttons[0]), 1)
        button = buttons[0][0]
        self.assertEqual(button["type"], "open_app")
        self.assertEqual(button["web_app"], "diary_test_bot")
        self.assertEqual(button["payload"], "health")

        # Repeating the input after completion cannot save a second record.
        await self.actions.diary_text_input(self.event(text))
        self.assert_single_record(diary, **values)

    async def test_weight_success_confirms_with_health_link(self):
        await self.assert_saved("weight", "82,5", "82,5 кг", weight_kg=82.5)

    async def test_bp_success_confirms_with_health_link(self):
        await self.assert_saved(
            "bp", "120/80, пульс 72", "120/80, пульс 72",
            systolic=120, diastolic=80, pulse=72,
        )

    async def test_sugar_success_preserves_meal_context(self):
        await self.assert_saved(
            "sugar", "5,5", "5,5 ммоль/л (до еды)",
            context={"meal": "до еды"}, sugar_mmol=5.5, meal_tag="до еды",
        )

    async def test_mood_success_preserves_selected_mood(self):
        await self.assert_saved(
            "mood", "3", "самочувствие — Хорошо, боль 3/10",
            context={"mood": "Хорошо"}, mood="Хорошо", pain=3,
        )

    async def test_success_without_username_confirms_without_markup(self):
        self.actions._DIALOGS[self.max_user_id] = {"diary": "weight"}
        event = self.event("82,5", username=None)

        await self.actions.diary_text_input(event)

        self.assert_single_record("weight", weight_kg=82.5)
        self.assertNotIn(self.max_user_id, self.actions._DIALOGS)
        event.message.answer.assert_awaited_once_with(
            "✅ Записал: 82,5 кг. 💙", attachments=None,
        )

    async def test_validation_error_keeps_dialog_for_successful_retry(self):
        dialog = {"diary": "weight"}
        self.actions._DIALOGS[self.max_user_id] = dialog
        event = self.event("999")

        await self.actions.diary_text_input(event)

        with self.sessions() as db:
            self.assertEqual(db.query(HealthRecord).count(), 0)
        self.assertIs(self.actions._DIALOGS[self.max_user_id], dialog)
        event.message.answer.assert_awaited_once_with(
            "Вес вне допустимого диапазона\nПопробуйте ещё раз.",
        )
        await self.assert_saved("weight", "82,5", "82,5 кг", weight_kg=82.5)


if __name__ == "__main__":
    unittest.main()
