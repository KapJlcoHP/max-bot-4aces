"""SQLAlchemy-модели. SQLite для MVP, апгрейд до Postgres — сменой DSN в .env."""

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    max_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")  # демо-поле профиля
    notifications_on: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 152-ФЗ: дата согласия
    avatar_url: Mapped[str] = mapped_column(String(500), default="")  # фото из MAX, если платформа его отдала
    tz: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")  # IANA-зона с телефона — «настенные» времена пушей
    region: Mapped[str] = mapped_column(String(100), default="")  # регион из content/regions.json
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    routes: Mapped[list["Route"]] = relationship(back_populates="user")


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    situation_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="routes")
    steps: Mapped[list["RouteStep"]] = relationship(
        back_populates="route", order_by="RouteStep.position", cascade="all, delete-orphan"
    )


class RouteStep(Base):
    __tablename__ = "route_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default="")
    place: Mapped[str] = mapped_column(String(200), default="")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | current | done
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_checklist: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="template")  # template | user | doctor

    route: Mapped[Route] = relationship(back_populates="steps")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    collected: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Organization(Base):
    """Справочник организаций — модельные (демо) данные кейса."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    org_type: Mapped[str] = mapped_column(String(40), default="Поликлиники")
    region: Mapped[str] = mapped_column(String(100), default="")  # регион из content/regions.json
    address: Mapped[str] = mapped_column(String(300))
    phone: Mapped[str] = mapped_column(String(40))
    hours: Mapped[str] = mapped_column(String(200))
    services: Mapped[list] = mapped_column(JSON, default=list)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    place: Mapped[str] = mapped_column(String(200), default="")
    at: Mapped[datetime] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # момент наступления отправлен ботом
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # «Выполнено» из бота


class HealthRecord(Base):
    """Единая запись дневника здоровья. Тип задаёт набор заполненных полей.

    Правило кейса: только факты — никаких «норма/выше нормы», оценки делает врач.
    """

    __tablename__ = "health_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # bp | weight | sugar | mood
    at: Mapped[datetime] = mapped_column(DateTime)
    # bp
    systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pulse: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # weight
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # sugar
    sugar_mmol: Mapped[float | None] = mapped_column(Float, nullable=True)
    meal_tag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # до еды | после еды
    # mood
    mood: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Хорошо | Нормально | Плохо
    pain: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..10
    # общий контекст
    tag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # утром | вечером | ...
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class HealthSetting(Base):
    """Какие дневники ведёт пользователь — персонализация с первой минуты."""

    __tablename__ = "health_settings"
    __table_args__ = (UniqueConstraint("user_id", "diary", name="uq_health_settings_user_diary"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    diary: Mapped[str] = mapped_column(String(16))  # bp | weight | sugar | mood
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    push_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM" — пуш от бота, None = выключен


class MedCourse(Base):
    """Курс лекарства: название + одно или несколько времён приёма в день."""

    __tablename__ = "med_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    times: Mapped[list] = mapped_column(JSON, default=list)  # ["09:00", "13:00"]
    until: Mapped[date | None] = mapped_column(Date, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MedIntake(Base):
    """Отметка приёма: курс × день × время. taken_at — когда пользователь нажал «принято»."""

    __tablename__ = "med_intakes"
    __table_args__ = (UniqueConstraint("course_id", "day", "at_time", name="uq_med_intake_slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("med_courses.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    at_time: Mapped[str] = mapped_column(String(20))
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotificationLog(Base):
    """Журнал пушей бота: один и тот же напоминатель не отправляем дважды (lead: day | hour | now)."""

    __tablename__ = "notification_log"
    __table_args__ = (UniqueConstraint("kind", "ref_id", "lead", name="uq_notification_kind_ref_lead"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # reminder | med
    ref_id: Mapped[int] = mapped_column(Integer)
    lead: Mapped[str] = mapped_column(String(16))  # day | hour | now | HH:MM (для лекарств)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExportRequest(Base):
    """Заявка мини-апа «прислать PDF-сводку в чат бота»: API кладёт, ��от-вотчер отправляет.

    Обходной путь для телефонов — вебвью MAX блокирует скачивание файлов.
    """

    __tablename__ = "export_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class BpRecord(Base):
    """Устаревшая таблица АД — оставлена для разовой миграции в HealthRecord."""

    __tablename__ = "bp_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    systolic: Mapped[int] = mapped_column(Integer)
    diastolic: Mapped[int] = mapped_column(Integer)
    pulse: Mapped[int] = mapped_column(Integer)


class FamilyMember(Base):
    """Демо-модель семейного доступа: владелец — user_id, участники добавляются записями."""

    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(16), default="blue")  # pink | yellow | blue
