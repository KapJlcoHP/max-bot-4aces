"""Read-only доступ помощника: приглашение, snapshot и отзыв прав."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, FamilyAccess, HealthRecord, MedCourse, MedIntake, Route, RouteStep, User
from core.schemas import FamilyAcceptIn, FamilyInviteIn
from server.api.v1 import misc


@pytest.fixture
def family_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(max_user_id=700001, first_name="Анна", last_name="Иванова", consent_at=datetime(2026, 10, 20, 8))
        viewer = User(max_user_id=700002, first_name="Иван", last_name="Иванов", consent_at=datetime(2026, 10, 20, 8))
        db.add_all([owner, viewer])
        db.commit()
        yield db, owner, viewer
    engine.dispose()


def test_invitation_is_one_time_and_binds_to_real_viewer(family_db):
    db, owner, viewer = family_db
    invitation = misc.create_family_invitation(FamilyInviteIn(label="Иван", expires_days=7), owner, db)
    assert invitation.code.count("-") == 2
    stored = db.get(FamilyAccess, invitation.access.id)
    assert stored is not None
    assert stored.invite_hash != invitation.code
    assert stored.viewer_id is None

    accepted = misc.accept_family_invitation(FamilyAcceptIn(code=invitation.code), viewer, db)
    assert accepted.status == "active"
    assert accepted.viewer_name == "Иван Иванов"
    assert db.get(FamilyAccess, invitation.access.id).viewer_id == viewer.id

    with pytest.raises(HTTPException) as error:
        misc.accept_family_invitation(FamilyAcceptIn(code=invitation.code), viewer, db)
    assert error.value.status_code == 404


def test_snapshot_contains_route_and_aggregated_statuses_but_no_raw_health_data(family_db):
    db, owner, viewer = family_db
    owner.tz = "Europe/Moscow"
    route = Route(user_id=owner.id, situation_key="doctor", title="Маршрут к врачу", subtitle="Подготовка", active=True)
    db.add(route)
    db.flush()
    db.add_all([
        RouteStep(route_id=route.id, position=1, title="Записаться", kind="booking", status="done", completed_at=datetime(2026, 10, 20, 9), appointment_date=date(2026, 10, 24)),
        RouteStep(route_id=route.id, position=2, title="Прийти на приём", kind="visit", status="current", deadline=date(2026, 10, 24), place="Поликлиника"),
    ])
    db.add(HealthRecord(user_id=owner.id, type="bp", at=datetime(2026, 10, 20, 10), systolic=124, diastolic=82, pulse=71, note="личная заметка"))
    course = MedCourse(user_id=owner.id, name="Лекарство", times=["08:00", "20:00"], enabled=True)
    db.add(course)
    db.flush()
    db.add(MedIntake(user_id=owner.id, course_id=course.id, day=date(2026, 10, 20), at_time="08:00", taken_at=datetime(2026, 10, 20, 8)))
    db.commit()

    invitation = misc.create_family_invitation(FamilyInviteIn(), owner, db)
    misc.accept_family_invitation(FamilyAcceptIn(code=invitation.code), viewer, db)
    with patch.object(misc, "user_today", return_value=date(2026, 10, 20)):
        snapshot = misc.family_snapshot(invitation.access.id, viewer, db)

    assert snapshot.owner_name == "Анна Иванова"
    assert snapshot.route is not None
    assert [step.status for step in snapshot.route.steps] == ["done", "current"]
    assert snapshot.diaries[0].filled_today is True
    assert snapshot.medication.planned_today == 2
    assert snapshot.medication.taken_today == 1
    assert not hasattr(snapshot.diaries[0], "systolic")
    assert not hasattr(snapshot.diaries[0], "note")


def test_snapshot_formats_utc_timestamps_in_owner_timezone(family_db):
    db, owner, viewer = family_db
    owner.tz = "Europe/Moscow"
    route = Route(user_id=owner.id, situation_key="doctor", title="Маршрут", subtitle="", active=True)
    db.add(route)
    db.flush()
    db.add(RouteStep(
        route_id=route.id,
        position=1,
        title="Визит",
        kind="visit",
        status="done",
        completed_at=datetime(2026, 10, 20, 9, 0),
    ))
    db.commit()

    invitation = misc.create_family_invitation(FamilyInviteIn(), owner, db)
    misc.accept_family_invitation(FamilyAcceptIn(code=invitation.code), viewer, db)
    with patch.object(misc, "utcnow", return_value=datetime(2026, 10, 20, 9, 30)):
        snapshot = misc.family_snapshot(invitation.access.id, viewer, db)

    assert snapshot.route is not None
    assert snapshot.route.steps[0].completed_at.isoformat() == "2026-10-20T12:00:00+03:00"
    assert snapshot.generated_at.isoformat() == "2026-10-20T12:30:00+03:00"


def test_revoke_is_immediate_and_expired_access_cannot_read(family_db):
    db, owner, viewer = family_db
    invitation = misc.create_family_invitation(FamilyInviteIn(), owner, db)
    misc.accept_family_invitation(FamilyAcceptIn(code=invitation.code), viewer, db)
    updated = misc.revoke_family_access(invitation.access.id, owner, db)
    assert updated.status == "revoked"
    with pytest.raises(HTTPException) as error:
        misc.family_snapshot(invitation.access.id, viewer, db)
    assert error.value.status_code == 403

    fresh = misc.create_family_invitation(FamilyInviteIn(), owner, db)
    row = db.get(FamilyAccess, fresh.access.id)
    row.expires_at = datetime.now() - timedelta(days=1)
    db.commit()
    with pytest.raises(HTTPException) as expired:
        misc.accept_family_invitation(FamilyAcceptIn(code=fresh.code), viewer, db)
    assert expired.value.status_code == 410
