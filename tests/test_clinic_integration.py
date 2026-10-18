"""Проверки координат, прикрепления и подстановки клиники в маршрут."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, Organization, User
from core.schemas import ConsentIn, OrganizationDto, SettingsIn
from server.api.v1 import api
from server.deps import PendingUser


class ClinicIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.ivanovo = Organization(
            title="Поликлиника тестовая", org_type="Поликлиники",
            region="Ивановская область", address="ул. Тестовая, 1",
            phone="", hours="", services=[], lat=57.1, lon=41.2,
        )
        self.vladimir = Organization(
            title="Поликлиника Владимирская", org_type="Поликлиники",
            region="Владимирская область", address="ул. Тестовая, 2",
            phone="", hours="", services=[], lat=56.1, lon=40.4,
        )
        self.hospital = Organization(
            title="Больница тестовая", org_type="Больницы",
            region="Ивановская область", address="ул. Тестовая, 3",
            phone="", hours="", services=[], lat=57.2, lon=41.3,
        )
        self.db.add_all([self.ivanovo, self.vladimir, self.hospital])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_organization_dto_contains_coordinates(self):
        dto = OrganizationDto.model_validate(self.ivanovo)
        self.assertEqual((dto.lat, dto.lon), (57.1, 41.2))

    def test_map_config_exposes_only_public_client_configuration(self):
        with patch(
            "server.api.v1.misc.get_settings",
            return_value=SimpleNamespace(yandex_maps_api_key="public-key"),
        ):
            config = api.maps_config()

        self.assertEqual(config.model_dump(), {"enabled": True, "api_key": "public-key"})

    def test_pending_consent_attaches_only_a_clinic_in_selected_region(self):
        pending = PendingUser(
            max_user_id=801001, first_name="Новый", last_name="Пользователь",
            email="user801001@demo.local", avatar_url="", region="Ивановская область",
        )
        with self.assertRaises(HTTPException):
            api.give_consent(
                ConsentIn(region="Ивановская область", attached_clinic_id=self.vladimir.id),
                user=pending, db=self.db,
            )
        self.assertIsNone(self.db.query(User).filter_by(max_user_id=pending.max_user_id).first())

        created = api.give_consent(
            ConsentIn(region="Ивановская область", attached_clinic_id=self.ivanovo.id),
            user=pending, db=self.db,
        )
        self.assertEqual(created.attached_clinic_id, self.ivanovo.id)

    def test_pending_consent_can_continue_without_a_clinic(self):
        pending = PendingUser(
            max_user_id=801005, first_name="Новый", last_name="Пользователь",
            email="user801005@demo.local", avatar_url="", region="Ивановская область",
        )

        created = api.give_consent(
            ConsentIn(region="Ивановская область", attached_clinic_id=None),
            user=pending, db=self.db,
        )

        self.assertIsNone(created.attached_clinic_id)

    def test_org_search_matches_address(self):
        pending = PendingUser(
            max_user_id=801006, first_name="Новый", last_name="Пользователь",
            email="user801006@demo.local", avatar_url="", region="Ивановская область",
        )

        rows = api.orgs(q="ул. Тестовая, 1", region="Ивановская область", user=pending, db=self.db)

        self.assertEqual([row.title for row in rows], [self.ivanovo.title])

    def test_settings_region_change_clears_foreign_clinic(self):
        user = User(
            max_user_id=801002, region="Ивановская область",
            consent_at=datetime(2026, 1, 1), attached_clinic_id=self.ivanovo.id,
        )
        self.db.add(user)
        self.db.commit()

        updated = api.update_settings(
            SettingsIn(region="Владимирская область", confirm_clinic_reset=True,
                       expected_region=user.region, expected_clinic_id=self.ivanovo.id), user=user, db=self.db,
        )
        self.assertEqual(updated.region, "Владимирская область")
        self.assertIsNone(updated.attached_clinic_id)

    def test_step_notification_settings_are_partial_and_persisted(self):
        user = User(max_user_id=801008, consent_at=datetime(2026, 1, 1))
        self.db.add(user)
        self.db.commit()

        updated = api.update_settings(
            SettingsIn(notify_day_before=False, notify_at_deadline=False, step_day_before_time="18:30"),
            user=user,
            db=self.db,
        )
        self.assertFalse(updated.notify_day_before)
        self.assertTrue(updated.notify_hour_before)
        self.assertFalse(updated.notify_at_deadline)
        self.assertEqual(updated.step_day_before_time, "18:30")

        updated = api.update_settings(
            SettingsIn(notify_hour_before=False), user=user, db=self.db,
        )
        self.assertEqual(
            (updated.notify_day_before, updated.notify_hour_before, updated.notify_at_deadline),
            (False, False, False),
        )
        self.db.refresh(user)
        self.assertEqual(
            (user.notify_day_before, user.notify_hour_before, user.notify_at_deadline),
            (False, False, False),
        )

    def test_orgs_is_available_to_pending_user_and_supports_region_filter(self):
        pending = PendingUser(
            max_user_id=801003, first_name="Новый", last_name="Пользователь",
            email="user801003@demo.local", avatar_url="", region="Ивановская область",
        )
        rows = api.orgs(region="Владимирская область", user=pending, db=self.db)
        self.assertEqual([row.title for row in rows], [self.vladimir.title])

    def test_route_place_uses_attached_clinic_name_and_address(self):
        user = User(
            max_user_id=801004, region="Ивановская область",
            consent_at=datetime(2026, 1, 1), attached_clinic_id=self.ivanovo.id,
        )
        self.db.add(user)
        self.db.commit()

        route = api.start_route(
            api.RouteStartIn(situation_key="chronic"), user=user, db=self.db,
        )
        place = next(step.place for step in route.steps if step.place)
        self.assertIn(self.ivanovo.title, place)
        self.assertIn(self.ivanovo.address, place)

    def test_existing_route_refreshes_when_clinic_is_selected_or_removed(self):
        user = User(
            max_user_id=801007, region="Ивановская область",
            consent_at=datetime(2026, 1, 1), attached_clinic_id=None,
        )
        self.db.add(user)
        self.db.commit()

        route = api.start_route(api.RouteStartIn(situation_key="chronic"), user=user, db=self.db)
        visit = next(step for step in route.steps if step.kind == "visit")
        self.assertIn("Поликлиника не выбрана", visit.place)

        api.update_settings(
            SettingsIn(attached_clinic_id=self.ivanovo.id), user=user, db=self.db,
        )
        refreshed = api.get_route(user=user, db=self.db)
        refreshed_visit = next(step for step in refreshed.steps if step.id == visit.id)
        self.assertIn(self.ivanovo.title, refreshed_visit.place)
        self.assertIn(self.ivanovo.address, refreshed_visit.place)

        api.update_settings(SettingsIn(region="Владимирская область", confirm_clinic_reset=True,
                                       expected_region=user.region, expected_clinic_id=self.ivanovo.id), user=user, db=self.db)
        restored = api.get_route(user=user, db=self.db)
        restored_visit = next(step for step in restored.steps if step.id == visit.id)
        self.assertIn("Поликлиника не выбрана", restored_visit.place)


if __name__ == "__main__":
    unittest.main()
