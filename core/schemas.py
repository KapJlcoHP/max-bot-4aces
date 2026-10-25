"""Pydantic-DTO, общие для server и bot."""

from datetime import date as Date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, PrivateAttr, model_validator

from core.time import as_utc, normalize_clock_time


def _normalize_step_clock(value: str) -> str:
    normalized = normalize_clock_time(value)
    if normalized is None:
        raise ValueError("Некорректное время шага: ожидается HH:MM")
    return normalized


_StepClockTime = Annotated[
    str,
    AfterValidator(_normalize_step_clock),
    Field(description="Местное время события в поясе профиля; нормализуется в HH:MM. Требует даты."),
]

StepReminderMode = Literal["profile", "day", "hour", "custom"]
StepKind = Literal["unknown", "visit", "booking", "investigation", "task", "process"]
_UtcMoment = Annotated[datetime, AfterValidator(as_utc)]


class OrmDto(BaseModel):
    """База для DTO, собираемых из ORM-объектов."""

    model_config = ConfigDict(from_attributes=True)


class UserDto(OrmDto):
    id: int
    max_user_id: int
    first_name: str
    last_name: str
    email: str
    avatar_url: str = ""
    notifications_on: bool
    notify_day_before: bool = True
    notify_hour_before: bool = True
    notify_at_deadline: bool = True
    step_day_before_time: str = "09:00"
    region: str = ""
    city: str | None = None
    attached_clinic_id: int | None = None
    consent_at: datetime | None = None
    contains_demo_data: bool = False


class RegionDto(OrmDto):
    """Регион из content/regions.json: добавление региона — правка файла, без кода."""

    key: str
    title: str
    pilot: bool = False
    cities: list["CityDto"] = Field(default_factory=list)


class CityDto(BaseModel):
    """Город из пилотного справочника; техническая зона наружу не выходит."""

    key: str
    title: str
    region: str


class ConsentIn(OrmDto):
    """Согласие и настройки первого входа сохраняются одной транзакцией."""

    region: str | None = None
    city: str | None = None
    diaries: list["HealthSettingDto"] | None = None
    attached_clinic_id: int | None = None


class ClinicChangeIn(OrmDto):
    """Явный подтверждённый выбор с проверкой состояния профиля из открытого окна."""

    attached_clinic_id: int = Field(gt=0)
    expected_clinic_id: int | None = Field(..., gt=0)
    expected_region: str = Field(min_length=1)


class SituationDto(OrmDto):
    key: str
    title: str
    description: str
    icon: str


class FaqItemDto(BaseModel):
    """One plain-language answer from the versioned static FAQ content."""

    id: str
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    order: int = Field(ge=1)
    source_ids: list[str] | None = None


class FaqOut(BaseModel):
    items: list[FaqItemDto] = Field(min_length=1)


class TemplateStepDto(OrmDto):
    position: int
    title: str
    has_checklist: bool = False
    key: str | None = None
    kind: StepKind = "unknown"
    booking_target_key: str | None = None
    description: str = ""


class ContentSourceDto(OrmDto):
    id: str
    title: str
    url: HttpUrl
    checked_at: Date | None = None
    checked_by: str | None = None
    checked_where: str | None = None
    scope: str


class StepDto(OrmDto):
    id: int
    kind: StepKind = "unknown"
    template_key: str | None = None
    booking_target_step_id: int | None = None
    appointment_date: Date | None = None
    reminder_revision: int = 0
    position: int
    title: str
    description: str
    place: str
    deadline: Date | None = None
    deadline_time: str | None = None
    reminder_mode: StepReminderMode = "profile"
    reminder_at: _UtcMoment | None = None
    activated_at: _UtcMoment | None = None
    status: str
    completed_at: datetime | None = None
    has_checklist: bool
    note: str | None = None
    source: str = "template"
    reason: str = Field(default="", description="Почему шаг появился в маршруте пользователя")
    source_id: str | None = None
    source_info: ContentSourceDto | None = None


class RouteDto(OrmDto):
    id: int
    situation_key: str
    title: str
    subtitle: str
    active: bool
    total_steps: int
    done_steps: int
    steps: list[StepDto]


class CompleteStepIn(OrmDto):
    date: Date | None = None
    note: str | None = None


class CompleteStepOut(OrmDto):
    step: StepDto
    route: "RouteDto"
    next_step: StepDto | None = None


class DoctorAssignmentIn(OrmDto):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    kind: StepKind = "unknown"
    appointment_date: Date | None = None
    deadline: Date | None = None
    deadline_time: _StepClockTime | None = None
    place: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.deadline is None and self.deadline_time is not None:
            raise ValueError("Время шага требует даты")
        if self.kind == "booking" and self.deadline_time is not None:
            raise ValueError("Запись не принимает точное время оформления")
        if self.kind != "booking" and self.appointment_date is not None:
            raise ValueError("Полученная дата допустима только для записи")
        return self


class StepAssignmentsIn(OrmDto):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    complete: bool = Field(strict=True)
    assignments: list[DoctorAssignmentIn]

    @model_validator(mode="after")
    def validate_batch(self):
        if not self.complete and not self.assignments:
            raise ValueError("Добавьте хотя бы одно назначение")
        return self


class StepAssignmentsOut(CompleteStepOut):
    added_step_ids: list[int]


class StepBookingIn(OrmDto):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    complete: bool = Field(strict=True)
    appointment_date: Date | None
    target_step_id: int | None = Field(..., gt=0, strict=True)
    expected_target_revision: int | None = Field(default=None, ge=0, strict=True)
    confirm_target_change: bool = Field(default=False, strict=True)
    target_reminder_action: Literal["keep", "profile"] = "keep"


class StepUpdateIn(OrmDto):
    """PATCH срока: пропущенное поле сохраняется, null явно очищает его."""

    kind: StepKind = "unknown"
    booking_target_step_id: int | None = Field(default=None, gt=0, strict=True)
    deadline: Date | None = Field(
        default=None,
        description="Местная дата события. Пропуск сохраняет дату; null очищает дату и зависимое время.",
    )
    deadline_time: _StepClockTime | None = Field(
        default=None,
        description="Местное время HH:MM. Пропуск сохраняет время; null очищает только время. Требует даты.",
    )
    reminder_mode: StepReminderMode = "profile"
    reminder_at: datetime | None = None

    @model_validator(mode="after")
    def validate_explicit_date_clear(self):
        if "deadline" in self.model_fields_set and self.deadline is None and self.deadline_time is not None:
            raise ValueError("Время шага требует даты")
        return self


class StepAddIn(OrmDto):
    """Новый шаг маршрута: назначение врача (source=doctor) или свой пункт (source=user)."""

    model_config = ConfigDict(extra="forbid")

    title: str
    kind: StepKind = "unknown"
    booking_target_step_id: int | None = Field(default=None, gt=0, strict=True)
    appointment_date: Date | None = None
    deadline: Date | None = None
    deadline_time: _StepClockTime | None = None
    reminder_mode: StepReminderMode = "profile"
    reminder_at: datetime | None = None
    place: str = ""
    source: str = "user"  # user | doctor

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.deadline is None and self.deadline_time is not None:
            raise ValueError("Время шага требует даты")
        if self.kind == "booking" and self.deadline_time is not None:
            raise ValueError("Запись не принимает точное время оформления")
        if self.kind != "booking" and (self.booking_target_step_id is not None or self.appointment_date is not None):
            raise ValueError("Связь и дата записи допустимы только для шага booking")
        return self


class CustomStepIn(OrmDto):
    """Свой шаг при создании маршрута из конструктора."""

    title: str
    kind: StepKind = "unknown"
    client_key: str | None = Field(default=None, min_length=1, max_length=100)
    booking_target_key: str | None = Field(default=None, min_length=1, max_length=100)
    before_position: int | None = Field(default=None, gt=0, strict=True)
    appointment_date: Date | None = None
    deadline: Date | None = None
    deadline_time: _StepClockTime | None = None
    place: str = ""

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.deadline is None and self.deadline_time is not None:
            raise ValueError("Время шага требует даты")
        if self.kind == "booking" and self.deadline_time is not None:
            raise ValueError("Запись не принимает точное время оформления")
        if self.kind != "booking" and (self.booking_target_key is not None or self.appointment_date is not None):
            raise ValueError("Связь и дата записи допустимы только для шага booking")
        return self


class RouteStartIn(OrmDto):
    situation_key: str
    exclude_positions: list[int] = Field(default_factory=list)
    custom_steps: list[CustomStepIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_client_keys(self):
        keys = [step.client_key for step in self.custom_steps if step.client_key is not None]
        if len(keys) != len(set(keys)):
            raise ValueError("client_key должен быть уникальным")
        return self


class ChecklistItemDto(OrmDto):
    id: int
    title: str
    collected: bool


class ChecklistOut(OrmDto):
    items: list[ChecklistItemDto]
    collected: int
    total: int


class ChecklistAddIn(OrmDto):
    title: str


class OrganizationDto(OrmDto):
    id: int
    title: str
    org_type: str
    region: str = ""
    address: str
    phone: str
    hours: str
    services: list[str]
    lat: float | None = None
    lon: float | None = None


class MapConfigDto(BaseModel):
    """Публичная конфигурация JS API: сам ключ ограничивается доменом в кабинете."""

    enabled: bool
    api_key: str = ""


class ReminderDto(OrmDto):
    id: int
    title: str
    place: str
    at: datetime
    enabled: bool
    done_at: datetime | None = None


class ReminderAddIn(OrmDto):
    """Данные для создания напоминания."""

    title: str = Field(min_length=1)
    at: datetime
    place: str | None = None


class HealthRecordDto(OrmDto):
    id: int
    type: str
    at: datetime
    systolic: int | None = None
    diastolic: int | None = None
    pulse: int | None = None
    weight_kg: float | None = None
    sugar_mmol: float | None = None
    meal_tag: str | None = None
    mood: str | None = None
    pain: int | None = None
    tag: str | None = None
    note: str | None = None


class HealthAddIn(OrmDto):
    """Новая запись дневника; обязательные поля зависят от type (проверяются в эндпоинте)."""

    systolic: int | None = None
    diastolic: int | None = None
    pulse: int | None = None
    weight_kg: float | None = None
    sugar_mmol: float | None = None
    meal_tag: str | None = None
    mood: str | None = None
    pain: int | None = None
    tag: str | None = None
    note: str | None = None


class HealthSettingDto(OrmDto):
    diary: str
    enabled: bool
    push_time: str | None = None  # "HH:MM" — время пуша бота; None = напоминание выключено


class HealthSettingsOut(OrmDto):
    diaries: list[HealthSettingDto]


class HealthSettingsIn(OrmDto):
    diaries: list[HealthSettingDto]


class ReportMedsRow(OrmDto):
    name: str
    taken: int
    planned: int
    pct: int


class ReportNote(OrmDto):
    at: datetime
    note: str


class HealthReportOut(OrmDto):
    # Внутренний snapshot окна для PDF; не меняет JSON API.
    _window_now: datetime | None = PrivateAttr(default=None)
    period_days: int = 30
    bp_count: int = 0
    bp_avg: str | None = None  # «124/81»
    pulse_avg: int | None = None
    weight_latest: float | None = None
    weight_delta: float | None = None
    weight_count: int = 0
    sugar_avg: float | None = None
    sugar_count: int = 0
    meds: list[ReportMedsRow] = Field(default_factory=list)
    notes: list[ReportNote] = Field(default_factory=list)


class MedCourseDto(OrmDto):
    id: int
    name: str
    times: list[str]
    until: Date | None = None
    enabled: bool


class MedSlotDto(OrmDto):
    course_id: int
    name: str
    at_time: str
    taken: bool
    taken_at: datetime | None = None


class MedsOut(OrmDto):
    courses: list[MedCourseDto]
    today: list[MedSlotDto]


class MedAddIn(OrmDto):
    name: str
    times: list[str] = Field(min_length=1)
    until: Date | None = None


class MedIntakeToggleIn(OrmDto):
    """Время приёма лекарства, которое нужно отметить или снять."""

    at_time: str = Field(min_length=1)


class FamilyMemberDto(OrmDto):
    id: int
    name: str
    role: str
    color: str


class FamilyAddIn(OrmDto):
    name: str
    role: str = "Родственник"


class FamilyInviteIn(BaseModel):
    label: str = Field(default="Помощник", min_length=1, max_length=120)
    expires_days: int = Field(default=7, ge=1, le=30)


class FamilyAcceptIn(BaseModel):
    code: str = Field(min_length=8, max_length=32)


class FamilyAccessDto(BaseModel):
    id: int
    status: Literal["pending", "active", "revoked", "expired"]
    label: str
    owner_name: str
    viewer_name: str | None = None
    scopes: list[str]
    created_at: datetime
    accepted_at: datetime | None = None
    expires_at: datetime
    revoked_at: datetime | None = None


class FamilyInviteOut(BaseModel):
    access: FamilyAccessDto
    code: str


class FamilyDiaryStatusDto(BaseModel):
    diary: str
    label: str
    enabled: bool
    filled_today: bool
    last_record_at: datetime | None = None


class FamilyMedicationStatusDto(BaseModel):
    active_courses: int
    planned_today: int
    taken_today: int


class FamilyStepSnapshotDto(BaseModel):
    id: int
    position: int
    title: str
    kind: StepKind
    status: str
    appointment_date: Date | None = None
    deadline: Date | None = None
    deadline_time: str | None = None
    place: str = ""
    completed_at: datetime | None = None


class FamilyRouteSnapshotDto(BaseModel):
    title: str
    subtitle: str
    active: bool
    total_steps: int
    done_steps: int
    steps: list[FamilyStepSnapshotDto]


class FamilySnapshotDto(BaseModel):
    access_id: int
    owner_name: str
    generated_at: datetime
    route: FamilyRouteSnapshotDto | None = None
    diaries: list[FamilyDiaryStatusDto]
    medication: FamilyMedicationStatusDto


class SettingsIn(OrmDto):
    notifications_on: bool | None = None
    notify_day_before: bool | None = None
    notify_hour_before: bool | None = None
    notify_at_deadline: bool | None = None
    step_day_before_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    email: str | None = None
    region: str | None = None
    city: str | None = None
    attached_clinic_id: int | None = None
    confirm_clinic_reset: bool = False
    expected_clinic_id: int | None = Field(default=None, gt=0)
    expected_region: str | None = None


RegionDto.model_rebuild()
RouteDto.model_rebuild()
CompleteStepOut.model_rebuild()
