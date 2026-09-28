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

# WAL: API и бот пишут в одну базу из разных процессов — журнал делает блокировки мягче
if _settings.database_url.startswith("sqlite"):
    from sqlalchemy import event  # noqa: PLC0415

    @event.listens_for(engine, "connect")
    def _sqlite_wal(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    from core.db.models import Base  # noqa: PLC0415 — импорт в функции, чтобы таблицы видели все модели

    Base.metadata.create_all(engine)
    _migrate_sqlite()
    _migrate_bp_records()


def _migrate_sqlite() -> None:
    """create_all не ALTER-ит существующие таблицы — досоздаём колонки, появившиеся после релиза."""
    from sqlalchemy import inspect, text  # noqa: PLC0415

    if not _settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    plans: dict[str, list[tuple[str, str]]] = {
        "users": [
            ("consent_at", "DATETIME NULL"),
            ("avatar_url", "VARCHAR(500) NULL DEFAULT ''"),
            ("tz", "VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'"),
            ("region", "VARCHAR(100) NOT NULL DEFAULT ''"),
        ],
        "route_steps": [("source", "VARCHAR(16) NOT NULL DEFAULT 'template'")],
        "organizations": [("region", "VARCHAR(100) NOT NULL DEFAULT ''")],
        "reminders": [("sent_at", "DATETIME NULL"), ("done_at", "DATETIME NULL")],
        "health_settings": [("push_time", "VARCHAR(5) NULL")],
    }
    with engine.begin() as conn:
        for table, columns in plans.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            inspector.clear_cache()


def _migrate_bp_records() -> None:
    """Разовый перенос старого дневника АД в единую таблицу health_records."""
    from collections import Counter  # noqa: PLC0415

    from sqlalchemy import inspect, text  # noqa: PLC0415

    inspector = inspect(engine)
    if "bp_records" not in inspector.get_table_names() or "health_records" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS data_migrations (name VARCHAR(100) PRIMARY KEY)"))
        if conn.execute(text("SELECT 1 FROM data_migrations WHERE name = 'bp_records_v2'")).first():
            return
        # Старая миграция могла уже перенести часть строк. Сравниваем кратности,
        # чтобы сохранить одинаковые измерения и не создавать дубли при обновлении.
        columns = "user_id, at, systolic, diastolic, pulse"
        existing = Counter(
            tuple(row) for row in conn.execute(text(f"SELECT {columns} FROM health_records WHERE type = 'bp'"))
        )
        legacy = conn.execute(text(f"SELECT id, {columns} FROM bp_records ORDER BY id"))
        for row in legacy:
            values = tuple(row)[1:]
            if existing[values]:
                existing[values] -= 1
                continue
            conn.execute(
                text(
                    "INSERT INTO health_records (user_id, type, at, systolic, diastolic, pulse) "
                    "SELECT user_id, 'bp', at, systolic, diastolic, pulse FROM bp_records WHERE id = :id"
                ),
                {"id": row[0]},
            )
        conn.execute(text("INSERT INTO data_migrations (name) VALUES ('bp_records_v2')"))
