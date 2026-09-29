"""Регрессии удаления данных, демо-сводки и первого входа."""

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.demo import fill_demo
from core.db.models import Base, BpRecord, HealthRecord, HealthSetting, MedCourse, MedIntake, User
from core.schemas import ConsentIn, HealthSettingDto
from core.services import user_today
from server.deps import PendingUser


# PDF-зависимость не нужна для этих API-функций и может отсутствовать в локальном venv.
pdf_module = types.ModuleType("server.health_pdf")
pdf_module.build_health_pdf = lambda *args, **kwargs: b""
with patch.dict(sys.modules, {"server.health_pdf": pdf_module}):
    api = importlib.import_module("server.api.v1.api")


class DataLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=510001)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_deleting_account_removes_legacy_and_current_pressure_records(self):
        self.db.add(BpRecord(user_id=self.user.id, at=datetime(2026, 9, 1, 8), systolic=120, diastolic=80, pulse=70))
        self.db.add(HealthRecord(user_id=self.user.id, type="bp", at=datetime(2026, 9, 1, 8), systolic=120, diastolic=80, pulse=70))
        self.db.commit()

        api.delete_my_data(user=self.user, db=self.db)

        self.assertEqual(self.db.query(User).count(), 0)
        self.assertEqual(self.db.query(BpRecord).count(), 0)
        self.assertEqual(self.db.query(HealthRecord).count(), 0)

    def test_demo_report_counts_historical_medicine_plan(self):
        fill_demo(self.db, self.user)

        report = api.health_report(user=self.user, db=self.db)

        self.assertEqual(len(report.meds), 2)
        self.assertGreaterEqual(report.meds[0].planned, 58)
        self.assertGreaterEqual(report.meds[1].planned, 29)
        self.assertLess(report.meds[0].pct, 100)

    def test_report_recovers_history_from_an_existing_demo_course(self):
        course = MedCourse(user_id=self.user.id, name="Medicine", times=["08:00"])
        self.db.add(course)
        self.db.flush()
        self.db.add(MedIntake(
            course_id=course.id,
            user_id=self.user.id,
            day=user_today(self.user) - timedelta(days=15),
            at_time="08:00",
            taken_at=datetime.now(),
        ))
        self.db.commit()

        report = api.health_report(user=self.user, db=self.db)

        self.assertEqual(report.meds[0].taken, 1)
        self.assertGreaterEqual(report.meds[0].planned, 16)

    def test_onboarding_rejects_invalid_settings_without_recording_consent(self):
        diaries = [HealthSettingDto(diary="bp", enabled=True)]
        # Windows-venv может не содержать tzdata; проверяем сохранение настроек отдельно от её поиска.
        with patch.object(api, "ZoneInfo", return_value=object()):
            with self.assertRaises(HTTPException):
                api.give_consent(ConsentIn(tz="Europe/Moscow", region="несуществующий", diaries=diaries), user=self.user, db=self.db)
            self.assertIsNone(self.user.consent_at)
            self.assertEqual(self.db.query(HealthSetting).count(), 0)

            with self.assertRaises(HTTPException):
                api.give_consent(ConsentIn(tz="Europe/Moscow", region="Владимирская область", diaries=[HealthSettingDto(diary="wrong", enabled=True)]), user=self.user, db=self.db)
            self.assertIsNone(self.user.consent_at)
            self.assertEqual(self.db.query(HealthSetting).count(), 0)

            api.give_consent(ConsentIn(tz="Europe/Moscow", region="Владимирская область", diaries=diaries), user=self.user, db=self.db)
        self.assertIsNotNone(self.user.consent_at)
        self.assertEqual(self.user.region, "Владимирская область")
        self.assertEqual(self.db.query(HealthSetting).count(), 1)

    def test_tz_only_consent_still_supports_existing_api_check(self):
        with patch.object(api, "ZoneInfo", return_value=object()):
            api.give_consent(ConsentIn(tz="Europe/Moscow"), user=self.user, db=self.db)

        self.assertIsNotNone(self.user.consent_at)
        self.assertEqual(self.db.query(HealthSetting).count(), 0)

    def test_pending_profile_is_created_only_after_valid_consent(self):
        pending = PendingUser(
            max_user_id=510002, first_name="Новый", last_name="Пользователь",
            email="user510002@demo.local", avatar_url="", region="Ивановская область",
        )
        profile = api.me(user=pending)
        self.assertEqual(profile.id, 0)
        self.assertIsNone(profile.consent_at)
        self.assertTrue(api.regions(user=pending))
        with self.assertRaises(HTTPException) as denied:
            api.consented_user(user=pending)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(self.db.query(User).count(), 1)

        with self.assertRaises(HTTPException):
            api.give_consent(
                ConsentIn(region="Владимирская область", diaries=[HealthSettingDto(diary="unknown", enabled=True)]),
                user=pending, db=self.db,
            )
        self.assertIsNone(self.db.query(User).filter_by(max_user_id=pending.max_user_id).first())

        created = api.give_consent(
            ConsentIn(region="Владимирская область", diaries=[HealthSettingDto(diary="bp", enabled=True)]),
            user=pending, db=self.db,
        )
        self.assertGreater(created.id, 0)
        self.assertIsNotNone(created.consent_at)
        self.assertEqual(created.region, "Владимирская область")
        self.assertEqual(self.db.query(HealthSetting).filter_by(user_id=created.id).count(), 1)
        self.assertEqual(api.consented_user(user=created), created)

    def test_delete_pending_profile_does_not_create_an_account(self):
        pending = PendingUser(
            max_user_id=510002, first_name="Новый", last_name="Пользователь",
            email="user510002@demo.local", avatar_url="", region="Ивановская область",
        )
        self.assertEqual(api.delete_my_data(user=pending, db=self.db), {"status": "deleted"})
        self.assertIsNone(self.db.query(User).filter_by(max_user_id=pending.max_user_id).first())


if __name__ == "__main__":
    unittest.main()
