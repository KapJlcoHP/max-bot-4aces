"""C5: city-first location contract and safe legacy conversion."""

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.db.models import Base, Reminder, Route, RouteStep, User
from core.db import session as db_session
from core.schemas import ConsentIn, SettingsIn, UserDto
from core.time import db_utc, user_local, user_zone
from server.api.v1 import profile


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_supported_city_derives_internal_tz_without_exposing_it(db):
    user = User(max_user_id=610001, region="Ивановская область")
    db.add(user)
    db.commit()

    saved = profile.give_consent_impl(
        ConsentIn(region="Ивановская область", city="Иваново"), user, db
    )

    assert (saved.city, saved.region, saved.tz) == ("Иваново", "Ивановская область", "Europe/Moscow")
    assert "tz" not in UserDto.model_fields
    assert "tz" not in UserDto.model_validate(saved).model_dump()


def test_kazan_is_available_as_a_second_pilot_city(db):
    user = User(max_user_id=610007, region="Республика Татарстан")
    db.add(user)
    db.commit()

    saved = profile.give_consent_impl(
        ConsentIn(region="Республика Татарстан", city="Казань"), user, db
    )

    assert (saved.city, saved.region, saved.tz) == ("Казань", "Республика Татарстан", "Europe/Moscow")


@pytest.mark.parametrize("city, region", [
    ("Владимир", "Ивановская область"),  # city belongs to another region
    ("Иваново", "Владимирская область"),  # region is outside the pilot
    ("Несуществующий", "Ивановская область"),
])
def test_city_and_region_are_checked_against_the_pilot_directory(db, city, region):
    user = User(max_user_id=610002, region="Ивановская область")
    db.add(user)
    db.commit()

    with pytest.raises(HTTPException) as error:
        profile.give_consent_impl(ConsentIn(region=region, city=city), user, db)

    assert error.value.status_code == 422
    db.refresh(user)
    assert user.consent_at is None and user.city is None


def test_city_save_failure_does_not_leave_a_partial_location(db, monkeypatch):
    user = User(max_user_id=610003, region="Ивановская область")
    db.add(user)
    db.commit()
    monkeypatch.setattr(profile, "_save_profile", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("write failed")))

    with pytest.raises(RuntimeError):
        profile.give_consent_impl(ConsentIn(region="Ивановская область", city="Иваново"), user, db)

    db.rollback()
    db.refresh(user)
    assert user.city is None and user.consent_at is None


def test_region_change_clears_city_until_user_chooses_a_new_one(db):
    user = User(
        max_user_id=610004,
        consent_at=datetime(2026, 10, 18),
        region="Ивановская область",
        city="Иваново",
    )
    db.add(user)
    db.commit()

    saved = profile.update_settings(
        SettingsIn(
            region="Владимирская область",
            expected_region="Ивановская область",
            expected_clinic_id=None,
        ),
        user,
        db,
    )

    assert (saved.region, saved.city) == ("Владимирская область", None)


def test_legacy_city_migration_only_uses_an_unambiguous_region_match(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                max_user_id INTEGER NOT NULL,
                region VARCHAR(100) NOT NULL DEFAULT '',
                tz VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'
            )
        """))
        connection.execute(text("INSERT INTO users (id, max_user_id, region, tz) VALUES (1, 1, 'Ивановская область', 'Europe/Moscow')"))
        connection.execute(text("INSERT INTO users (id, max_user_id, region, tz) VALUES (2, 2, '', 'Europe/Moscow')"))
        connection.execute(text("INSERT INTO users (id, max_user_id, region, tz) VALUES (3, 3, 'Ивановская область', 'Asia/Irkutsk')"))

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session._settings, "database_url", f"sqlite:///{database}")
    db_session._migrate_sqlite()

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, city FROM users ORDER BY id")).all()
        assert rows == [(1, "Иваново"), (2, None), (3, None)]
        assert connection.execute(text("SELECT name FROM data_migrations WHERE name = 'user_city_v1'")).first()

    engine.dispose()


def test_client_timezone_override_is_not_part_of_the_location_contract(db):
    consent = ConsentIn.model_validate({
        "region": "Ивановская область", "city": "Иваново", "tz": "Asia/Tokyo",
    })
    settings = SettingsIn.model_validate({"city": "Иваново", "tz": "Asia/Tokyo"})
    assert "tz" not in ConsentIn.model_fields
    assert "tz" not in SettingsIn.model_fields
    assert "tz" not in consent.model_dump()
    assert "tz" not in settings.model_dump()

    user = User(max_user_id=610006, region="Ивановская область")
    db.add(user)
    db.commit()
    saved = profile.give_consent_impl(consent, user, db)
    assert saved.tz == "Europe/Moscow"


def test_city_change_moves_only_future_notification_moments(db, monkeypatch):
    old_tz = "Europe/Moscow"
    new_tz = "Asia/Tokyo"
    future_wall = datetime(2031, 1, 10, 10, 0)
    past_wall = datetime(2020, 1, 10, 10, 0)
    user = User(
        max_user_id=610005, consent_at=datetime(2026, 10, 18),
        region="Ивановская область", city="Иваново", tz=old_tz,
    )
    db.add(user)
    db.flush()
    future_reminder = Reminder(user_id=user.id, title="future", at=db_utc(future_wall, user_zone(old_tz)))
    past_reminder = Reminder(user_id=user.id, title="past", at=db_utc(past_wall, user_zone(old_tz)))
    done_future = Reminder(
        user_id=user.id, title="done", at=db_utc(future_wall, user_zone(old_tz)),
        done_at=datetime(2026, 10, 18),
    )
    route = Route(user_id=user.id, situation_key="test", title="Test")
    db.add_all([future_reminder, past_reminder, done_future, route])
    db.flush()
    future_step = RouteStep(
        route_id=route.id, position=1, title="future step", status="current",
        deadline=future_wall.date(), reminder_mode="custom",
        reminder_at=db_utc(future_wall, user_zone(old_tz)),
    )
    past_step = RouteStep(
        route_id=route.id, position=2, title="past step", status="current",
        deadline=past_wall.date(), reminder_mode="custom",
        reminder_at=db_utc(past_wall, user_zone(old_tz)),
    )
    done_step = RouteStep(
        route_id=route.id, position=3, title="done step", status="done",
        deadline=future_wall.date(), reminder_mode="custom",
        reminder_at=db_utc(future_wall, user_zone(old_tz)),
    )
    db.add_all([future_step, past_step, done_step])
    db.commit()
    old_future = future_reminder.at
    old_past = past_reminder.at
    old_done = done_future.at
    old_step_future = future_step.reminder_at
    old_step_past = past_step.reminder_at
    old_step_done = done_step.reminder_at

    original_city = profile.city_for_location
    monkeypatch.setattr(
        profile, "city_for_location",
        lambda city, region: (
            {"title": "Тестовый город", "region": region, "tz": new_tz}
            if city == "Тестовый город" else original_city(city, region)
        ),
    )
    saved = profile.update_settings(
        SettingsIn(
            region="Ивановская область", city="Тестовый город",
            expected_region="Ивановская область", expected_clinic_id=None,
        ),
        user, db,
    )

    assert (saved.city, saved.tz) == ("Тестовый город", new_tz)
    assert future_reminder.at == db_utc(future_wall, user_zone(new_tz))
    assert future_reminder.at != old_future
    assert past_reminder.at == old_past
    assert done_future.at == old_done
    assert future_step.reminder_at == db_utc(future_wall, user_zone(new_tz))
    assert future_step.reminder_at != old_step_future
    assert past_step.reminder_at == old_step_past
    assert done_step.reminder_at == old_step_done
    assert user_local(future_reminder.at, saved.tz).replace(tzinfo=None) == future_wall
