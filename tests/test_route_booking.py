"""Explicit event semantics and atomic booking receipts, with isolated HTTP readback."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.orm import Session

from core.db.models import NotificationLog, RouteAssignmentReceipt, RouteStep, utcnow
from test_route_assignments import ROOT, assert_order, body as assignments_body, post as assignments_post, store


@pytest.fixture
def booking(store):
    with store.sessions() as db:
        db.get(RouteStep, store.ids.anchor).kind = "booking"
        db.get(RouteStep, store.ids.tail).kind = "investigation"
        db.commit()
    return store


def payload(**changes):
    return {"request_id": str(uuid4()), "complete": False, "appointment_date": "2035-10-24",
            "target_step_id": None, "expected_target_revision": None,
            "confirm_target_change": False, "target_reminder_action": "keep", **changes}


def post(store, data, step_id=None, **kwargs):
    return store.client.post(f"{ROOT}/steps/{step_id or store.ids.anchor}/booking", json=data, **kwargs)


def step(store, step_id):
    return next(s for s in store.client.get(ROOT).json()["steps"] if s["id"] == step_id)


def test_save_date_readback_then_complete_and_clear_preserves_target(booking):
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0)
    response = post(booking, data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["step"]["status"] == "current"
    assert result["step"]["appointment_date"] == "2035-10-24"
    assert result["step"]["deadline"] is None
    assert result["step"]["booking_target_step_id"] == booking.ids.tail
    target = step(booking, booking.ids.tail)
    assert (target["deadline"], target["reminder_revision"]) == ("2035-10-24", 1)
    assert booking.client.get(ROOT).json() == result["route"]
    # Null date is local information only, not a command to erase target dates.
    result = post(booking, payload(target_step_id=booking.ids.tail, appointment_date=None,
                                    complete=True)).json()
    assert result["step"]["status"] == "done"
    assert result["step"]["appointment_date"] is None
    assert result["next_step"]["id"] == booking.ids.tail
    assert step(booking, booking.ids.tail)["deadline"] == "2035-10-24"
    assert_order(result["route"])


def test_booking_assignment_keeps_obtained_date_separate_and_replays(store):
    data = assignments_body({"title": "Записаться на контроль", "kind": "booking",
                             "appointment_date": "2035-10-24"})
    result = assignments_post(store, data)
    assert result.status_code == 200, result.text
    added_id = result.json()["added_step_ids"][0]
    added = step(store, added_id)
    assert (added["kind"], added["appointment_date"], added["deadline"], added["deadline_time"],
            added["booking_target_step_id"]) == ("booking", "2035-10-24", None, None, None)
    assert assignments_post(store, data).json() == result.json()


def test_step_creation_rejects_silently_ignored_body_placement(store):
    response = store.client.post(f"{ROOT}/steps", json={
        "title": "Preparation", "kind": "task", "before_step_id": store.ids.anchor,
    })
    assert response.status_code == 422


def test_completed_unknown_can_be_explicitly_clarified_without_rewriting_historical_fact(store):
    with store.sessions() as db:
        historical = db.get(RouteStep, store.ids.history)
        historical.kind = "unknown"
        db.commit()
    before = step(store, store.ids.history)
    path = f"{ROOT}/steps/{store.ids.history}"
    assert store.client.patch(path, json={"kind": "visit", "deadline": None}).status_code == 409
    result = store.client.patch(path, json={"kind": "visit"})
    assert result.status_code == 200, result.text
    after = result.json()
    for field in set(before) - {"kind", "reminder_revision"}:
        assert after[field] == before[field]
    assert after["kind"] == "visit"
    assert store.client.patch(path, json={"kind": "task"}).status_code == 409
    added = assignments_post(store, assignments_body({"title": "Фактическое назначение", "kind": "investigation"},
                                                      complete=False), anchor=store.ids.history)
    assert added.status_code == 200, added.text
    assert step(store, store.ids.history)["completed_at"] == before["completed_at"]


def test_editorial_doctor_flow_http_booking_preparation_visit_and_actual_assignments(store):
    started = store.client.post(f"{ROOT}/start", json={"situation_key": "doctor"})
    assert started.status_code == 200, started.text
    data = started.json()
    book, prep, visit = data["steps"]
    assert [s["kind"] for s in data["steps"]] == ["booking", "task", "visit"]
    assert book["booking_target_step_id"] == visit["id"]
    result = post(store, payload(complete=True, target_step_id=visit["id"], expected_target_revision=0), book["id"])
    assert result.status_code == 200, result.text
    assert result.json()["next_step"]["id"] == prep["id"]
    readback = store.client.get(ROOT).json()
    assert readback == result.json()["route"]
    assert readback["steps"][1]["deadline"] is None
    assert readback["steps"][2]["deadline"] == "2035-10-24"
    # Preparation can be inserted before the target through the actual query contract.
    inserted = store.client.post(f"{ROOT}/steps?before_step_id={visit['id']}",
                                 json={"title": "Получить имеющийся результат", "kind": "task"})
    assert inserted.status_code == 200, inserted.text
    assert [s["kind"] for s in inserted.json()["steps"]] == ["booking", "task", "task", "visit"]
    for current_id in [prep["id"], inserted.json()["steps"][2]["id"]]:
        store.client.post(f"{ROOT}/steps/{current_id}/complete").raise_for_status()
    actual = assignments_post(store, assignments_body(
        {"title": "Одинаково", "kind": "investigation"}, {"title": "Одинаково", "kind": "visit"},
    ), anchor=visit["id"])
    assert actual.status_code == 200, actual.text
    assert_order(actual.json()["route"])
    assert [s["kind"] for s in actual.json()["route"]["steps"]][-2:] == ["investigation", "visit"]
    assert store.client.get(ROOT).json() == actual.json()["route"]


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("appointment", [None, "2035-10-24"])
def test_unlinked_date_or_unknown_date_can_save_and_complete(booking, complete, appointment):
    original_target = step(booking, booking.ids.tail)
    response = post(booking, payload(complete=complete, appointment_date=appointment))
    assert response.status_code == 200, response.text
    assert response.json()["step"]["status"] == ("done" if complete else "current")
    after = step(booking, booking.ids.tail)
    assert after["deadline"] == original_target["deadline"]
    assert after["reminder_revision"] == 0


def test_pending_save_allowed_completion_forbidden_done_immutable(booking):
    added = booking.client.post(f"{ROOT}/steps?before_step_id={booking.ids.anchor}",
                                json={"title": "Before", "kind": "task"})
    assert added.status_code == 200
    assert post(booking, payload()).status_code == 200
    before = booking.client.get(ROOT).json()
    assert post(booking, payload(complete=True)).status_code == 409
    assert booking.client.get(ROOT).json() == before
    current = next(s for s in before["steps"] if s["status"] == "current")
    booking.client.post(f"{ROOT}/steps/{current['id']}/complete").raise_for_status()
    post(booking, payload(complete=True)).raise_for_status()
    before = booking.client.get(ROOT).json()
    assert post(booking, payload()).status_code == 409
    assert booking.client.get(ROOT).json() == before


@pytest.mark.parametrize("kind", ["unknown", "visit", "investigation", "task", "process"])
def test_only_booking_accepts_booking_operation(booking, kind):
    with booking.sessions() as db:
        db.get(RouteStep, booking.ids.anchor).kind = kind
        db.commit()
    assert post(booking, payload()).status_code == 409


@pytest.mark.parametrize("kind", ["unknown", "booking", "investigation", "task", "process"])
def test_new_assignments_require_explicit_visit(store, kind):
    with store.sessions() as db:
        db.get(RouteStep, store.ids.anchor).kind = kind
        db.commit()
    before = store.client.get(ROOT).json()
    assert assignments_post(store, assignments_body({"title": "Doctor"})).status_code == 409
    assert store.client.get(ROOT).json() == before


@pytest.mark.parametrize("target, expected", [("foreign", 404), ("inactive", 404),
                                              ("history", 422), ("anchor", 422)])
def test_target_security_and_forward_only(booking, target, expected):
    before = booking.client.get(ROOT).json()
    result = post(booking, payload(target_step_id=getattr(booking.ids, target), expected_target_revision=0))
    assert result.status_code == expected, result.text
    assert booking.client.get(ROOT).json() == before


@pytest.mark.parametrize("target_kind, target_status", [("unknown", "pending"),
                                                        ("booking", "pending"), ("visit", "done")])
def test_target_requires_unfinished_known_event(booking, target_kind, target_status):
    with booking.sessions() as db:
        row = db.get(RouteStep, booking.ids.tail)
        row.kind, row.status = target_kind, target_status
        db.commit()
    before = booking.client.get(ROOT).json()
    assert post(booking, payload(target_step_id=booking.ids.tail, expected_target_revision=0)).status_code == 422
    assert booking.client.get(ROOT).json() == before


@pytest.mark.parametrize("revision, expected", [(None, 422), (2, 409)])
def test_required_revision_and_stale_revision(booking, revision, expected):
    before = booking.client.get(ROOT).json()
    assert post(booking, payload(target_step_id=booking.ids.tail,
                                  expected_target_revision=revision)).status_code == expected
    assert booking.client.get(ROOT).json() == before


def test_confirmation_preserves_event_time_scoped_dedup_and_noop(booking):
    with booking.sessions() as db:
        target = db.get(RouteStep, booking.ids.tail)
        target.deadline, target.deadline_time = date(2035, 10, 23), "08:00"
        db.add_all([NotificationLog(user_id=booking.ids.user, kind="step", ref_id=target.id, lead="hour"),
                    NotificationLog(user_id=booking.ids.other, kind="step", ref_id=target.id, lead="hour")])
        db.commit()
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0)
    assert post(booking, data).status_code == 409
    result = post(booking, {**data, "confirm_target_change": True})
    assert result.status_code == 200, result.text
    target = step(booking, booking.ids.tail)
    assert (target["deadline"], target["deadline_time"], target["reminder_revision"]) == ("2035-10-24", "08:00", 1)
    with booking.sessions() as db:
        assert [s.user_id for s in db.query(NotificationLog)] == [booking.ids.other]
        db.add(NotificationLog(user_id=booking.ids.user, kind="step", ref_id=booking.ids.tail, lead="hour"))
        db.commit()
    # A fresh UUID with identical schedule does not invalidate dedup.
    result = post(booking, payload(target_step_id=booking.ids.tail, expected_target_revision=1,
                                    confirm_target_change=True))
    assert result.status_code == 200
    assert step(booking, booking.ids.tail)["reminder_revision"] == 1
    with booking.sessions() as db:
        assert db.query(NotificationLog).count() == 2


@pytest.mark.parametrize("action, past", [("keep", False), ("keep", True), ("profile", True)])
def test_custom_timer_requires_confirmation_and_future_or_explicit_profile(booking, action, past):
    moment = utcnow() + timedelta(days=-1 if past else 10)
    with booking.sessions() as db:
        target = db.get(RouteStep, booking.ids.tail)
        target.deadline, target.reminder_mode, target.reminder_at = date(2035, 1, 1), "custom", moment
        db.commit()
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0, target_reminder_action=action)
    assert post(booking, data).status_code == 409
    result = post(booking, {**data, "confirm_target_change": True})
    assert result.status_code == (422 if action == "keep" and past else 200), result.text
    target = step(booking, booking.ids.tail)
    if result.status_code == 200:
        assert target["reminder_mode"] == ("custom" if action == "keep" else "profile")
        assert (target["reminder_at"] is not None) == (action == "keep")


def test_hour_requires_time_and_profile_can_reset_invalid_legacy_override(booking):
    with booking.sessions() as db:
        target = db.get(RouteStep, booking.ids.tail)
        target.reminder_mode = "hour"
        db.commit()
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0, confirm_target_change=True)
    assert post(booking, data).status_code == 422
    assert post(booking, {**data, "target_reminder_action": "profile"}).status_code == 200


def test_receipt_replay_changed_content_shared_uuid_and_deleted_route(booking):
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0, complete=True)
    original = post(booking, data)
    assert original.status_code == 200
    assert post(booking, data).json() == original.json()
    assert post(booking, {**data, "appointment_date": None}).status_code == 409
    assert assignments_post(booking, assignments_body(request_id=data["request_id"])).status_code == 409
    booking.client.delete(ROOT).raise_for_status()
    assert post(booking, data).json() == original.json()


def test_old_assignment_fingerprint_and_snapshot_replay_before_role_check(store):
    data = assignments_body({"title": "Old", "deadline": None, "deadline_time": None, "place": ""})
    legacy_payload = {"step_id": store.ids.anchor, "complete": True, "assignments": data["assignments"]}
    fingerprint = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode()).hexdigest()
    route = store.client.get(ROOT).json()
    snapshot = {"step": route["steps"][1], "route": route, "next_step": route["steps"][2], "added_step_ids": []}
    # Stored S4 snapshot has no semantic fields and remains readable.
    for row in [snapshot["step"], snapshot["next_step"], *snapshot["route"]["steps"]]:
        for name in ("kind", "template_key", "appointment_date", "booking_target_step_id", "reminder_revision"):
            row.pop(name, None)
    with store.sessions() as db:
        db.get(RouteStep, store.ids.anchor).kind = "unknown"
        db.add(RouteAssignmentReceipt(user_id=store.ids.user, request_id=data["request_id"],
                                      fingerprint=fingerprint, response=snapshot))
        db.commit()
    result = assignments_post(store, data)
    assert result.status_code == 200, result.text
    assert result.json()["step"]["kind"] == "unknown"
    assert post(store, payload(request_id=data["request_id"])).status_code == 409


def test_booking_receipt_commit_failure_rolls_back_everything(booking, monkeypatch):
    before = booking.client.get(ROOT).json()
    original = Session.commit

    def fail(db):
        if any(isinstance(row, RouteAssignmentReceipt) for row in db.new):
            raise RuntimeError("synthetic receipt failure")
        return original(db)

    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0, complete=True)
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        with TestClient(booking.app, raise_server_exceptions=False) as client:
            assert client.post(f"{ROOT}/steps/{booking.ids.anchor}/booking", json=data).status_code == 500
    assert booking.client.get(ROOT).json() == before
    assert post(booking, data).status_code == 200


@pytest.mark.parametrize("same_uuid", [True, False])
def test_booking_concurrency_uses_existing_route_lock(booking, same_uuid):
    data = payload(target_step_id=booking.ids.tail, expected_target_revision=0, complete=True)
    requests = [data, data if same_uuid else {**data, "request_id": str(uuid4())}]
    booking.race.barrier = Barrier(2)

    def send(data):
        with TestClient(booking.app) as client:
            return client.post(f"{ROOT}/steps/{booking.ids.anchor}/booking", json=data, headers={"X-Race": "1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, requests))
    assert len(booking.race.connections) == 2
    assert sorted(r.status_code for r in responses) == ([200, 200] if same_uuid else [200, 409])
    if same_uuid:
        assert responses[0].json() == responses[1].json()
    assert_order(booking.client.get(ROOT).json())


def test_explicit_manual_link_patch_before_insertion_and_target_deletion(booking):
    before = booking.client.get(ROOT).json()
    response = booking.client.post(f"{ROOT}/steps?before_step_id={booking.ids.tail}", json={
        "title": "Same", "kind": "booking", "appointment_date": "2035-10-24",
        "booking_target_step_id": booking.ids.tail,
    })
    assert response.status_code == 200, response.text
    added = next(s for s in response.json()["steps"] if s["id"] not in {s["id"] for s in before["steps"]})
    assert added["kind"] == "booking"
    assert added["appointment_date"] == "2035-10-24"
    assert step(booking, booking.ids.tail)["deadline"] is None
    assert [s["id"] for s in response.json()["steps"]][-2:] == [added["id"], booking.ids.tail]
    path = f"{ROOT}/steps/{booking.ids.anchor}"
    result = booking.client.patch(path, json={"booking_target_step_id": booking.ids.tail})
    assert result.status_code == 200
    assert result.json()["reminder_revision"] == 1
    assert booking.client.patch(path, json={"kind": "task"}).status_code == 422
    assert booking.client.patch(path, json={"kind": None}).status_code == 422
    result = booking.client.patch(path, json={"kind": "task", "booking_target_step_id": None})
    assert result.status_code == 200
    assert result.json()["reminder_revision"] == 2
    result = booking.client.delete(f"{ROOT}/steps/{booking.ids.tail}")
    assert result.status_code == 200
    assert step(booking, added["id"])["booking_target_step_id"] is None
    assert step(booking, added["id"])["reminder_revision"] == 1


def test_invalid_insert_rolls_back_positions_and_metadata(booking):
    before = booking.client.get(ROOT).json()
    for query, data, status in [
        (f"before_step_id={booking.ids.tail}&after_step_id={booking.ids.anchor}", {"title": "A"}, 422),
        (f"before_step_id={booking.ids.history}", {"title": "A"}, 409),
        (f"before_step_id={booking.ids.tail}", {"title": "A", "kind": "booking", "booking_target_step_id": booking.ids.foreign}, 404),
        (f"after_step_id={booking.ids.tail}", {"title": "A", "kind": "booking", "booking_target_step_id": booking.ids.tail}, 422),
        ("", {"title": "A", "kind": "task", "appointment_date": "2035-10-24"}, 422),
        ("", {"title": "A", "kind": "booking", "deadline": "2035-10-24", "deadline_time": "08:00"}, 422),
    ]:
        result = booking.client.post(f"{ROOT}/steps?{query}", json=data)
        assert result.status_code == status, result.text
        assert booking.client.get(ROOT).json() == before


def test_old_booking_clock_survives_kind_patch_and_explicit_edit(booking):
    with booking.sessions() as db:
        row = db.get(RouteStep, booking.ids.anchor)
        row.kind, row.deadline, row.deadline_time = "unknown", date(2035, 1, 1), "8:00"
        db.commit()
    path = f"{ROOT}/steps/{booking.ids.anchor}"
    response = booking.client.patch(path, json={"kind": "booking"})
    assert response.status_code == 200
    assert response.json()["deadline_time"] == "8:00"
    assert booking.client.patch(path, json={"deadline_time": "09:00"}).status_code == 422
    assert booking.client.patch(path, json={"deadline_time": "08:00"}).status_code == 200
    assert booking.client.patch(path, json={"deadline_time": None}).status_code == 200


def test_http_preview_and_custom_route_explicit_keys_placement_readback(store):
    from server.api.v1 import profile

    store.app.include_router(profile.router, prefix="/api/v1")
    response = store.client.get("/api/v1/catalog/doctor/steps")
    assert response.status_code == 200
    preview = response.json()
    assert all({"position", "title", "has_checklist", "description", "key", "kind", "booking_target_key"} <= s.keys()
               for s in preview)
    visit = next(s for s in preview if s["kind"] == "visit")
    result = store.client.post(f"{ROOT}/start", json={
        "situation_key": "doctor", "custom_steps": [
            {"title": "Same", "kind": "booking", "client_key": "own-book",
             "booking_target_key": "own-target", "before_position": visit["position"],
             "appointment_date": "2035-10-24"},
            {"title": "Same", "kind": "investigation", "client_key": "own-target",
             "before_position": visit["position"]},
        ],
    })
    assert result.status_code == 200, result.text
    route = result.json()
    custom = [s for s in route["steps"] if s["source"] == "user"]
    assert [s["kind"] for s in custom] == ["booking", "investigation"]
    assert custom[0]["booking_target_step_id"] == custom[1]["id"]
    assert custom[0]["appointment_date"] == "2035-10-24"
    assert custom[1]["deadline"] is None
    assert all(s["template_key"] is None for s in custom)
    target = next(s for s in route["steps"] if s["template_key"] == visit["key"])
    assert custom[0]["position"] < custom[1]["position"] < target["position"]
    assert store.client.get(ROOT).json() == route


def test_http_excluded_template_target_stays_unlinked(store):
    from core.db.seed import load_scenarios

    specs = load_scenarios()["doctor"]["steps"]
    spec = next(s for s in specs if s["kind"] == "booking")
    excluded = next(i for i, s in enumerate(specs, 1) if s["key"] == spec["booking_target_key"])
    result = store.client.post(f"{ROOT}/start", json={"situation_key": "doctor", "exclude_positions": [excluded]})
    assert result.status_code == 200, result.text
    booking = next(s for s in result.json()["steps"] if s["template_key"] == spec["key"])
    assert booking["booking_target_step_id"] is None
    assert store.client.get(ROOT).json() == result.json()


@pytest.mark.parametrize("custom", [
    [{"title": "Bad", "kind": "booking", "booking_target_key": "missing"}],
    [{"title": "Bad", "kind": "task", "before_position": 9999}],
    [{"title": "A", "client_key": "same"}, {"title": "B", "client_key": "same"}],
    [{"title": "A", "kind": "visit", "client_key": "before"},
     {"title": "B", "kind": "booking", "booking_target_key": "before"}],
])
def test_invalid_route_start_rolls_back_active_route_and_receipts(store, custom):
    assignments_post(store, assignments_body()).raise_for_status()
    before = store.client.get(ROOT).json()
    result = store.client.post(f"{ROOT}/start", json={"situation_key": "custom", "custom_steps": custom})
    assert result.status_code == 422, result.text
    assert store.client.get(ROOT).json() == before
    with store.sessions() as db:
        assert db.query(RouteAssignmentReceipt).count() == 1


@pytest.mark.parametrize("changes", [{"complete": "true"}, {"request_id": "bad"},
                                      {"target_reminder_action": "silent"}, {"target_step_id": -1},
                                      {"target_step_id": True},
                                      {"expected_target_revision": -1}, {"confirm_target_change": "true"},
                                      {"appointment_date": "bad"}, {"extra": "ignored?"}])
def test_booking_invalid_body_never_mutates(booking, changes):
    before = booking.client.get(ROOT).json()
    assert post(booking, payload(**changes)).status_code == 422
    assert booking.client.get(ROOT).json() == before


def test_missing_consent_or_auth_blocks_booking_before_mutation(booking):
    from server.api.v1.common import current_user, db_session

    app = FastAPI()
    from server.api.v1 import route as api
    app.include_router(api.router, prefix="/api/v1")

    def session():
        with booking.sessions() as db:
            yield db

    app.dependency_overrides[db_session] = session
    with TestClient(app) as client:
        assert client.post(f"{ROOT}/steps/{booking.ids.anchor}/booking", json=payload()).status_code == 401
        app.dependency_overrides[current_user] = lambda: SimpleNamespace(consent_at=None)
        assert client.post(f"{ROOT}/steps/{booking.ids.anchor}/booking", json=payload()).status_code == 403


def test_migration_adds_unknown_fields_preserves_history_and_receipts(store, monkeypatch):
    from core.db import session as database

    assignments_post(store, assignments_body({"title": "Saved"})).raise_for_status()
    fields = {"kind", "template_key", "booking_target_step_id", "appointment_date"}
    with store.engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN contains_demo_data"))
        legacy = Table("route_steps_legacy", MetaData(), *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable,
                   server_default=c.server_default)
            for c in RouteStep.__table__.columns if c.name not in fields
        ])
        legacy.create(conn)
        columns = ", ".join(c.name for c in legacy.columns)
        conn.execute(text(f"INSERT INTO route_steps_legacy ({columns}) SELECT {columns} FROM route_steps"))
        conn.execute(text("DROP TABLE route_steps"))
        conn.execute(text("ALTER TABLE route_steps_legacy RENAME TO route_steps"))
        before = conn.execute(text("SELECT * FROM route_steps ORDER BY id")).mappings().all()
        receipts = conn.execute(text("SELECT * FROM route_assignment_receipts")).mappings().all()
    monkeypatch.setattr(database, "engine", store.engine)
    monkeypatch.setattr(database, "_settings", SimpleNamespace(database_url=str(store.engine.url)))
    database.init_db()
    database.init_db()
    with store.engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM route_steps ORDER BY id")).mappings().all()
        assert [{k: v for k, v in row.items() if k not in fields} for row in rows] == before
        assert all(row["kind"] == "unknown" for row in rows)
        assert all(row["template_key"] is row["booking_target_step_id"] is row["appointment_date"] is None for row in rows)
        assert conn.execute(text("SELECT * FROM route_assignment_receipts")).mappings().all() == receipts
        assert set(conn.execute(text("SELECT contains_demo_data FROM users")).scalars()) == {0}
