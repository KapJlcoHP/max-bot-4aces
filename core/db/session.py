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
        "export_requests": [
            ("status", "VARCHAR(16) NOT NULL DEFAULT 'queued'"),
            ("next_attempt_at", "DATETIME NULL"),
            ("last_error", "VARCHAR(500) NULL"),
        ],
    }
    with engine.begin() as conn:
        # API и bot могут стартовать одновременно. Проверяем схему и ALTER
        # под одной SQLite writer-lock, а introspection использует то же
        # соединение (особенно важно для in-memory тестов).
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        inspector = inspect(conn)
        for table, columns in plans.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            inspector.clear_cache()

        # Существующие заявки получают явные состояния. Отправленные заявки
        # никогда не должны блокировать новую заявку пользователя.
        if "export_requests" in inspector.get_table_names():
            conn.execute(text("UPDATE export_requests SET status = 'sent' WHERE sent_at IS NOT NULL"))
            conn.execute(text("UPDATE export_requests SET status = 'queued' WHERE status IS NULL OR status = ''"))
            conn.execute(text(
                "UPDATE export_requests SET status = 'failed', next_attempt_at = NULL, "
                "last_error = COALESCE(last_error, 'Лимит попыток исчерпан') "
                "WHERE sent_at IS NULL AND attempts >= 3 AND status NOT IN ('failed', 'sent')"
            ))
            # При обновлении могли остаться несколько старых активных заявок.
            # Оставляем последнюю, остальные переводим в понятный terminal-state.
            duplicates = conn.execute(text(
                "SELECT user_id, MAX(id) AS keep_id FROM export_requests "
                "WHERE sent_at IS NULL AND status NOT IN ('failed', 'sent') GROUP BY user_id "
                "HAVING COUNT(*) > 1"
            )).fetchall()
            for user_id, keep_id in duplicates:
                conn.execute(
                    text(
                        "UPDATE export_requests SET status = 'failed', last_error = 'superseded by newer request' "
                        "WHERE user_id = :user_id AND sent_at IS NULL AND status NOT IN ('failed', 'sent') AND id <> :keep_id"
                    ),
                    {"user_id": user_id, "keep_id": keep_id},
                )
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_active_user "
                "ON export_requests (user_id) WHERE sent_at IS NULL AND status NOT IN ('failed', 'sent')"
            ))

        # В ранней схеме дедуп был глобальным по kind/ref/lead: одинаковые id
        # разных пользователей взаимно подавляли пуши. SQLite не умеет снять
        # UNIQUE constraint через ALTER TABLE, поэтому аккуратно пересоздаём
        # только эту небольшую таблицу при обнаружении старого constraint.
        if "notification_log" in inspector.get_table_names():
            constraints = inspector.get_unique_constraints("notification_log")
            old = any(c.get("name") == "uq_notification_kind_ref_lead" for c in constraints)
            if old:
                conn.execute(text(
                    "CREATE TABLE notification_log_new ("
                    "id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL, kind VARCHAR(16) NOT NULL, "
                    "ref_id INTEGER NOT NULL, lead VARCHAR(16) NOT NULL, sent_at DATETIME NOT NULL, "
                    "CONSTRAINT uq_notification_user_kind_ref_lead UNIQUE (user_id, kind, ref_id, lead), "
                    "FOREIGN KEY(user_id) REFERENCES users(id))"
                ))
                conn.execute(text(
                    "INSERT INTO notification_log_new (id, user_id, kind, ref_id, lead, sent_at) "
                    "SELECT id, user_id, kind, ref_id, lead, sent_at FROM notification_log"
                ))
                conn.execute(text("DROP TABLE notification_log"))
                conn.execute(text("ALTER TABLE notification_log_new RENAME TO notification_log"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_user_kind_ref_lead "
                "ON notification_log (user_id, kind, ref_id, lead)"
            ))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notification_log_user_id ON notification_log (user_id)"))

        # Старые Reminder.at были пользовательским настенным временем. Перевод
        # выполняется один раз; новые записи уже нормализуются API при записи.
        if "reminders" in inspector.get_table_names() and "users" in inspector.get_table_names():
            from datetime import datetime
            from core.time import db_utc, user_zone

            conn.execute(text("CREATE TABLE IF NOT EXISTS data_migrations (name VARCHAR(100) PRIMARY KEY)"))
            if not conn.execute(text("SELECT 1 FROM data_migrations WHERE name = 'reminder_at_utc_v1'")).first():
                for reminder_id, at, tz in conn.execute(text(
                    "SELECT r.id, r.at, u.tz FROM reminders r JOIN users u ON u.id = r.user_id"
                )).fetchall():
                    value = datetime.fromisoformat(at) if isinstance(at, str) else at
                    conn.execute(text("UPDATE reminders SET at = :at WHERE id = :id"), {
                        "at": db_utc(value, user_zone(tz)), "id": reminder_id,
                    })
                conn.execute(text("INSERT INTO data_migrations (name) VALUES ('reminder_at_utc_v1')"))



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
