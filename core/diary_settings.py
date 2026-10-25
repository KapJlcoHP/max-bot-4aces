"""Единый effective-view настроек; отсутствующая строка использует DEFAULT_DIARIES.

Чтение не создаёт настройки. PUT/onboarding сохраняют только явно переданные
строки и сохраняют настройки остальных дневников (существующий контракт).
"""

from sqlalchemy.orm import Session

from core.db.models import HealthSetting
from core.schemas import HealthSettingDto

DIARIES = ("bp", "weight", "sugar", "mood")
DEFAULT_DIARIES = {"bp": True, "weight": True, "sugar": False, "mood": True}


def diary_settings(db: Session, user_id: int) -> dict[str, HealthSettingDto]:
    rows = {row.diary: row for row in db.query(HealthSetting).filter_by(user_id=user_id).all()}
    return {
        diary: HealthSettingDto(
            diary=diary,
            enabled=rows[diary].enabled if diary in rows else DEFAULT_DIARIES[diary],
            push_time=rows[diary].push_time if diary in rows else None,
        )
        for diary in DIARIES
    }


def enabled_diaries(db: Session, user_id: int) -> dict[str, bool]:
    return {diary: setting.enabled for diary, setting in diary_settings(db, user_id).items()}
