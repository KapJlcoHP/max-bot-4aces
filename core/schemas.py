"""Pydantic-DTO, общие для server и bot."""

from datetime import date as Date, datetime

from pydantic import BaseModel, ConfigDict, Field


class OrmDto(BaseModel):
    """База для DTO, собираемых из ORM-объектов."""

    model_config = ConfigDict(from_attributes=True)


class UserDto(OrmDto):
    id: int
    max_user_id: int
    first_name: str
    last_name: str
    email: str
    notifications_on: bool
    consent_at: datetime | None = None


class SituationDto(OrmDto):
    key: str
    title: str
    description: str
    icon: str


class StepDto(OrmDto):
    id: int
    position: int
    title: str
    description: str
    place: str
    deadline: Date | None = None
    deadline_time: str | None = None
    status: str
    has_checklist: bool
    note: str | None = None
    source: str = "template"


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


class StepAddIn(OrmDto):
    """Новый шаг маршрута: назначение врача (source=doctor) или свой пункт (source=user)."""

    title: str
    deadline: Date | None = None
    deadline_time: str | None = None
    place: str = ""
    source: str = "user"  # user | doctor


class CustomStepIn(OrmDto):
    """Свой шаг при создании маршрута из конструктора."""

    title: str
    deadline: Date | None = None
    deadline_time: str | None = None


class RouteStartIn(OrmDto):
    situation_key: str
    exclude_positions: list[int] = Field(default_factory=list)
    custom_steps: list[CustomStepIn] = Field(default_factory=list)


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
    address: str
    phone: str
    hours: str
    services: list[str]


class ReminderDto(OrmDto):
    id: int
    title: str
    place: str
    at: datetime
    enabled: bool


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


class FamilyMemberDto(OrmDto):
    id: int
    name: str
    role: str
    color: str


class FamilyAddIn(OrmDto):
    name: str
    role: str = "Родственник"


class SettingsIn(OrmDto):
    notifications_on: bool | None = None
    email: str | None = None


RouteDto.model_rebuild()
CompleteStepOut.model_rebuild()
