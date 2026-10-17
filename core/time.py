"""Единая конвенция времени backend.

Все абсолютные даты в базе хранятся как UTC. SQLite теряет ``tzinfo`` у
DateTime, поэтому функции ниже явно восстанавливают UTC для прочитанных
значений. Пользовательские даты/время без смещения считаются настенным
временем ``User.tz`` и переводятся в UTC при записи.
"""

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo


UTC = timezone.utc
DEFAULT_TZ = "Europe/Moscow"


def normalize_clock_time(value: str) -> str | None:
    """Normalize a local clock value to the app's canonical ``HH:MM`` form.

    Medication schedules have minute precision.  Accept the forms users and
    older clients commonly send (``8:00``, ``08:00`` and ``08:00:00``), but
    reject invalid values and non-zero seconds instead of silently changing the
    scheduled minute.
    """
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(value))
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second != 0:
        return None
    return f"{hour:02d}:{minute:02d}"


def user_zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def as_utc(value: datetime, assume_zone: ZoneInfo | None = None) -> datetime:
    """Вернуть aware UTC; naive значение трактуется в ``assume_zone``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=assume_zone or UTC)
    return value.astimezone(UTC)


def db_utc(value: datetime, assume_zone: ZoneInfo | None = None) -> datetime:
    """UTC в форме, безопасной для SQLite DateTime (без tzinfo)."""
    return as_utc(value, assume_zone).replace(tzinfo=None)


def user_local(value: datetime, tz: str | None) -> datetime:
    return as_utc(value).astimezone(user_zone(tz))


def local_day_bounds(day: date, tz: str | None) -> tuple[datetime, datetime]:
    zone = user_zone(tz)
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
    return start, end


def report_window(now: datetime, tz: str | None, days: int = 30) -> tuple[datetime, datetime, datetime, datetime]:
    """(UTC start/end для БД, local start/end для отображения)."""
    local_now = user_local(now, tz)
    local_start = local_now - timedelta(days=days)
    return db_utc(local_start), db_utc(now), local_start, local_now
