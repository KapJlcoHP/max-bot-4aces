"""Per-step reminder contract, persistence, DST, activation and delivery races.

All stores are SQLite memory databases and every bot call is a local test double.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bot.scheduler import collect_due, mark_sent, revalidate_step_push, scheduler_loop
from core.db import session as session_module
from core.db.models import Base, NotificationLog, Route, RouteStep, User
from core.schemas import RouteStartIn, StepUpdateIn
from core.services import complete_route_step, uncomplete_route_step
from server.api.v1 import route as api

NOW = datetime(2030, 1, 1, 9)
DAY = date(2030, 1, 3)


@pytest.fixture
def state():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        user = User(max_user_id=920001, tz="Europe/Moscow", consent_at=NOW)
        db.add(user)
        db.flush()
        route = Route(user_id=user.id, situation_key="custom", title="My route")
        db.add(route)
        db.flush()
        step = RouteStep(route_id=route.id, position=1, title="Visit", source="user",
                         status="current", deadline=DAY, deadline_time="14:00", activated_at=NOW)
        db.add(step)
        db.commit()
        app = FastAPI()
        app.include_router(api.router, prefix="/api/v1")
        app.dependency_overrides[api.db_session] = lambda: db
        app.dependency_overrides[api.consented_user] = lambda: user
        with patch.object(api, "utcnow", return_value=NOW), patch("core.services.utcnow", return_value=NOW):
            with TestClient(app) as client:
                yield db, user, route, step, client, sessions
    engine.dispose()


@pytest.mark.parametrize("mode, lead, start", [
    ("profile", "hour", datetime(2030, 1, 3, 10)),
    ("hour", "hour", datetime(2030, 1, 3, 10)),
    ("day", "day", datetime(2030, 1, 2, 6)),
])
@pytest.mark.parametrize("delta", [-1, 1])
def test_standard_windows_are_not_caught_up_after_late_activation(state, mode, lead, start, delta):
    db, user, route, first, _, _ = state
    first.deadline = None
    following = RouteStep(
        route_id=route.id, position=2, title="Next", status="pending",
        deadline=DAY, deadline_time="14:00", reminder_mode=mode,
    )
    db.add(following)
    db.commit()
    with patch("core.services.utcnow", return_value=start + timedelta(seconds=delta)):
        complete_route_step(db, user.id, first.id)
    pushes = collect_due(db, (start + timedelta(minutes=2)).replace(tzinfo=timezone.utc))
    assert [p.lead for p in pushes] == ([lead] if delta < 0 else [])


def test_route_and_initial_activation_are_saved_in_one_transaction(state):
    db, user, previous, _, _, _ = state
    with patch.object(api, "utcnow", side_effect=RuntimeError("clock unavailable")):
        with pytest.raises(RuntimeError):
            api.start_route(RouteStartIn(situation_key="custom", custom_steps=[{"title": "New"}]), user, db)
    db.rollback()
    db.expire_all()
    assert db.query(Route).count() == 1
    assert previous.active


@pytest.mark.parametrize("race", ["schedule", "done", "inactive"])
def test_concurrent_schedule_save_cannot_overwrite_newer_revision_or_completed_step(state, race):
    db, user, route, step, client, sessions = state
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="hour"))
    db.commit()
    original = api.reminder_setting

    def racing_setting(*args, **kwargs):
        values = original(*args, **kwargs)
        with sessions() as writer:
            target = writer.get(RouteStep, step.id)
            if race == "schedule":
                target.deadline_time = "18:00"
                target.reminder_revision += 1
            elif race == "done":
                target.status = "done"
            else:
                writer.get(Route, route.id).active = False
            writer.commit()
        return values

    with patch.object(api, "reminder_setting", side_effect=racing_setting):
        response = client.patch(f"/api/v1/route/steps/{step.id}", json={"deadline_time": "16:00"})
    assert response.status_code == 409
    db.expire_all()
    assert step.deadline_time == ("18:00" if race == "schedule" else "14:00")
    assert db.query(NotificationLog).count() == 1
    if race == "done":
        assert step.status == "done"


@pytest.mark.parametrize("activation_delta, expected", [(-1, ["custom"]), (1, [])])
def test_pending_timer_only_sends_if_still_future_at_activation(state, activation_delta, expected):
    db, user, route, first, _, _ = state
    first.deadline = None
    at = datetime(2030, 1, 2, 9)
    following = RouteStep(route_id=route.id, position=2, title="Pending", status="pending",
                          deadline=DAY, reminder_mode="custom", reminder_at=at)
    db.add(following)
    db.commit()
    now = (at + timedelta(minutes=2)).replace(tzinfo=timezone.utc)
    assert collect_due(db, now) == []
    # Editing a pending step preserves its status and never activates it.
    response = state[4].patch(f"/api/v1/route/steps/{following.id}", json={"reminder_mode": "custom", "reminder_at": "2030-01-02T09:00:00Z"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    with patch("core.services.utcnow", return_value=at + timedelta(seconds=activation_delta)):
        complete_route_step(db, user.id, first.id)
    assert following.status == "current"
    assert following.activated_at == at + timedelta(seconds=activation_delta)
    assert [p.lead for p in collect_due(db, now)] == expected
    if not expected:
        # An expired timer can be reset and a replacement is deliverable.
        response = state[4].patch(f"/api/v1/route/steps/{following.id}", json={"reminder_mode": "custom", "reminder_at": "2030-01-02T09:03:00Z"})
        assert response.status_code == 200
        assert [p.lead for p in collect_due(db, now + timedelta(minutes=2))] == ["custom"]


def test_undo_and_delete_current_also_record_activation(state):
    db, user, route, first, client, _ = state
    first.status = "done"
    first.reminder_mode = "custom"
    first.reminder_at = NOW - timedelta(seconds=1)
    following = RouteStep(route_id=route.id, position=2, title="Next", status="current", deadline=DAY,
                          reminder_mode="custom", reminder_at=NOW - timedelta(seconds=1))
    db.add(following)
    db.commit()
    uncomplete_route_step(db, user.id, first.id)
    assert first.activated_at == NOW
    assert following.status == "pending"
    assert collect_due(db, NOW.replace(tzinfo=timezone.utc)) == []
    response = client.delete(f"/api/v1/route/steps/{first.id}")
    assert response.status_code == 200
    db.refresh(following)
    assert following.activated_at == NOW and following.status == "current"
    assert collect_due(db, NOW.replace(tzinfo=timezone.utc)) == []


def test_newly_started_route_records_initial_activation(state):
    client = state[4]
    response = client.post("/api/v1/route/start", json={"situation_key": "custom", "custom_steps": [{"title": "Appointment", "deadline": "2030-01-03", "deadline_time": "16:15"}]})
    assert response.status_code == 200
    step = response.json()["steps"][0]
    assert step["activated_at"] == "2030-01-01T09:00:00Z"
    assert step["reminder_mode"] == "profile" and step["reminder_at"] is None


def test_add_step_with_reminder_is_persistent_and_invalid_add_does_not_reorder(state):
    db, _, _, step, client, _ = state
    payload = {"title": "New", "deadline": "2030-01-03", "reminder_mode": "custom", "reminder_at": "2030-01-02T12:00:00"}
    response = client.post("/api/v1/route/steps", json=payload)
    assert response.status_code == 200
    created = response.json()["steps"][1]
    assert created["status"] == "pending" and created["activated_at"] is None
    assert created["reminder_at"] == "2030-01-02T09:00:00Z"
    before = [(s.id, s.position) for s in db.query(RouteStep).order_by(RouteStep.position)]
    assert client.post("/api/v1/route/steps", json={**payload, "reminder_at": None}).status_code == 422
    assert [(s.id, s.position) for s in db.query(RouteStep).order_by(RouteStep.position)] == before


@pytest.mark.parametrize("change", ["done", "pending", "deleted", "inactive", "other_owner", "off", "moved", "mode", "profile_time", "timezone", "already_sent"])
def test_presend_revalidation_rejects_stale_push_from_fresh_database_state(state, change):
    db, user, route, step, _, sessions = state
    custom(state)
    now = datetime(2030, 1, 2, 9, tzinfo=timezone.utc)
    push = collect_due(db, now)[0]
    with sessions() as writer:
        target, owner, target_route = writer.get(RouteStep, step.id), writer.get(User, user.id), writer.get(Route, route.id)
        if change in ("done", "pending"):
            target.status = change
        elif change == "deleted":
            writer.delete(target)
        elif change == "inactive":
            target_route.active = False
        elif change == "other_owner":
            other = User(max_user_id=920002, tz="UTC")
            writer.add(other)
            writer.flush()
            target_route.user_id = other.id
        elif change == "off":
            owner.notifications_on = False
        elif change == "moved":
            target.deadline = date(2030, 1, 4)
        elif change == "mode":
            target.reminder_mode, target.reminder_at = "profile", None
        elif change == "profile_time":
            owner.step_day_before_time = "10:00"
        elif change == "timezone":
            owner.tz = "Asia/Tokyo"
        elif change == "already_sent":
            mark_sent(writer, push)
        writer.commit()
    assert not revalidate_step_push(db, push, now)


def test_old_inflight_receipt_cannot_suppress_new_revision(state):
    db, _, _, step, _, _ = state
    custom(state)
    now = datetime(2030, 1, 2, 9, tzinfo=timezone.utc)
    old = collect_due(db, now)[0]
    assert update(state, reminder_mode="custom", reminder_at="2030-01-02T09:01:00Z").status_code == 200
    # Delivery succeeded just before edit but its database receipt was delayed.
    mark_sent(db, old)
    replacement = collect_due(db, now + timedelta(minutes=1))
    assert len(replacement) == 1
    assert replacement[0].step_revision != old.step_revision
    mark_sent(db, replacement[0])
    assert collect_due(db, now + timedelta(minutes=2)) == []


@pytest.mark.parametrize("before_send", ["complete", "edit", "none"])
def test_real_scheduler_rechecks_before_network_and_retries_without_false_receipt(state, before_send):
    db, _, _, step, _, sessions = state
    custom(state)
    attempts, delivered, log_counts = [], [], []
    now = datetime(2030, 1, 2, 9)
    ticks = 0

    class Keyboard:
        def as_markup(self):
            return {}

    def keyboard(*_):
        if before_send != "none":
            with sessions() as writer:
                target = writer.get(RouteStep, step.id)
                if before_send == "complete":
                    target.status = "done"
                else:
                    target.reminder_at += timedelta(hours=1)
                    target.reminder_revision += 1
                writer.commit()
        return Keyboard()

    class Bot:
        async def send_message(self, **kwargs):
            attempts.append(kwargs)
            with sessions() as check:
                log_counts.append(check.query(NotificationLog).count())
            if len(attempts) == 1:
                raise OSError("network unavailable")
            delivered.append(kwargs)

    async def stop(_):
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            raise asyncio.CancelledError()

    with patch("bot.scheduler.SessionLocal", sessions), patch("bot.scheduler._user_now", return_value=now + timedelta(hours=3)), patch("bot.keyboards.push_keyboard", side_effect=keyboard), patch("bot.scheduler.asyncio.sleep", side_effect=stop), patch("bot.scheduler.log.exception"):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(scheduler_loop(Bot(), None))
    db.expire_all()
    if before_send == "none":
        assert len(attempts) == 2 and len(delivered) == 1
        assert log_counts == [0, 0]
        assert db.query(NotificationLog).count() == 1
    else:
        assert attempts == [] and db.query(NotificationLog).count() == 0


def update(state, **fields):
    step, client = state[3:5]
    return client.patch(f"/api/v1/route/steps/{step.id}", json=fields)


def custom(state, value="2030-01-02T12:00:00"):
    response = update(state, reminder_mode="custom", reminder_at=value)
    assert response.status_code == 200, response.text
    return response.json()


def test_custom_wall_clock_roundtrip_is_utc_and_distinct_from_event(state):
    db, user, _, step, client, _ = state
    result = custom(state)
    assert result["reminder_at"] == "2030-01-02T09:00:00Z"
    assert result["activated_at"] == "2030-01-01T09:00:00Z"
    db.expire_all()
    assert step.reminder_at == datetime(2030, 1, 2, 9)
    assert step.reminder_at.tzinfo is None
    assert (step.deadline, step.deadline_time) == (DAY, "14:00")
    fetched = client.get("/api/v1/route").json()["steps"][0]
    assert fetched["reminder_mode"] == "custom"
    assert fetched["reminder_at"] == result["reminder_at"]
    user.tz = "Asia/Tokyo"
    db.commit()
    assert client.get("/api/v1/route").json()["steps"][0]["reminder_at"] == result["reminder_at"]


@pytest.mark.parametrize("value", ["2030-01-02T12:00:00+03:00", "2030-01-02T04:00:00-05:00", "2030-01-02T09:00:00Z"])
def test_aware_input_is_an_instant(state, value):
    assert custom(state, value)["reminder_at"] == "2030-01-02T09:00:00Z"


@pytest.mark.parametrize("fields", [
    {"reminder_mode": None}, {"reminder_mode": "tomorrow"}, {"reminder_mode": ""},
    {"reminder_mode": ["day", "hour"]}, {"reminder_mode": "custom"},
    {"reminder_mode": "custom", "reminder_at": None},
    {"reminder_mode": "custom", "reminder_at": "2020-01-02T12:00:00Z"},
    {"reminder_mode": "day", "reminder_at": "2030-01-02T12:00:00Z"},
    {"reminder_at": "2030-01-02T12:00:00Z"},
    {"deadline": None, "reminder_mode": "day"},
    {"deadline_time": None, "reminder_mode": "hour"},
])
def test_invalid_modes_and_incomplete_settings_are_atomic(state, fields):
    db, user, _, step, _, _ = state
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="day"))
    db.commit()
    assert update(state, **fields).status_code == 422
    db.expire_all()
    assert (step.deadline, step.deadline_time, step.reminder_mode, step.reminder_at, step.reminder_revision) == (DAY, "14:00", "profile", None, 0)
    assert db.query(NotificationLog).count() == 1


@pytest.mark.parametrize("value", ["2030-03-10T02:30:00", "2030-11-03T01:30:00"])
def test_nonexistent_and_ambiguous_wall_times_are_rejected(state, value):
    db, user, _, _, _, _ = state
    user.tz = "America/New_York"
    db.commit()
    response = update(state, reminder_mode="custom", reminder_at=value)
    assert response.status_code == 422
    assert "не существует или неоднозначно" in response.json()["detail"]


@pytest.mark.parametrize("value, expected", [
    ("2030-11-03T01:30:00-04:00", "2030-11-03T05:30:00Z"),
    ("2030-11-03T01:30:00-05:00", "2030-11-03T06:30:00Z"),
])
def test_explicit_offset_disambiguates_fall_back(state, value, expected):
    db, user, _, _, _, _ = state
    user.tz = "America/New_York"
    db.commit()
    assert custom(state, value)["reminder_at"] == expected


@pytest.mark.parametrize("fold, instant", [(0, "2030-11-03T05:30:00Z"), (1, "2030-11-03T06:30:00Z")])
def test_production_clock_keeps_fold_for_explicit_custom_instant(state, fold, instant):
    db, user, _, _, _, _ = state
    user.tz = "America/New_York"
    db.commit()
    custom(state, instant)
    wall = datetime(2030, 11, 3, 1, 30, tzinfo=ZoneInfo(user.tz), fold=fold)
    with patch("bot.scheduler._user_now", return_value=wall):
        assert [p.lead for p in collect_due(db)] == ["custom"]


def test_hour_mode_is_one_real_hour_across_spring_forward(state):
    db, user, _, _, _, _ = state
    user.tz = "America/New_York"
    db.commit()
    assert update(state, deadline="2030-03-10", deadline_time="03:30", reminder_mode="hour").status_code == 200
    # 03:30 EDT = 07:30 UTC; its one-hour lead is 01:30 EST, not
    # nonexistent 02:30 wall time.
    assert [p.lead for p in collect_due(db, datetime(2030, 3, 10, 6, 30, tzinfo=timezone.utc))] == ["hour"]


def test_event_move_requires_explicit_custom_review_but_equivalent_clock_does_not(state):
    db, _, _, step, _, _ = state
    custom(state)
    revision = step.reminder_revision
    assert update(state, deadline_time="14:00:00").status_code == 200
    assert step.reminder_revision == revision
    for fields in ({"deadline": "2030-01-04"}, {"deadline_time": "15:00"},
                   {"deadline_time": "15:00", "reminder_at": "2030-01-02T09:00:00Z"}):
        response = update(state, **fields)
        assert response.status_code == 422, response.text
        db.expire_all()
        assert step.deadline == DAY and step.deadline_time == "14:00"
    response = update(state, deadline_time="15:00", reminder_mode="custom", reminder_at="2030-01-02T09:00:00Z")
    assert response.status_code == 200
    assert step.reminder_at == datetime(2030, 1, 2, 9)
    assert step.deadline_time == "15:00"
    assert step.reminder_revision == revision + 1


@pytest.mark.parametrize("fields", [{"reminder_mode": "profile"}, {"deadline": None}])
def test_explicit_reset_or_date_clear_removes_custom_timer(state, fields):
    custom(state)
    result = update(state, **fields)
    assert result.status_code == 200
    assert result.json()["reminder_mode"] == "profile"
    assert result.json()["reminder_at"] is None
    if "deadline" in fields:
        assert result.json()["deadline_time"] is None


def test_identical_normalized_setting_preserves_dedup_even_after_timer_elapsed(state):
    db, user, _, step, _, _ = state
    result = custom(state)
    revision = step.reminder_revision
    now = datetime(2030, 1, 2, 9, tzinfo=timezone.utc)
    mark_sent(db, collect_due(db, now)[0])
    for fields in ({}, {"reminder_mode": "custom"},
                   {"reminder_mode": "custom", "reminder_at": "2030-01-02T04:00:00-05:00"}):
        with patch.object(api, "utcnow", return_value=datetime(2030, 1, 5)):
            response = update(state, **fields)
        assert response.status_code == 200
        assert response.json()["reminder_at"] == result["reminder_at"]
        assert step.reminder_revision == revision
        assert db.query(NotificationLog).filter_by(user_id=user.id, kind="step").count() == 1
    assert collect_due(db, now) == []


@pytest.mark.parametrize("mode", ["profile", "day", "hour", "custom"])
def test_exclusive_delivery_modes_and_global_switch(state, mode):
    db, user, _, step, _, _ = state
    values = {"reminder_mode": mode}
    if mode == "custom":
        values["reminder_at"] = "2030-01-02T08:00:00Z"
    assert update(state, **values).status_code == 200
    # Profile has all leads; explicit modes replace them, even if profile
    # lead switches are off. Global notifications_on gates every mode.
    if mode != "profile":
        user.notify_day_before = user.notify_hour_before = user.notify_at_deadline = False
        db.commit()
    cases = [(datetime(2030, 1, 2, 8, tzinfo=timezone.utc), "custom"),
             (datetime(2030, 1, 2, 6, tzinfo=timezone.utc), "day"),
             (datetime(2030, 1, 3, 10, tzinfo=timezone.utc), "hour"),
             (datetime(2030, 1, 3, 11, tzinfo=timezone.utc), "now")]
    for now, lead in cases:
        expected = (["day"] if lead == "custom" else [lead]) if mode == "profile" else ([mode] if lead == mode or (mode == "day" and lead == "custom") else [])
        # Custom's retry window also overlaps the later day lead test only
        # if now is after its instant; this matrix uses a preceding day slot.
        assert [p.lead for p in collect_due(db, now)] == expected
        user.notifications_on = False
        db.commit()
        assert collect_due(db, now) == []
        user.notifications_on = True
        db.commit()


def test_legacy_migration_is_idempotent_without_inventing_a_timer():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE route_steps (id INTEGER PRIMARY KEY, title TEXT, status TEXT, deadline DATE, deadline_time TEXT)")
        conn.exec_driver_sql("INSERT INTO route_steps VALUES (1, 'Visit', 'current', '2030-01-03', '14:00')")
    with patch.object(session_module, "engine", engine), patch.object(session_module._settings, "database_url", "sqlite:///:memory:"):
        session_module._migrate_sqlite()
        session_module._migrate_sqlite()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT deadline, deadline_time, reminder_mode, reminder_at, activated_at, reminder_revision FROM route_steps")).one() == ("2030-01-03", "14:00", "profile", None, None, 0)
    engine.dispose()
