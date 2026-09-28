"""Валидация подписанного initData (только сервер, HMAC-SHA256, как в доках MAX)."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import User
from core.db.seed import pilot_region

HEADER = "X-Max-Init-Data"
DEV_USER_MAX_ID = 0
INIT_DATA_MAX_AGE = timedelta(hours=24)
INIT_DATA_CLOCK_SKEW = timedelta(minutes=1)


class AuthError(Exception):
    pass


def _parse_init_data(raw: str) -> dict[str, str]:
    """Пары key=value; значения URL-декодируются один раз (parse_qsl)."""
    pairs: dict[str, str] = {}
    for key, value in parse_qsl(raw, keep_blank_values=True):
        pairs[key] = value
    return pairs


def validate_init_data(raw: str) -> dict | None:
    """Проверяет подпись и срок действия initData."""
    settings = get_settings()
    if not settings.max_bot_token or not raw:
        return None

    pairs = _parse_init_data(raw)
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    # Исключили hash → сортировка по ключу → склейка \n (как в примере из доков MAX).
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.max_bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None

    try:
        auth_date = datetime.fromtimestamp(int(pairs["auth_date"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    now = datetime.now(timezone.utc)
    if auth_date > now + INIT_DATA_CLOCK_SKEW or now - auth_date > INIT_DATA_MAX_AGE:
        return None

    return pairs


def _parse_user(payload: dict) -> dict:
    try:
        user = json.loads(payload["user"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("Некорректные данные пользователя") from exc
    if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**63:
        raise AuthError("Некорректные данные пользователя")
    if any(user.get(field) is not None and not isinstance(user[field], str) for field in ("first_name", "last_name", "avatar_url", "photo_url")):
        raise AuthError("Некорректные данные пользователя")
    return user


def get_or_create_user(db: Session, init_data: str | None) -> User:
    """Валидирует initData (если передан) и заводит пользователя с демо-данными при первом входе.

    При dev_bypass_auth и отсутствии/невалидном initData работаем под демо-пользователем.
    """
    settings = get_settings()
    user_payload: dict = {}

    if init_data:
        validated = validate_init_data(init_data)
        if validated is not None:
            user_payload = _parse_user(validated)
        elif not settings.dev_bypass_auth:
            raise AuthError("Подпись initData не прошла проверку")

    if not user_payload:
        if not settings.dev_bypass_auth:
            raise AuthError("initData отсутствует")
        user_payload = {"id": DEV_USER_MAX_ID, "first_name": "Анна", "last_name": "Иванова"}

    max_id = user_payload["id"]
    user = db.query(User).filter(User.max_user_id == max_id).first()
    if user is None:
        user = User(
            max_user_id=max_id,
            first_name=user_payload.get("first_name") or "Пользователь",
            last_name=user_payload.get("last_name") or "",
            email=f"user{max_id}@demo.local",
            avatar_url=user_payload.get("avatar_url") or user_payload.get("photo_url") or "",
            region=pilot_region(),  # регион пилотного запуска — потом выбирается в профиле
        )
        # чистый аккаунт: маршрут и дневники пользователь заводит сам
        db.add(user)
        db.commit()
    else:
        # фото из MAX может появиться/смениться между запусками — подтягиваем при входе
        fresh_avatar = user_payload.get("avatar_url") or user_payload.get("photo_url") or ""
        if fresh_avatar and fresh_avatar != user.avatar_url:
            user.avatar_url = fresh_avatar
            db.commit()
    return user
