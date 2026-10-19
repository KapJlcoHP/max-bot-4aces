"""P1.2: schedule edits, DST zones, stale snapshots and isolated delivery ticks."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.scheduler import collect_due, revalidate_step_push, scheduler_loop
from core.db.models import Base, NotificationLog, Route, RouteStep, User
from core.schemas import StepUpdateIn
from core.time import strict_local_utc
from server.api.v1 import route as route_api


NOW = datetime(2030, 1, 1, 9)
DAY = date(2030, 1, 3)
NEXT_DAY = date(2030, 1, 4)


@pytest.fixture
def schedule_state():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(max_user_id=931201, tz="UTC", consent_at=NOW)
        db.add(user)
        db.flush()
        route = Route(user_id=user.id, situation_key="custom", title="P1.2")
        db.add(route)
        db.flush()
        step = RouteStep(
            route_id=route.id,
            position=1,
            title="Visit",
            status="current",
            deadline=DAY,
            deadline_time="14:00",
            activated_at=NOW,
        )
        db.add(step)
        db.commit()
        yield db, user, route, step, sessions
    engine.dispose()


def test_date_transfer_clear_and_profile_reset_advance_dedup_revision(schedule_state):
    db, user, _, step, _ = schedule_state

    # A custom timer is intentionally not moved implicitly with the event.
    response = route_api.update_step(
        step.id,
        StepUpdateIn(reminder_mode="custom", reminder_at=datetime(2030, 1, 2, 12)),
        user=user,
        db=db,
    )
    assert response.reminder_mode == "custom"
    assert response.reminder_at == datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
    assert step.reminder_revision == 1
    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="custom:1"))
    db.commit()

    with pytest.raises(HTTPException) as error:
        route_api.update_step(
            step.id,
            StepUpdateIn(deadline=NEXT_DAY),
            user=user,
            db=db,
        )
    assert getattr(error.value, "status_code", None) == 422
    db.refresh(step)
    assert (step.deadline, step.deadline_time, step.reminder_mode, step.reminder_at) == (
        DAY,
        "14:00",
        "custom",
        datetime(2030, 1, 2, 12),
    )
    assert db.query(NotificationLog).count() == 1

    # Returning to the profile mode explicitly clears the custom instant and
    # its old receipt; the next event move can preserve the event clock.
    route_api.update_step(
        step.id,
        StepUpdateIn(reminder_mode="profile"),
        user=user,
        db=db,
    )
    assert (step.reminder_mode, step.reminder_at, step.reminder_revision) == ("profile", None, 2)
    assert db.query(NotificationLog).count() == 0

    db.add(NotificationLog(user_id=user.id, kind="step", ref_id=step.id, lead="hour"))
    db.commit()
    route_api.update_step(step.id, StepUpdateIn(deadline=NEXT_DAY), user=user, db=db)
    assert (step.deadline, step.deadline_time, step.reminder_revision) == (NEXT_DAY, "14:00", 3)
    assert db.query(NotificationLog).count() == 0

    route_api.update_step(step.id, StepUpdateIn(deadline_time=None), user=user, db=db)
    assert (step.deadline, step.deadline_time, step.reminder_revision) == (NEXT_DAY, None, 4)

    # Clearing the date also clears its dependent event clock and leaves the
    # profile mode without manufacturing a replacement time.
    route_api.update_step(step.id, StepUpdateIn(deadline=None), user=user, db=db)
    assert (step.deadline, step.deadline_time, step.reminder_mode, step.reminder_at) == (
        None,
        None,
        "profile",
        None,
    )


@pytest.mark.parametrize(
    "tz, wall_event",
    [
        ("Europe/Moscow", datetime(2030, 3, 10, 10, 30)),
        ("America/New_York", datetime(2030, 3, 10, 3, 30)),
        ("Europe/Berlin", datetime(2030, 3, 31, 3, 30)),
        ("Asia/Tokyo", datetime(2030, 3, 10, 10, 30)),
    ],
)
def test_hour_window_uses_real_instants_in_multiple_zones(schedule_state, tz, wall_event):
    db, _, _, _, _ = schedule_state
    user = User(max_user_id=931202 + len(db.query(User).all()), tz=tz, consent_at=NOW)
    db.add(user)
    db.flush()
    route = Route(user_id=user.id, situation_key="custom", title=tz)
    db.add(route)
    db.flush()
    step = RouteStep(
        route_id=route.id,
        position=1,
        title=f"Visit in {tz}",
        status="current",
        deadline=wall_event.date(),
        deadline_time=f"{wall_event:%H:%M}",
        activated_at=NOW,
    )
    db.add(step)
    db.commit()

    event_utc = strict_local_utc(wall_event, tz).replace(tzinfo=timezone.utc)
    pushes = collect_due(db, now=event_utc - timedelta(hours=1), user_id=user.id)
    assert [(push.kind, push.lead) for push in pushes] == [("step", "hour")]


@pytest.mark.parametrize("wall_event", [datetime(2030, 3, 10, 2, 30), datetime(2030, 11, 3, 1, 30)])
def test_dst_gap_or_fold_never_creates_a_step_window(schedule_state, wall_event):
    db, _, _, _, _ = schedule_state
    user = User(max_user_id=931210 + wall_event.day, tz="America/New_York", consent_at=NOW)
    db.add(user)
    db.flush()
    route = Route(user_id=user.id, situation_key="custom", title="DST")
    db.add(route)
    db.flush()
    db.add(RouteStep(
        route_id=route.id,
        position=1,
        title="DST event",
        status="current",
        deadline=wall_event.date(),
        deadline_time=f"{wall_event:%H:%M}",
        activated_at=NOW,
    ))
    db.commit()

    # collect_due deliberately treats an unrepresentable/ambiguous event as
    # non-deliverable instead of inventing one of the two possible instants.
    assert collect_due(db, now=datetime(2030, 11, 4, tzinfo=timezone.utc), user_id=user.id) == []


@pytest.mark.parametrize("mutation", ["done", "moved"])
def test_presend_snapshot_is_rejected_after_completion_or_transfer(schedule_state, mutation):
    db, user, _, step, sessions = schedule_state
    now = datetime(2030, 1, 3, 13, tzinfo=timezone.utc)
    push = collect_due(db, now=now, user_id=user.id)[0]

    with sessions() as writer:
        fresh = writer.get(RouteStep, step.id)
        if mutation == "done":
            fresh.status = "done"
        else:
            fresh.deadline = NEXT_DAY
        writer.commit()

    assert not revalidate_step_push(db, push, now)


def test_scheduler_ticks_retry_network_and_persist_one_receipt(schedule_state):
    db, user, _, step, sessions = schedule_state
    now = datetime(2030, 1, 3, 14)
    attempts = []
    delivered = []
    ticks = 0

    class Bot:
        async def send_message(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise OSError("temporary network failure")
            delivered.append(kwargs)

    async def run_scheduler():
        async def tick(_):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                raise asyncio.CancelledError()

        with (
            patch("bot.scheduler.SessionLocal", sessions),
            patch("bot.scheduler._user_now", return_value=now),
            patch("bot.scheduler.asyncio.sleep", side_effect=tick),
            patch("bot.scheduler.log.exception"),
        ):
            with pytest.raises(asyncio.CancelledError):
                await scheduler_loop(Bot(), None)

    asyncio.run(run_scheduler())

    assert len(attempts) == 2
    assert len(delivered) == 1
    with sessions() as check:
        receipts = check.query(NotificationLog).filter_by(
            user_id=user.id, kind="step", ref_id=step.id,
        ).all()
        assert [(receipt.lead,) for receipt in receipts] == [("now",)]
        assert collect_due(check, now=now, user_id=user.id) == []
