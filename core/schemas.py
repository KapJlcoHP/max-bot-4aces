"""Pydantic-DTO, общие для server и bot."""

from datetime import date as Date, datetime

from pydantic import BaseModel, ConfigDict


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


class BpRecordDto(OrmDto):
    id: int
    at: datetime
    systolic: int
    diastolic: int
    pulse: int


class BpAddIn(OrmDto):
    systolic: int
    diastolic: int
    pulse: int


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
