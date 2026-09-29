"""Тестовый доступ к API по X-Test-Token: проверка платформой (см. DATA-API.yaml)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, User
from server.deps import TEST_USER_MAX_ID, AuthError, PendingUser, get_authenticated_user
from server.deps import test_token_ok as token_matches  # алиас без префикса test_ — иначе pytest зовёт её как тест

SETTINGS = SimpleNamespace(max_bot_token="bot-token", dev_bypass_auth=False, test_api_token="secret-token")
SETTINGS_NO_TOKEN = SimpleNamespace(max_bot_token="bot-token", dev_bypass_auth=False, test_api_token="")


class TestTokenTests(unittest.TestCase):
    def test_token_comparison(self):
        with patch("server.deps.get_settings", return_value=SETTINGS):
            self.assertTrue(token_matches("secret-token"))
            self.assertFalse(token_matches("wrong"))
            self.assertFalse(token_matches(None))
        with patch("server.deps.get_settings", return_value=SETTINGS_NO_TOKEN):
            self.assertFalse(token_matches("secret-token"))  # токен не настроен — доступ закрыт

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_token_returns_pending_profile_without_creating_account(self):
        with patch("server.deps.get_settings", return_value=SETTINGS):
            user = get_authenticated_user(self.db, None, test_token="secret-token")
            self.assertIsInstance(user, PendingUser)
            self.assertEqual(user.max_user_id, TEST_USER_MAX_ID)
            self.assertEqual(self.db.query(User).count(), 0)
            again = get_authenticated_user(self.db, None, test_token="secret-token")
            self.assertIsInstance(again, PendingUser)
            self.assertEqual(again.max_user_id, user.max_user_id)

            self.db.add(User(max_user_id=TEST_USER_MAX_ID, first_name="Сохранённый"))
            self.db.commit()
            persisted = get_authenticated_user(self.db, None, test_token="secret-token")
            self.assertIsInstance(persisted, User)
            self.assertEqual(persisted.first_name, "Сохранённый")

    def test_without_token_access_is_denied(self):
        with patch("server.deps.get_settings", return_value=SETTINGS):
            with self.assertRaises(AuthError):
                get_authenticated_user(self.db, None, test_token="wrong")
            with self.assertRaises(AuthError):
                get_authenticated_user(self.db, None)
        with patch("server.deps.get_settings", return_value=SETTINGS_NO_TOKEN):
            with self.assertRaises(AuthError):
                get_authenticated_user(self.db, None, test_token="secret-token")

    def test_valid_token_overrides_bad_init_data(self):
        with patch("server.deps.get_settings", return_value=SETTINGS):
            user = get_authenticated_user(self.db, "garbage-not-signed", test_token="secret-token")
            self.assertIsInstance(user, PendingUser)
            self.assertEqual(user.max_user_id, TEST_USER_MAX_ID)
            self.assertEqual(user.first_name, "Тестовая")
            self.assertEqual(self.db.query(User).count(), 0)


if __name__ == "__main__":
    unittest.main()
