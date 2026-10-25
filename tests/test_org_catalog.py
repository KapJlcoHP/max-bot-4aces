"""Unified catalog contract through HTTP, with synthetic in-memory data only."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db.models import Base, Organization, User
from core.db.seed import seed_organizations
from server.api.v1 import common, misc
from server.deps import PendingUser

REGION = "Ивановская область"
OTHER = "Владимирская область"


@pytest.fixture
def catalog():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organizations = [
            Organization(title="Тестовая Поликлиника", address="Улица Северная, 1", region=REGION,
                         org_type="Поликлиники", phone="", hours="", services=[], lat=57.0, lon=41.0),
            Organization(title="Тестовая Поликлиника", address="Улица Южная, 2", region=OTHER,
                         org_type="Поликлиники", phone="", hours="", services=[], lat=None, lon=None),
            Organization(title="Тестовый Центр 100%", address="Улица Северная, 3", region=OTHER,
                         org_type="Центры", phone="", hours="", services=[], lat=56.0, lon=40.0),
        ]
        user = User(max_user_id=991001, region=REGION, consent_at=datetime(2026, 1, 1))
        db.add_all([user, *organizations])
        db.commit()
        user.attached_clinic_id = organizations[0].id
        db.commit()
        app = FastAPI()
        app.include_router(misc.router, prefix="/api/v1")
        app.dependency_overrides[common.db_session] = lambda: db
        app.dependency_overrides[common.current_user] = lambda: user
        with TestClient(app) as client:
            yield client, db, user, organizations, app
    engine.dispose()


def read(client, **params):
    response = client.get("/api/v1/orgs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_omitted_region_is_profile_but_explicit_all_really_removes_filter(catalog):
    client, _, user, orgs, _ = catalog
    assert [row["id"] for row in read(client)] == [orgs[0].id]
    for value in ["", "Все", "  "]:
        assert [row["id"] for row in read(client, region=value)] == [org.id for org in orgs]
    assert [row["id"] for row in read(client, region=OTHER)] == [orgs[1].id, orgs[2].id]
    assert (user.region, user.attached_clinic_id) == (REGION, orgs[0].id)


def test_pending_onboarding_user_keeps_default_and_can_explicitly_browse_all(catalog):
    client, _, _, orgs, app = catalog
    pending = PendingUser(max_user_id=991002, region=REGION, first_name="", last_name="", email="", avatar_url="")
    app.dependency_overrides[common.current_user] = lambda: pending
    assert [row["id"] for row in read(client)] == [orgs[0].id]
    assert len(read(client, region="")) == 3


def test_seed_keeps_21_rows_both_regional_centers_and_readback_after_repeated_seed(catalog):
    client, db, user, _, _ = catalog
    seed_organizations(db)
    first = read(client, region="")
    seed_organizations(db)
    second = read(client, region="")
    assert len(first) == len(second) == 21
    assert first == second
    centers = [row for row in second if row["title"] == "Областной перинатальный центр"]
    assert {row["region"] for row in centers} == {"Владимирская область", "Ярославская область"}
    assert len({row["id"] for row in centers}) == 2
    for row in centers:
        response = client.get(f"/api/v1/orgs/{row['id']}")
        assert response.status_code == 200 and response.json() == row
    # Synthetic attachment points to an obsolete seed entry, so seed safely clears it.
    db.refresh(user)
    assert user.region == REGION and user.attached_clinic_id is None


def test_filters_combine_and_search_cyrillic_without_case_or_wildcard_surprises(catalog):
    client, _, _, orgs, _ = catalog
    assert [row["id"] for row in read(client, region="", org_type="Поликлиники", q="  ТЕСТОВАЯ  ")] == [orgs[0].id, orgs[1].id]
    assert [row["id"] for row in read(client, region=OTHER, org_type="Поликлиники", q="южная")] == [orgs[1].id]
    assert read(client, region=REGION, org_type="Центры") == []
    assert [row["id"] for row in read(client, region="", q="100%")] == [orgs[2].id]
    assert read(client, region="", q="_") == []
    assert read(client, region="Несуществующий регион") == []


def test_missing_coordinates_stay_in_catalog_and_foreign_legacy_link_is_read_only(catalog):
    client, db, user, orgs, _ = catalog
    rows = read(client, region="", org_type="Поликлиники")
    assert len(rows) == 2 and rows[1]["lat"] is None and rows[1]["lon"] is None
    response = client.get(f"/api/v1/orgs/{orgs[1].id}")
    assert response.status_code == 200
    assert response.json() == rows[1]
    assert client.get("/api/v1/orgs/999999").status_code == 404
    db.refresh(user)
    assert (user.region, user.attached_clinic_id) == (REGION, orgs[0].id)
