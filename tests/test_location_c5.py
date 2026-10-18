"""C5: city-first location contract and safe legacy conversion."""

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.db.models import Base, User
from core.db import session as db_session
from core.schemas import ConsentIn, SettingsIn, UserDto
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
