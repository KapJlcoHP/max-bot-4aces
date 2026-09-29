"""Валидация подписанного initData (только сервер, HMAC-SHA256, как в доках MAX)."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import User
from core.db.seed import pilot_region

HEADER = "X-Max-Init-Data"
DEV_USER_MAX_ID = 0
TEST_USER_MAX_ID = 909_001  # тестовая учётная запись для проверки API платформой
INIT_DATA_MAX_AGE = timedelta(hours=24)
INIT_DATA_CLOCK_SKEW = timedelta(minutes=1)


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class PendingUser:
    """Проверенный профиль MAX до согласия; в БД не записывается."""

    max_user_id: int
    first_name: str
    last_name: str
    email: str
    avatar_url: str
    region: str
    id: int = 0  # служебное значение только в ответе GET /me
    notifications_on: bool = True
    tz: str = "Europe/Moscow"
    consent_at: None = None


def test_token_ok(test_token: str | None) -> bool:
    """X-Test-Token совпадает с настроенным TEST_API_TOKEN (пустой настроечный = выключено)."""
    configured = get_settings().test_api_token
    if not configured or not test_token:
        return False
    return hmac.compare_digest(test_token, configured)


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


def get_authenticated_user(db: Session, init_data: str | None, test_token: str | None = None) -> User | PendingUser:
    """Валидирует initData и возвращает профиль, не записывая нового пользователя до согласия.

    При dev_bypass_auth и отсутствии/невалидном initData работаем под демо-пользователем.
    Если initData нет/невалиден, но передан верный X-Test-Token — работаем с
    тестовым профилем (проверка API платформой, см. DATA-API.yaml).
    """
    settings = get_settings()
    user_payload: dict = {}

    if init_data:
        validated = validate_init_data(init_data)
        if validated is not None:
            user_payload = _parse_user(validated)
        elif not (test_token_ok(test_token) or settings.dev_bypass_auth):
            raise AuthError("Подпись initData не прошла проверку")

    if not user_payload:
        if test_token_ok(test_token):
            user_payload = {"id": TEST_USER_MAX_ID, "first_name": "Тестовая", "last_name": "учётная запись"}
        elif settings.dev_bypass_auth:
            user_payload = {"id": DEV_USER_MAX_ID, "first_name": "Анна", "last_name": "Иванова"}
        else:
            raise AuthError("initData отсутствует")

    max_id = user_payload["id"]
    user = db.query(User).filter(User.max_user_id == max_id).first()
    if user is None:
        return PendingUser(
            max_user_id=max_id,
            first_name=user_payload.get("first_name") or "Пользователь",
            last_name=user_payload.get("last_name") or "",
            email=f"user{max_id}@demo.local",
            avatar_url=user_payload.get("avatar_url") or user_payload.get("photo_url") or "",
            region=pilot_region(),
        )
    # До согласия существующий профиль не обновляем. После согласия фото из MAX
    # может измениться; обновляем его при следующем входе.
    fresh_avatar = user_payload.get("avatar_url") or user_payload.get("photo_url") or ""
    if user.consent_at is not None and fresh_avatar and fresh_avatar != user.avatar_url:
        user.avatar_url = fresh_avatar
        db.commit()
    return user
