"""Event dates/times are optional, partial updates preserve omitted fields."""

from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db.models import Base, NotificationLog, Route, RouteStep, User
from core.schemas import CustomStepIn, StepAddIn, StepUpdateIn
from server.api.v1 import route as api


DAY = date(2026, 10, 20)
NEXT_DAY = date(2026, 10, 21)


@pytest.mark.parametrize("dto", [StepAddIn, CustomStepIn, StepUpdateIn])
@pytest.mark.parametrize("raw, expected", [
    ("8:00", "08:00"), ("08:00", "08:00"), ("08:00:00", "08:00"),
    (" 9:05 ", "09:05"), ("00:00", "00:00"), ("23:59:00", "23:59"),
    (None, None),
])
def test_time_normalization(dto, raw, expected):
    body = dto(title="Visit", deadline=DAY, deadline_time=raw)
    assert body.deadline_time == expected
    assert dto.model_validate_json(body.model_dump_json()).deadline_time == expected


@pytest.mark.parametrize("dto", [StepAddIn, CustomStepIn, StepUpdateIn])
@pytest.mark.parametrize("raw", [
    "", " ", "24:00", "12:60", "12:00:01", "9:5", "noon", "12",
    "12:00Z", "12:00+03:00", "12:00:00.0", 1200, False,
])
def test_invalid_time_is_rejected(dto, raw):
    with pytest.raises(ValidationError):
        dto(title="Visit", deadline=DAY, deadline_time=raw)


@pytest.mark.parametrize("dto", [StepAddIn, CustomStepIn])
@pytest.mark.parametrize("fields", [{}, {"deadline": None}])
def test_creation_requires_date_for_non_null_time(dto, fields):
    with pytest.raises(ValidationError):
        dto(title="Visit", deadline_time="08:00", **fields)


@pytest.mark.parametrize("dto", [StepAddIn, CustomStepIn])
@pytest.mark.parametrize("fields", [
    {}, {"deadline": None}, {"deadline_time": None},
    {"deadline": None, "deadline_time": None}, {"deadline": DAY},
])
def test_creation_accepts_optional_date_and_time_without_fabricating_time(dto, fields):
    body = dto(title="Visit", **fields)
    assert body.deadline == fields.get("deadline")
    assert body.deadline_time is None


@pytest.mark.parametrize("fields", [
    {}, {"deadline": None}, {"deadline_time": None},
    {"deadline": None, "deadline_time": None}, {"deadline": DAY},
    {"deadline_time": "08:00"},
])
def test_patch_preserves_explicit_fields_through_round_trip(fields):
    body = StepUpdateIn(**fields)
    assert body.model_fields_set == set(fields)
    restored = StepUpdateIn.model_validate_json(body.model_dump_json(exclude_unset=True))
    assert restored.model_fields_set == set(fields)
    assert restored.model_dump(exclude_unset=True) == fields


def test_patch_rejects_explicit_null_date_with_non_null_time():
    with pytest.raises(ValidationError):
        StepUpdateIn(deadline=None, deadline_time="08:00")


@pytest.fixture
def schedule_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(max_user_id=780001, consent_at=datetime.now(timezone.utc))
        other = User(max_user_id=780002, consent_at=datetime.now(timezone.utc))
        db.add_all([user, other])
        db.flush()
        route = Route(user_id=user.id, situation_key="custom", title="Schedule")
        db.add(route)
        db.flush()
        step = RouteStep(
            route_id=route.id, position=1, title="Visit", status="current",
            deadline=DAY, deadline_time="08:00", source="user",
        )
        db.add(step)
        db.commit()
        yield db, user, other, route, step
    engine.dispose()


@pytest.fixture
def client(schedule_db):
    db, user, _, _, _ = schedule_db
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.db_session] = lambda: db
    app.dependency_overrides[api.consented_user] = lambda: user
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("old_date, old_time, fields, expected_date, expected_time", [
    (DAY, "08:00", {}, DAY, "08:00"),
    (None, None, {}, None, None),
    (DAY, "08:00", {"deadline": "2026-10-21"}, NEXT_DAY, "08:00"),
    (DAY, None, {"deadline": "2026-10-21"}, NEXT_DAY, None),
    (None, None, {"deadline": "2026-10-21"}, NEXT_DAY, None),
    (DAY, "08:00", {"deadline": None}, None, None),
    (DAY, "08:00", {"deadline_time": "9:15:00"}, DAY, "09:15"),
    (DAY, None, {"deadline_time": "9:15"}, DAY, "09:15"),
    (DAY, "08:00", {"deadline_time": None}, DAY, None),
    (None, None, {"deadline_time": None}, None, None),
    (DAY, "08:00", {"deadline": None, "deadline_time": None}, None, None),
    (None, None, {"deadline": "2026-10-21", "deadline_time": "0:00"}, NEXT_DAY, "00:00"),
    (DAY, "08:00", {"deadline": "2026-10-21", "deadline_time": None}, NEXT_DAY, None),
])
def test_http_patch_round_trip(client, schedule_db, old_date, old_time, fields, expected_date, expected_time):
    db, _, _, _, step = schedule_db
    step.deadline, step.deadline_time = old_date, old_time
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{step.id}", json=fields)
    assert response.status_code == 200, response.text
    expected = (expected_date.isoformat() if expected_date else None, expected_time)
    assert (response.json()["deadline"], response.json()["deadline_time"]) == expected
    db.expire_all()
    assert (step.deadline, step.deadline_time) == (expected_date, expected_time)
    fetched = client.get("/api/v1/route").json()["steps"][0]
    assert (fetched["deadline"], fetched["deadline_time"]) == expected


@pytest.mark.parametrize("fields", [
    {"deadline_time": "08:00"},
    {"deadline": None, "deadline_time": "08:00"},
    {"deadline": "not-a-date"}, {"deadline_time": "24:00"},
])
def test_http_invalid_patch_is_atomic(client, schedule_db, fields):
    db, user, _, _, step = schedule_db
    step.deadline = None
    step.deadline_time = None
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="day"))
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{step.id}", json=fields)
    assert response.status_code == 422, response.text
    db.expire_all()
    assert (step.deadline, step.deadline_time) == (None, None)
    assert db.query(NotificationLog).count() == 1


def test_direct_api_time_only_without_date_is_422(schedule_db):
    db, user, _, _, step = schedule_db
    step.deadline, step.deadline_time = None, None
    db.commit()
    with pytest.raises(HTTPException) as error:
        api.update_step(step.id, StepUpdateIn(deadline_time="08:00"), user=user, db=db)
    assert error.value.status_code == 422
    assert (step.deadline, step.deadline_time) == (None, None)


def test_empty_patch_does_not_repair_or_reject_legacy_orphan_time(client, schedule_db):
    db, user, _, _, step = schedule_db
    step.deadline = None
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="day"))
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{step.id}", json={})
    assert response.status_code == 200
    db.expire_all()
    assert (step.deadline, step.deadline_time) == (None, "08:00")
    assert db.query(NotificationLog).count() == 1


@pytest.mark.parametrize("fields, changed", [
    ({}, False), ({"deadline": "2026-10-20"}, False),
    ({"deadline_time": "8:00:00"}, False),
    ({"deadline": "2026-10-20", "deadline_time": "08:00"}, False),
    ({"deadline": "2026-10-21"}, True), ({"deadline_time": "09:00"}, True),
    ({"deadline_time": None}, True), ({"deadline": None}, True),
])
def test_dedup_invalidation_is_scoped_to_actual_schedule_changes(client, schedule_db, fields, changed):
    db, user, other, _, step = schedule_db
    target_ids = []
    for lead in ("day", "hour", "now"):
        log = NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead=lead)
        db.add(log)
        db.flush()
        target_ids.append(log.id)
    isolated_logs = [
        NotificationLog(user_id=other.id, kind="step", ref_id=step.id, lead="day"),
        NotificationLog(user_id=user.id, kind="reminder", ref_id=step.id, lead="day"),
        NotificationLog(user_id=user.id, kind="step", ref_id=step.id + 100, lead="day"),
    ]
    db.add_all(isolated_logs)
    db.commit()
    isolated_ids = {log.id for log in isolated_logs}
    response = client.patch(f"/api/v1/route/steps/{step.id}", json=fields)
    assert response.status_code == 200, response.text
    remaining_ids = {log.id for log in db.query(NotificationLog).all()}
    assert remaining_ids == isolated_ids | (set() if changed else set(target_ids))


@pytest.mark.parametrize("fields", [{}, {"deadline": None}, {"deadline_time": None}])
def test_repeated_null_clears_preserve_dedup(client, schedule_db, fields):
    db, user, _, _, step = schedule_db
    step.deadline, step.deadline_time = None, None
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="day"))
    db.commit()
    assert client.patch(f"/api/v1/route/steps/{step.id}", json=fields).status_code == 200
    assert db.query(NotificationLog).count() == 1


@pytest.mark.parametrize("fields", [
    {"deadline_time": "08:00"}, {"deadline_time": "8:00:00"},
    {"deadline": "2026-10-20"},
])
def test_equivalent_legacy_clock_does_not_renew_dedup(client, schedule_db, fields):
    db, user, _, _, step = schedule_db
    step.deadline_time = "8:00"
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="hour"))
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{step.id}", json=fields)
    assert response.status_code == 200
    assert db.query(NotificationLog).count() == 1
    assert response.json()["deadline_time"] == ("08:00" if "deadline_time" in fields else "8:00")


@pytest.mark.parametrize("status, expected", [("current", 200), ("pending", 200), ("done", 409)])
def test_status_guards(client, schedule_db, status, expected):
    db, user, _, _, step = schedule_db
    step.status = status
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="day"))
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{step.id}", json={"deadline_time": "09:00"})
    assert response.status_code == expected
    db.expire_all()
    assert step.deadline_time == ("08:00" if status == "done" else "09:00")
    assert db.query(NotificationLog).count() == (1 if status == "done" else 0)
    if status == "done":
        assert client.patch(f"/api/v1/route/steps/{step.id}", json={}).status_code == 409


@pytest.mark.parametrize("target", ["other_user", "inactive", "missing", "no_active_route"])
def test_step_must_belong_to_users_active_route(client, schedule_db, target):
    db, user, other, route, step = schedule_db
    target_step = step
    if target in ("other_user", "inactive"):
        hidden = Route(
            user_id=other.id if target == "other_user" else user.id,
            situation_key="custom", title="Hidden", active=target == "other_user",
        )
        db.add(hidden)
        db.flush()
        target_step = RouteStep(
            route_id=hidden.id, position=1, title="Hidden visit", status="current",
            deadline=DAY, deadline_time="08:00",
        )
        db.add(target_step)
    elif target == "no_active_route":
        route.active = False
    db.flush()
    target_id = target_step.id if target != "missing" else step.id + 100
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=target_id, lead="day"))
    db.commit()
    response = client.patch(f"/api/v1/route/steps/{target_id}", json={"deadline": None})
    assert response.status_code == 404
    db.expire_all()
    assert (target_step.deadline, target_step.deadline_time) == (DAY, "08:00")
    assert db.query(NotificationLog).count() == 1


@pytest.mark.parametrize("endpoint", ["add", "start"])
@pytest.mark.parametrize("fields, expected_time", [
    ({}, None), ({"deadline": "2026-10-20"}, None),
    ({"deadline": None, "deadline_time": None}, None),
    ({"deadline": "2026-10-20", "deadline_time": "8:00:00"}, "08:00"),
])
def test_http_creation_round_trip(client, endpoint, fields, expected_time):
    custom = {"title": "New visit", **fields}
    url = "/api/v1/route/steps" if endpoint == "add" else "/api/v1/route/start"
    payload = custom if endpoint == "add" else {"situation_key": "custom", "custom_steps": [custom]}
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    created = next(step for step in response.json()["steps"] if step["title"] == "New visit")
    assert (created["deadline"], created["deadline_time"]) == (fields.get("deadline"), expected_time)
    fetched = next(step for step in client.get("/api/v1/route").json()["steps"] if step["id"] == created["id"])
    assert (fetched["deadline"], fetched["deadline_time"]) == (fields.get("deadline"), expected_time)


@pytest.mark.parametrize("endpoint", ["add", "start"])
@pytest.mark.parametrize("fields", [
    {"deadline_time": "08:00"}, {"deadline": None, "deadline_time": "08:00"},
    {"deadline": "2026-10-20", "deadline_time": "12:00:01"},
])
def test_http_creation_rejects_invalid_schedule_without_mutation(client, schedule_db, endpoint, fields):
    db, _, _, route, step = schedule_db
    custom = {"title": "Invalid", **fields}
    url = "/api/v1/route/steps" if endpoint == "add" else "/api/v1/route/start"
    payload = custom if endpoint == "add" else {"situation_key": "custom", "custom_steps": [custom]}
    assert client.post(url, json=payload).status_code == 422
    db.expire_all()
    assert route.active
    assert db.query(Route).count() == 1
    assert db.query(RouteStep).one().id == step.id
