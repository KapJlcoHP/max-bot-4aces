from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import get_settings

_settings = get_settings()

# SQLite: разрешаем использование соединения из разных потоков uvicorn
connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

# Каталог под sqlite-файл создаём сами (sqlite3 этого не делает)
if _settings.database_url.startswith("sqlite:///./"):
    Path(_settings.database_url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)

# autoflush оставляем включённым (по умолчанию): иначе незакоммиченные мутации
# не видны собственным запросам сессии (ловили на этом баг «шаг не завершается»).
engine = create_engine(_settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    from core.db.models import Base  # noqa: PLC0415 — импорт в функции, чтобы таблицы видели все модели

    Base.metadata.create_all(engine)
