"""Isolated HTTP and real-connection regressions for atomic doctor assignments."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import Base, Route, RouteAssignmentReceipt, RouteStep, User
from core.schemas import StepAddIn
from core.services import complete_route_step
from server.api.v1 import route as api


HISTORY = datetime(2026, 1, 2, 12)
ACTIVATED = datetime(2026, 1, 3, 12)
ROOT = "/api/v1/route"


@pytest.fixture
def store(tmp_path):
    # File SQLite / independent pooled connections, never the configured DB.
    engine = create_engine(f"sqlite:///{tmp_path / 'assignments.sqlite'}",
                           connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def configure(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        user = User(max_user_id=880001, consent_at=HISTORY)
        other = User(max_user_id=880002, consent_at=HISTORY)
        db.add_all([user, other])
        db.flush()
        route = Route(user_id=user.id, situation_key="custom", title="Synthetic")
        foreign = Route(user_id=other.id, situation_key="custom", title="Other")
        inactive = Route(user_id=user.id, situation_key="custom", title="Old", active=False)
        db.add_all([route, foreign, inactive])
        db.flush()
        history = RouteStep(route_id=route.id, position=1, title="History", status="done",
                            completed_at=HISTORY, note="historical note")
        anchor = RouteStep(route_id=route.id, position=2, title="Anchor", status="current",
                           activated_at=ACTIVATED)
        tail = RouteStep(route_id=route.id, position=3, title="Tail", status="pending")
        foreign_step = RouteStep(route_id=foreign.id, position=1, title="Foreign", status="current")
        inactive_step = RouteStep(route_id=inactive.id, position=1, title="Old", status="current")
        db.add_all([history, anchor, tail, foreign_step, inactive_step])
        db.commit()
        ids = SimpleNamespace(user=user.id, other=other.id, route=route.id, anchor=anchor.id,
                              history=history.id, tail=tail.id, foreign=foreign_step.id,
                              inactive=inactive_step.id)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    race = SimpleNamespace(barrier=None, connections=set(), guard=Lock())

    def db_dep():
        with sessions() as db:
            yield db

    def user_dep(request: Request, db: Session = Depends(api.db_session)):
        user = db.get(User, int(request.headers.get("X-User", ids.user)))
        if request.headers.get("X-Race"):
            # Deliberately load stale route/step objects before competing writes.
            route = db.get(Route, ids.route)
            list(route.steps)
            with race.guard:
                race.connections.add(id(db.connection().connection.driver_connection))
            race.barrier.wait(timeout=10)
        return user

    app.dependency_overrides[api.db_session] = db_dep
    app.dependency_overrides[api.consented_user] = user_dep
    with TestClient(app) as client:
        yield SimpleNamespace(engine=engine, sessions=sessions, app=app, client=client,
                              ids=ids, race=race)
    engine.dispose()


def body(*assignments, complete=True, request_id=None):
    return {"request_id": str(request_id or uuid4()), "complete": complete,
            "assignments": list(assignments)}


def post(store, payload, anchor=None, **kwargs):
    return store.client.post(f"{ROOT}/steps/{anchor or store.ids.anchor}/assignments",
                             json=payload, **kwargs)


def assert_order(route):
    steps = route["steps"]
    assert [s["position"] for s in steps] == list(range(1, len(steps) + 1))
    assert len({s["id"] for s in steps}) == len(steps)
    unfinished = [s for s in steps if s["status"] != "done"]
    assert [s["status"] for s in unfinished] == (["current"] + ["pending"] * (len(unfinished) - 1)
                                               if unfinished else [])


def test_http_batch_readback_duplicate_titles_time_and_activation(store):
    response = post(store, body(
        {"title": " Same ", "deadline": "2026-10-20", "deadline_time": "8:05:00", "place": " Lab "},
        {"title": "Same", "deadline": None, "deadline_time": None},
    ))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["step"]["id"] == store.ids.anchor
    assert result["step"]["status"] == "done"
    assert result["step"]["completed_at"] is not None
    assert result["step"]["activated_at"] == ACTIVATED.isoformat() + "Z"
    added = result["route"]["steps"][2:4]
    assert result["added_step_ids"] == [s["id"] for s in added]
    assert len(set(result["added_step_ids"])) == 2
    assert [s["title"] for s in added] == ["Same", "Same"]
    assert [s["source"] for s in added] == ["doctor", "doctor"]
    assert [s["deadline_time"] for s in added] == ["08:05", None]
    assert added[0]["place"] == "Lab"
    assert added[0]["activated_at"] is not None
    assert added[1]["activated_at"] is None
    assert result["route"]["steps"][-1]["activated_at"] is None
    assert result["next_step"] == added[0]
    assert_order(result["route"])
    assert store.client.get(ROOT).json() == result["route"]
    with store.sessions() as db:
        history = db.get(RouteStep, store.ids.history)
        assert (history.status, history.completed_at, history.note) == ("done", HISTORY, "historical note")
        assert db.query(RouteAssignmentReceipt).count() == 1


def test_empty_completion_and_assign_after_fully_done(store):
    response = post(store, body())
    assert response.status_code == 200
    assert response.json()["added_step_ids"] == []
    assert response.json()["next_step"]["id"] == store.ids.tail
    store.client.post(f"{ROOT}/steps/{store.ids.tail}/complete").raise_for_status()
    before = store.client.get(ROOT).json()
    assert all(s["status"] == "done" for s in before["steps"])
    result = post(store, body({"title": "Late assignment"}, complete=False)).json()
    assert_order(result["route"])
    assert result["next_step"]["id"] == result["added_step_ids"][0]
    assert result["step"] == before["steps"][1]
    assert result["route"]["steps"][-1] == {**before["steps"][-1], "position": 4}
    assert store.client.get(ROOT).json() == result["route"]


def test_empty_completion_of_last_step_has_no_next(store):
    post(store, body()).raise_for_status()
    result = post(store, body(), anchor=store.ids.tail).json()
    assert result["next_step"] is None
    assert result["added_step_ids"] == []
    assert result["route"]["done_steps"] == result["route"]["total_steps"] == 3
    assert store.client.get(ROOT).json() == result["route"]


@pytest.mark.parametrize("invalid", [
    {"title": " "}, {"title": "x" * 201}, {"title": "OK", "place": "x" * 201},
    {"title": "OK", "deadline": "bad"}, {"title": "OK", "deadline_time": "08:00"},
    {"title": "OK", "deadline": "2026-10-20", "deadline_time": "24:00"},
    {"title": "OK", "deadline": "2026-10-20", "deadline_time": "08:00:01"},
    {"title": "OK", "source": "user"}, {"title": "OK", "place": None},
])
def test_invalid_later_assignment_rolls_back_entire_batch(store, invalid):
    before = store.client.get(ROOT).json()
    response = post(store, body({"title": "Valid first"}, invalid))
    assert response.status_code == 422
    assert store.client.get(ROOT).json() == before
    with store.sessions() as db:
        assert db.query(RouteAssignmentReceipt).count() == 0


@pytest.mark.parametrize("change", [
    {"complete": False, "assignments": []}, {"complete": "true"}, {"request_id": "bad"},
])
def test_invalid_envelope(store, change):
    payload = body({"title": "A"}) | change
    assert post(store, payload).status_code == 422
    assert store.client.get(ROOT).json()["done_steps"] == 1


@pytest.mark.parametrize("target, complete, expected", [
    ("foreign", True, 404), ("inactive", True, 404), ("tail", True, 409),
    ("history", True, 409), ("anchor", False, 409), ("tail", False, 409),
])
def test_ownership_active_and_state_conflicts(store, target, complete, expected):
    before = store.client.get(ROOT).json()
    response = post(store, body({"title": "A"}, complete=complete), anchor=getattr(store.ids, target))
    assert response.status_code == expected
    assert store.client.get(ROOT).json() == before


def test_no_active_route_and_cross_user_request_scope(store):
    payload = body({"title": "A"})
    first = post(store, payload).json()
    other = post(store, payload, anchor=store.ids.foreign, headers={"X-User": str(store.ids.other)})
    assert other.status_code == 200
    assert set(first["added_step_ids"]).isdisjoint(other.json()["added_step_ids"])
    store.client.delete(ROOT).raise_for_status()
    assert post(store, body({"title": "B"})).status_code == 404


def test_retry_lost_response_after_uncomplete_and_route_replacement(store):
    payload = body({"title": "A", "deadline": "2026-10-20", "deadline_time": "8:00"})
    original = post(store, payload).json()
    # Simulate losing the response: a fresh request must return its saved receipt.
    assert post(store, payload).json() == original
    equivalent = {**payload, "assignments": [{**payload["assignments"][0], "deadline_time": "08:00:00", "place": ""}]}
    assert post(store, equivalent).json() == original
    store.client.post(f"{ROOT}/steps/{store.ids.anchor}/uncomplete").raise_for_status()
    changed = store.client.get(ROOT).json()
    assert post(store, payload).json() == original
    assert store.client.get(ROOT).json() == changed
    store.client.delete(ROOT).raise_for_status()
    store.client.post(f"{ROOT}/start", json={"situation_key": "custom", "custom_steps": [{"title": "New"}]}).raise_for_status()
    changed = store.client.get(ROOT).json()
    assert post(store, payload).json() == original
    assert store.client.get(ROOT).json() == changed


@pytest.mark.parametrize("change", ["title", "anchor", "complete", "order", "date", "place"])
def test_changed_payload_or_anchor_conflicts(store, change):
    payload = body({"title": "A"}, {"title": "B"})
    post(store, payload).raise_for_status()
    before = store.client.get(ROOT).json()
    anchor = None
    if change == "anchor":
        anchor = store.ids.history
    elif change == "complete":
        payload["complete"] = False
    elif change == "order":
        payload["assignments"].reverse()
    else:
        payload["assignments"][0][{"title": "title", "date": "deadline", "place": "place"}[change]] = (
            "2026-10-20" if change == "date" else "Changed")
    assert post(store, payload, anchor=anchor).status_code == 409
    assert store.client.get(ROOT).json() == before


def test_receipt_failure_rolls_back_completion_and_insertion(store, monkeypatch):
    before = store.client.get(ROOT).json()
    original = Session.commit

    def fail_receipt_commit(db):
        if any(isinstance(row, RouteAssignmentReceipt) for row in db.new):
            raise RuntimeError("simulated storage failure")
        original(db)

    payload = body({"title": "A"})
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_receipt_commit)
        with TestClient(store.app, raise_server_exceptions=False) as client:
            response = client.post(f"{ROOT}/steps/{store.ids.anchor}/assignments", json=payload)
        assert response.status_code == 500
    assert store.client.get(ROOT).json() == before
    assert post(store, payload).status_code == 200


@pytest.mark.parametrize("same_request, complete", [(True, True), (False, True), (False, False)])
def test_real_concurrent_connections(store, same_request, complete):
    if not complete:
        post(store, body()).raise_for_status()
    payloads = [body({"title": "A1"}, {"title": "A2"}, complete=complete)]
    payloads.append(payloads[0] if same_request else body({"title": "B1"}, {"title": "B2"}, complete=complete))
    store.race.barrier = Barrier(2)

    def send(payload):
        with TestClient(store.app) as client:
            return client.post(f"{ROOT}/steps/{store.ids.anchor}/assignments", json=payload, headers={"X-Race": "1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, payloads))
    assert len(store.race.connections) == 2
    statuses = sorted(r.status_code for r in responses)
    assert statuses == ([200, 409] if complete and not same_request else [200, 200]), [r.text for r in responses]
    if same_request:
        assert responses[0].json() == responses[1].json()
    route = store.client.get(ROOT).json()
    assert_order(route)
    successful = [r.json() for r in responses if r.status_code == 200]
    expected_ids = {i for result in successful for i in result["added_step_ids"]}
    assert {s["id"] for s in route["steps"] if s["source"] == "doctor"} == expected_ids
    titles = [s["title"] for s in route["steps"]]
    for a, b in [("A1", "A2"), ("B1", "B2")]:
        if a in titles:
            assert titles.index(b) == titles.index(a) + 1


@pytest.mark.parametrize("action", ["single_add", "complete", "delete_step", "uncomplete", "delete_route", "start", "patch"])
def test_assignments_serialize_with_legacy_route_writers(store, action):
    if action == "uncomplete":
        post(store, body()).raise_for_status()
    payload = body({"title": "Batch A"}, {"title": "Batch B"}, complete=action != "uncomplete")
    store.race.barrier = Barrier(2)

    def send(which):
        with TestClient(store.app) as client:
            headers = {"X-Race": "1"}
            path = f"{ROOT}/steps/{store.ids.anchor}"
            if which == "batch":
                return client.post(f"{path}/assignments", json=payload, headers=headers)
            if action == "single_add":
                return client.post(f"{ROOT}/steps?after_step_id={store.ids.anchor}",
                                   json={"title": "Legacy"}, headers=headers)
            if action in ("complete", "uncomplete"):
                return client.post(f"{path}/{action}", headers=headers)
            if action == "delete_step":
                return client.delete(path, headers=headers)
            if action == "delete_route":
                return client.delete(ROOT, headers=headers)
            if action == "start":
                return client.post(f"{ROOT}/start", json={"situation_key": "custom",
                                   "custom_steps": [{"title": "Replacement"}]}, headers=headers)
            return client.patch(path, json={"deadline": "2026-10-20"}, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        batch, legacy = list(pool.map(send, ["batch", "legacy"]))
    assert len(store.race.connections) == 2
    statuses = (batch.status_code, legacy.status_code)
    allowed = {
        "single_add": {(200, 200)}, "complete": {(200, 409), (409, 200)},
        "delete_step": {(200, 409), (404, 200)}, "uncomplete": {(200, 200), (409, 200)},
        "delete_route": {(200, 200), (404, 200)}, "start": {(200, 200), (404, 200)},
        "patch": {(200, 200), (200, 409)},
    }
    assert statuses in allowed[action], (batch.text, legacy.text)
    route = store.client.get(ROOT).json()
    if route:
        assert_order(route)
    if batch.status_code == 200:
        # Even route deletion/replacement cannot invalidate a committed receipt.
        assert post(store, payload).json() == batch.json()


def test_composed_completion_preserves_staged_schedule(store):
    with store.sessions() as db:
        step = db.get(RouteStep, store.ids.anchor)
        step.deadline_time = "08:00"
        step.deadline = date(2026, 10, 20)
        complete_route_step(db, store.ids.user, step.id, commit=False)
        db.commit()
        db.refresh(step)
        assert (step.status, step.deadline.isoformat(), step.deadline_time) == ("done", "2026-10-20", "08:00")


def test_legacy_insert_uses_fresh_ordered_dtos_then_delete_and_uncomplete(store):
    with store.sessions() as db:
        user = db.get(User, store.ids.user)
        route = db.get(Route, store.ids.route)
        list(route.steps)  # Existing relationship and step identity-map objects.
        result = api.add_step(StepAddIn(title="Before current"), after_step_id=store.ids.history,
                              user=user, db=db).model_dump(mode="json")
        assert [s["title"] for s in result["steps"]] == ["History", "Before current", "Anchor", "Tail"]
        assert_order(result)
        assert result["steps"][1]["activated_at"] is not None
        assert result["steps"][2]["activated_at"] == ACTIVATED.isoformat() + "Z"
    assert store.client.get(ROOT).json() == result
    deleted = store.client.delete(f"{ROOT}/steps/{result['steps'][1]['id']}").json()
    assert_order(deleted)
    assert deleted["steps"][1]["id"] == store.ids.anchor
    undone = store.client.post(f"{ROOT}/steps/{store.ids.history}/uncomplete").json()
    assert_order(undone)
    assert undone["steps"][0]["status"] == "current"
    assert store.client.get(ROOT).json() == undone


def test_deleting_user_cascades_receipts(store):
    post(store, body()).raise_for_status()
    with store.sessions() as db:
        # The profile deletion path removes routes first, then ORM-deletes user.
        for route in db.query(Route).filter_by(user_id=store.ids.user).all():
            db.delete(route)
        db.flush()
        db.delete(db.get(User, store.ids.user))
        db.commit()
        assert db.query(RouteAssignmentReceipt).count() == 0


def test_existing_database_initialization_adds_receipts_without_changing_routes(store, monkeypatch):
    from core.db import session as database

    before = store.client.get(ROOT).json()
    # Simulate the previous release: all application tables except new receipts.
    RouteAssignmentReceipt.__table__.drop(store.engine)
    monkeypatch.setattr(database, "engine", store.engine)
    monkeypatch.setattr(database, "_settings", SimpleNamespace(database_url=str(store.engine.url)))
    database.init_db()
    database.init_db()
    assert store.client.get(ROOT).json() == before
    payload = body({"title": "After upgrade"})
    result = post(store, payload)
    assert result.status_code == 200, result.text
    assert post(store, payload).json() == result.json()
    with store.sessions() as db:
        assert db.query(RouteAssignmentReceipt).count() == 1
