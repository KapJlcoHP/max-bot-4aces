"""Clinic compare-and-swap, consent bypasses and read-only legacy projections."""

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db.models import Base, Organization, RouteStep, User
from core.db.seed import build_route_for, project_step_clinic, seed_organizations
from core.schemas import ClinicChangeIn, ConsentIn, SettingsIn
from server.api.v1 import common, profile
from server.deps import PendingUser

REGION = "Ивановская область"
OTHER_REGION = "Владимирская область"


@pytest.fixture
def fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        clinics = [Organization(title=f"Клиника {n}", address=f"Адрес {n}", org_type=kind,
                                region=region, phone="", hours="", services=[])
                   for n, kind, region in [(1, "Поликлиники", REGION), (2, "Поликлиники", REGION),
                                           (3, "Поликлиники", OTHER_REGION), (4, "Больницы", REGION)]]
        user = User(max_user_id=990001, region=REGION, consent_at=datetime(2026, 1, 1), email="keep@example.test")
        db.add_all([user, *clinics])
        db.commit()
        yield db, user, clinics
    engine.dispose()


def choose(db, user, clinic_id, expected=None, region=REGION):
    return profile.change_clinic(ClinicChangeIn(attached_clinic_id=clinic_id, expected_clinic_id=expected,
                                               expected_region=region), user, db)


def conflict(callback):
    with pytest.raises(HTTPException) as caught:
        callback()
    assert caught.value.status_code == 409


def test_first_choice_change_retry_and_stale_requests(fixture):
    db, user, (first, second, _, _) = fixture
    choose(db, user, first.id)
    choose(db, user, first.id)  # Retry after a lost response.
    conflict(lambda: choose(db, user, second.id))
    assert user.attached_clinic_id == first.id
    choose(db, user, second.id, first.id)
    conflict(lambda: choose(db, user, first.id))
    assert user.attached_clinic_id == second.id
    assert user.email == "keep@example.test"


def test_invalid_and_stale_region_leave_choice_unchanged(fixture):
    db, user, (first, _, foreign, hospital) = fixture
    choose(db, user, first.id)
    for target in [foreign.id, hospital.id, 987654]:
        with pytest.raises(HTTPException) as caught:
            choose(db, user, target, first.id)
        assert caught.value.status_code == 422
    conflict(lambda: choose(db, user, first.id, first.id, OTHER_REGION))
    assert user.attached_clinic_id == first.id


def test_settings_and_repeated_consent_cannot_replace_or_detach(fixture):
    db, user, (first, second, _, _) = fixture
    profile.update_settings(SettingsIn(attached_clinic_id=first.id), user, db)
    for target in [None, second.id]:
        conflict(lambda: profile.update_settings(SettingsIn(attached_clinic_id=target, notifications_on=False), user, db))
        conflict(lambda: profile.give_consent_impl(ConsentIn(attached_clinic_id=target), user, db))
    profile.give_consent_impl(ConsentIn(attached_clinic_id=first.id), user, db)
    assert user.attached_clinic_id == first.id
    assert user.notifications_on


def test_region_reset_needs_ack_and_exact_state_and_is_atomic(fixture):
    db, user, (first, second, _, _) = fixture
    choose(db, user, first.id)
    for fields in [{}, {"confirm_clinic_reset": True},
                   {"confirm_clinic_reset": True, "expected_region": REGION, "expected_clinic_id": second.id}]:
        conflict(lambda: profile.update_settings(SettingsIn(region=OTHER_REGION, email="wrong", **fields), user, db))
        assert (user.region, user.attached_clinic_id, user.email) == (REGION, first.id, "keep@example.test")
    profile.update_settings(SettingsIn(region=OTHER_REGION, confirm_clinic_reset=True,
                                      expected_region=REGION, expected_clinic_id=first.id), user, db)
    assert (user.region, user.attached_clinic_id) == (OTHER_REGION, None)
    with pytest.raises(HTTPException) as caught:
        profile.update_settings(SettingsIn(region="Unknown"), user, db)
    assert caught.value.status_code == 422


def test_stale_orm_sessions_and_unrelated_settings_do_not_undo_cas(fixture):
    db, user, (first, second, _, _) = fixture
    with Session(db.bind, expire_on_commit=False) as other:
        stale = other.get(User, user.id)
        choose(db, user, first.id)
        conflict(lambda: choose(other, stale, second.id))
        profile.update_settings(SettingsIn(notifications_on=False), stale, other)
        db.refresh(user)
        assert user.attached_clinic_id == first.id
        assert not user.notifications_on
        choose(other, stale, second.id, first.id)
        conflict(lambda: choose(db, user, first.id))
        db.refresh(user)
        assert user.attached_clinic_id == second.id


def test_race_after_snapshot_checks_update_rowcount(fixture):
    db, user, (first, second, _, _) = fixture
    original = profile._profile_state
    with Session(db.bind) as rival:
        def race(session, current):
            state = original(session, current)
            rival.execute(update(User).where(User.id == current.id).values(attached_clinic_id=first.id))
            rival.commit()
            return state
        with patch.object(profile, "_profile_state", side_effect=race):
            conflict(lambda: choose(db, user, second.id))
    db.refresh(user)
    assert user.attached_clinic_id == first.id


def test_pending_account_collision_cannot_bypass_existing_choice(fixture):
    db, user, (first, second, _, _) = fixture
    choose(db, user, first.id)
    pending = PendingUser(max_user_id=user.max_user_id, region=REGION, first_name="", last_name="", email="", avatar_url="")
    conflict(lambda: profile.give_consent_impl(ConsentIn(region=REGION, attached_clinic_id=second.id), pending, db))
    db.refresh(user)
    assert user.attached_clinic_id == first.id


@pytest.mark.parametrize("same_target", [False, True])
@pytest.mark.parametrize("already_attached", [False, True])
def test_real_two_connection_attach_and_change_race(tmp_path, same_target, already_attached):
    engine = create_engine(f"sqlite:///{tmp_path / 'clinic-race.sqlite'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        user = User(max_user_id=990002, region=REGION, consent_at=datetime(2026, 1, 1))
        first = Organization(title="First", address="A", region=REGION, org_type="Поликлиники", phone="", hours="")
        second = Organization(title="Second", address="B", region=REGION, org_type="Поликлиники", phone="", hours="")
        previous = Organization(title="Previous", address="C", region=REGION, org_type="Поликлиники", phone="", hours="")
        setup.add_all([user, first, second, previous])
        setup.commit()
        expected = previous.id if already_attached else None
        user.attached_clinic_id = expected
        setup.commit()
        user_id, targets = user.id, [first.id, first.id if same_target else second.id]
    original = profile._profile_state
    gate = Barrier(2)
    def simultaneous_snapshot(db, user):
        state = original(db, user)
        if state.attached_clinic_id == expected:
            gate.wait(timeout=5)
        return state
    def attempt(target):
        with Session(engine) as db:
            try:
                choose(db, db.get(User, user_id), target, expected)
                return 200, target
            except HTTPException as error:
                return error.status_code, target
    try:
        with patch.object(profile, "_profile_state", side_effect=simultaneous_snapshot), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, targets))
        assert sorted(code for code, _ in results) == ([200, 200] if same_target else [200, 409])
        with Session(engine) as db:
            winner = next(target for code, target in results if code == 200)
            assert db.get(User, user_id).attached_clinic_id == winner
    finally:
        engine.dispose()


def test_http_dependencies_and_input_contract(fixture):
    db, user, (first, _, _, _) = fixture
    app = FastAPI()
    app.include_router(profile.router)
    app.dependency_overrides[common.db_session] = lambda: db
    # Keep the actual consent gate; only substitute the external identity dependency.
    app.dependency_overrides[common.current_user] = lambda: user
    with TestClient(app) as client:
        for payload in [{}, {"attached_clinic_id": 0, "expected_clinic_id": None, "expected_region": REGION},
                        {"attached_clinic_id": first.id, "expected_region": REGION},
                        {"attached_clinic_id": first.id, "expected_clinic_id": None, "expected_region": ""},
                        {"attached_clinic_id": first.id, "expected_clinic_id": None, "expected_region": "   "}]:
            assert client.post("/me/clinic", json=payload).status_code == 422
        user.consent_at = None
        assert client.post("/me/clinic", json={"attached_clinic_id": first.id,
                           "expected_clinic_id": None, "expected_region": REGION}).status_code == 403
        app.dependency_overrides[common.current_user] = lambda: (_ for _ in ()).throw(HTTPException(401))
        assert client.post("/me/clinic", json={"attached_clinic_id": first.id,
                           "expected_clinic_id": None, "expected_region": REGION}).status_code == 401


def test_real_pending_consent_account_creation_race_cannot_replace_first_choice(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'consent-race.sqlite'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        clinics = [Organization(title=title, address=title, region=REGION, org_type="Поликлиники", phone="", hours="")
                   for title in ["First", "Second"]]
        setup.add_all(clinics)
        setup.commit()
        targets = [clinic.id for clinic in clinics]
    gate = Barrier(2)
    def consent(target):
        with Session(engine) as db:
            pending = PendingUser(max_user_id=990003, region=REGION, first_name="", last_name="", email="", avatar_url="")
            gate.wait(timeout=5)
            try:
                profile.give_consent_impl(ConsentIn(region=REGION, attached_clinic_id=target), pending, db)
                return 200, target
            except HTTPException as error:
                return error.status_code, target
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consent, targets))
        assert sorted(code for code, _ in results) == [200, 409]
        with Session(engine) as db:
            assert db.query(User).count() == 1
            assert db.query(User).one().attached_clinic_id == next(target for code, target in results if code == 200)
    finally:
        engine.dispose()


@pytest.fixture
def clinic_scenario(monkeypatch):
    # Keep clinic/history regressions independent of editorial scenario length
    # and titles: this synthetic template deliberately has several clinic facts.
    from core.db import seed

    scenarios = seed.load_scenarios()
    scenarios["doctor"] = {
        "route_title": "Synthetic clinic projection",
        "steps": [
            {"key": "test-intro", "kind": "task", "title": "Выбрать поликлинику",
             "description": "Уточните порядок в {clinic}.", "place": "{clinic}"},
            {"key": "test-visit", "kind": "visit", "title": "Приём у врача", "place": "{clinic}"},
            {"key": "test-repeat", "kind": "visit", "title": "Повторный визит", "place": "{clinic}"},
            {"key": "test-final", "kind": "visit", "title": "Финальный приём", "place": "{clinic}"},
            {"key": "test-exam", "kind": "investigation", "title": "Профильное обследование",
             "place": "Диагностический центр"},
        ],
        "checklist": [],
    }
    monkeypatch.setattr(seed, "load_scenarios", lambda: scenarios)


def test_new_routes_first_choice_change_reset_and_completed_facts(fixture, clinic_scenario):
    db, user, (first, second, _, _) = fixture
    route = build_route_for(db, user, "doctor")
    for step in route.steps:
        assert "№12" not in step.place + step.description
        assert "304" not in step.place
    visit = next(step for step in route.steps if step.title == "Приём у врача")
    done = next(step for step in route.steps if step.title == "Повторный визит")
    done.status = "done"
    done.place = "Историческая клиника, кабинет 7"
    visit.note = "Моя заметка о поликлинике №12"
    manual = next(step for step in route.steps if step.title == "Финальный приём")
    manual.place = "Другой врач, кабинет 99"
    manual.description = "Личное описание"
    db.commit()
    choose(db, user, first.id)
    assert visit.place == f"{first.title}, {first.address}"
    choose(db, user, second.id, first.id)
    assert visit.place == f"{second.title}, {second.address}"
    assert done.place == "Историческая клиника, кабинет 7"
    assert manual.place == "Другой врач, кабинет 99"
    assert manual.description == "Личное описание"
    assert visit.note == "Моя заметка о поликлинике №12"
    profile.update_settings(SettingsIn(region=OTHER_REGION, confirm_clinic_reset=True,
                                      expected_region=REGION, expected_clinic_id=second.id), user, db)
    assert "Поликлиника не выбрана" in visit.place
    assert done.place == "Историческая клиника, кабинет 7"


def test_saved_legacy_dto_and_bot_projection_never_write_on_get(fixture, clinic_scenario):
    db, user, (first, second, _, _) = fixture
    route = build_route_for(db, user, "doctor")
    visit = next(step for step in route.steps if step.title == "Приём у врача")
    visit.place = "Поликлиника №12, каб. 304"
    introduction = route.steps[0]
    introduction.description = "Определена поликлиника по месту прикрепления — №12."
    introduction.place = ""
    db.commit()
    writes = []
    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
            writes.append(statement)
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        dto = common.route_dto(route)
        assert "Поликлиника не выбрана" in next(s.place for s in dto.steps if s.id == visit.id)
        assert "№12" not in dto.steps[0].description
        assert "Поликлиника не выбрана" in project_step_clinic(visit)["place"]
        assert visit.place == "Поликлиника №12, каб. 304"
        assert not db.dirty
        assert writes == []
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    choose(db, user, first.id)
    assert visit.place == f"{first.title}, {first.address}"
    visit.place += ", каб. 304"  # Legacy formatter output saved by an older release.
    db.commit()
    choose(db, user, second.id, first.id)
    assert visit.place == f"{second.title}, {second.address}"
    profile.update_settings(SettingsIn(region=OTHER_REGION, confirm_clinic_reset=True,
                                      expected_region=REGION, expected_clinic_id=second.id), user, db)
    assert "Поликлиника не выбрана" in visit.place
    assert "№12" not in introduction.description


def test_stale_route_identity_does_not_overwrite_completed_or_manually_edited_fact(fixture, clinic_scenario):
    db, user, (first, _, _, _) = fixture
    route = build_route_for(db, user, "doctor")
    visit = next(step for step in route.steps if step.title == "Приём у врача")
    edited = next(step for step in route.steps if step.title == "Повторный визит")
    with Session(db.bind) as other:
        other.execute(update(RouteStep).where(RouteStep.id == visit.id).values(status="done", place="Фактический визит"))
        other.execute(update(RouteStep).where(RouteStep.id == edited.id).values(place="Уточнённое место"))
        other.commit()
    # Both objects in this session still hold the old template fields/status.
    choose(db, user, first.id)
    db.refresh(visit)
    db.refresh(edited)
    assert (visit.status, visit.place) == ("done", "Фактический визит")
    assert edited.place == "Уточнённое место"


def test_unrelated_manual_doctor_duplicate_and_inactive_steps_not_bound(fixture, clinic_scenario):
    db, user, (first, _, _, _) = fixture
    choose(db, user, first.id)
    route = build_route_for(db, user, "doctor")
    unrelated = next(s for s in route.steps if s.title == "Профильное обследование")
    assert project_step_clinic(unrelated)["place"] == "Диагностический центр"
    visit = next(s for s in route.steps if s.title == "Приём у врача")
    duplicate = RouteStep(route_id=route.id, position=99, title=visit.title, source_id=visit.source_id,
                          source="template", place="Поликлиника №12, каб. 304")
    route.steps.append(duplicate)
    db.commit()
    assert project_step_clinic(duplicate)["place"] == duplicate.place
    duplicate.source = "doctor"
    assert project_step_clinic(duplicate)["place"] == duplicate.place
    route.active = False
    visit.place = "История"
    assert project_step_clinic(visit)["place"] == "История"


def test_repeated_catalog_seed_keeps_ids_and_real_ivanovo_clinic(fixture):
    db, user, _ = fixture
    seed_organizations(db)
    clinic = db.query(Organization).filter(Organization.org_type == "Поликлиники", Organization.region == REGION).first()
    choose(db, user, clinic.id)
    before = [(org.id, org.title) for org in db.query(Organization).order_by(Organization.id)]
    seed_organizations(db)
    assert [(org.id, org.title) for org in db.query(Organization).order_by(Organization.id)] == before
    db.refresh(user)
    assert user.attached_clinic_id == clinic.id
    assert any("Ивановская городская поликлиника №2" == title for _, title in before)
