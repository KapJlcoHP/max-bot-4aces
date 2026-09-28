"""Regression checks for signed entry data and route progression."""

import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, Route, RouteStep, User
from core.services import ServiceError, complete_route_step, uncomplete_route_step
from server.deps import AuthError, _parse_user, validate_init_data


def signed_data(auth_date: int | None, user: object = None) -> str:
    fields = {"user": json.dumps(user if user is not None else {"id": 123})}
    if auth_date is not None:
        fields["auth_date"] = str(auth_date)
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class AuthTests(unittest.TestCase):
    def test_signed_data_has_a_limited_lifetime(self):
        now = datetime.now(timezone.utc)
        with patch("server.deps.get_settings", return_value=SimpleNamespace(max_bot_token="test-token")):
            self.assertIsNotNone(validate_init_data(signed_data(int(now.timestamp()))))
            self.assertIsNone(validate_init_data(signed_data(int((now - timedelta(days=2)).timestamp()))))
            self.assertIsNone(validate_init_data(signed_data(int((now + timedelta(minutes=2)).timestamp()))))
            self.assertIsNone(validate_init_data(signed_data(None)))

    def test_user_must_be_an_object_with_a_positive_integer_id(self):
        for raw in ("[]", "null", "{}", '{"id": 0}', '{"id": "123"}', '{"id": true}', '{"id": 9223372036854775808}', '{"id": 123, "first_name": 42}'):
            with self.subTest(raw=raw), self.assertRaises(AuthError):
                _parse_user({"user": raw})
        self.assertEqual(_parse_user({"user": '{"id": 123}'})["id"], 123)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        user = User(max_user_id=123)
        self.db.add(user)
        self.db.flush()
        route = Route(user_id=user.id, situation_key="test", title="Test")
        self.db.add(route)
        self.db.flush()
        self.steps = [
            RouteStep(route_id=route.id, position=i, title=f"Step {i}", status="current" if i == 1 else "pending")
            for i in range(1, 4)
        ]
        self.db.add_all(self.steps)
        self.db.commit()
        self.user_id = user.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_only_current_step_can_be_completed_and_undo_restores_it(self):
        first, second, third = self.steps
        with self.assertRaises(ServiceError) as caught:
            complete_route_step(self.db, self.user_id, third.id)
        self.assertEqual(caught.exception.status, 409)

        complete_route_step(self.db, self.user_id, first.id)
        self.assertEqual([step.status for step in self.steps], ["done", "current", "pending"])

        uncomplete_route_step(self.db, self.user_id, first.id)
        self.assertEqual([step.status for step in self.steps], ["current", "pending", "pending"])
        complete_route_step(self.db, self.user_id, first.id)
        self.assertEqual([step.status for step in self.steps], ["done", "current", "pending"])


if __name__ == "__main__":
    unittest.main()
