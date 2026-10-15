"""REST API v1: совместимый фасад и сборка доменных роутеров.

Публичные функции остаются доступны по старому пути ``server.api.v1.api``.
Доменные реализации находятся в соседних модулях, а фасад сохраняет старые
имена и точки monkeypatch для тестов и фоновых callers.
"""

from zoneinfo import ZoneInfo

from fastapi import APIRouter

from core.db.models import (
    BpRecord,
    ChecklistItem,
    ExportRequest,
    FamilyMember,
    HealthRecord,
    HealthSetting,
    MedCourse,
    MedIntake,
    NotificationLog,
    Organization,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.db.seed import build_route_for, load_catalog, load_regions, load_scenarios
from core.diary_settings import DEFAULT_DIARIES, diary_settings, enabled_diaries
from core.schemas import *  # noqa: F401,F403 - исторически экспортировалось из api.py
from core.services import (
    ServiceError,
    add_health_record as create_health_record,
    complete_route_step,
    take_med,
    uncomplete_route_step,
    user_today,
)
from core.time import db_utc, report_window, user_local, user_zone
from server.deps import AuthError, PendingUser, get_authenticated_user
from server.health_pdf import build_health_pdf

from . import common, health, meds, misc, profile, route

router = APIRouter(prefix="/api/v1")
for domain_router in (profile.router, route.router, misc.router, health.router, meds.router):
    router.include_router(domain_router)

HEALTH_TYPES = common.HEALTH_TYPES

# Совместимые имена общих helpers.
db_session = common.db_session
current_user = common.current_user
consented_user = common.consented_user
route_dto = common.route_dto
_validate_diary_settings = common.validate_diary_settings
_apply_diary_settings = common.apply_diary_settings
_get_active_route = common.get_active_route

# Совместимые имена доменных helpers.
_reminder_dto = misc._reminder_dto
_health_record_dto = health._health_record_dto
_meds_out = meds._meds_out
_diary_settings = health._diary_settings
_get_diary_settings = health._get_diary_settings
_EXPORT_TOKENS = health._EXPORT_TOKENS
_EXPORT_TTL = health._EXPORT_TTL

# Реэкспорт endpoint-функций для старых прямых callers и unit-тестов.
me = profile.me
delete_my_data = profile.delete_my_data
update_settings = profile.update_settings
regions = profile.regions
catalog = profile.catalog
catalog_steps = profile.catalog_steps

get_route = route.get_route
delete_route = route.delete_route
start_route = route.start_route
add_step = route.add_step
delete_step = route.delete_step
complete_step = route.complete_step
uncomplete_step = route.uncomplete_step
update_step = route.update_step

checklist = misc.checklist
toggle_checklist_item = misc.toggle_checklist_item
add_checklist_item = misc.add_checklist_item
orgs = misc.orgs
org_detail = misc.org_detail
maps_config = misc.maps_config
reminders = misc.reminders
toggle_reminder = misc.toggle_reminder
add_reminder = misc.add_reminder
family = misc.family
add_family_member = misc.add_family_member

health_settings = health.health_settings
update_health_settings = health.update_health_settings
health_records = health.health_records
create_export_token = health.create_export_token
request_pdf_in_chat = health.request_pdf_in_chat
pdf_in_chat_status = health.pdf_in_chat_status
add_health_record = health.add_health_record
delete_health_record = health.delete_health_record

_meds_endpoint = meds.meds
add_med = meds.add_med
toggle_intake = meds.toggle_intake
disable_med = meds.disable_med
meds = _meds_endpoint


def give_consent(body=None, user=None, db=None):
    """Совместимая обёртка с сохранением patch(api.ZoneInfo) в тестах."""
    return profile.give_consent_impl(body, user, db, zone_info_cls=ZoneInfo)


def health_report(user=None, db=None):
    """Совместимая обёртка с сохранением patch(api.utcnow) и settings helper."""
    return health.health_report_impl(
        user,
        db,
        now_fn=utcnow,
        get_diary_settings_fn=_get_diary_settings,
    )


def export_health_pdf(request, t=None, db=None):
    """Совместимая обёртка для callers, патчащих helpers на фасаде."""
    return health.export_health_pdf_impl(
        request,
        t,
        db,
        auth_fn=get_authenticated_user,
        report_fn=health_report,
        diary_settings_fn=_get_diary_settings,
        pdf_builder=build_health_pdf,
    )
