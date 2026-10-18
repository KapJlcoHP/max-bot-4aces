"""Регрессии удаления данных, демо-сводки и первого входа."""

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.demo import fill_demo, has_any_data, is_demo_data
from core.db.models import (
    Base, BpRecord, FamilyMember, HealthRecord, HealthSetting, MedCourse,
    MedIntake, User,
)
from core.schemas import ConsentIn, HealthSettingDto, HealthSettingsIn, ReminderAddIn
from core.services import user_today
from server.deps import PendingUser
from server.api.v1 import health as health_api, meds as meds_api


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

    def test_completed_medication_stays_in_history_but_not_today_schedule(self):
        course = MedCourse(
            user_id=self.user.id,
            name="Исторический курс",
            times=["10:00"],
            created_at=datetime(2026, 9, 28, 8),
        )
        self.db.add(course)
        self.db.flush()
        self.db.add(MedIntake(
            course_id=course.id, user_id=self.user.id,
            day=datetime(2026, 9, 29).date(), at_time="10:00",
            taken_at=datetime(2026, 9, 29, 10),
        ))
        self.db.commit()

        result = meds_api.disable_med(course.id, user=self.user, db=self.db)

        returned = next(row for row in result.courses if row.id == course.id)
        self.assertFalse(returned.enabled)
        self.assertEqual(result.today, [])

        report = health_api.health_report_impl(
            self.user, self.db, now_fn=lambda: datetime(2026, 9, 30, 12)
        )
        history = next(row for row in report.meds if row.name == course.name)
        self.assertEqual((history.taken, history.planned), (1, 3))

    def test_demo_reuses_onboarding_settings_and_is_safe_to_repeat(self):
        consent_at = datetime(2026, 10, 1, 12, 30)
        self.user.consent_at = consent_at
        self.user.region = "Владимирская область"
        self.db.add(HealthSetting(
            user_id=self.user.id,
            diary="bp",
            enabled=False,
            push_time=None,
        ))
        self.db.commit()
        account_id = self.user.id

        # После согласия настройки дневников уже есть, но контент аккаунта пуст.
        self.assertFalse(has_any_data(self.db, account_id))
        fill_demo(self.db, self.user)
        first_counts = (
            self.db.query(HealthRecord).filter_by(user_id=account_id).count(),
            self.db.query(MedCourse).filter_by(user_id=account_id).count(),
        )
        self.assertTrue(is_demo_data(self.db, account_id))

        # Повторный запуск не конфликтует с uq_health_settings_user_diary и не
        # плодит демо-контент: уже готовый набор обрабатывается как no-op.
        fill_demo(self.db, self.user)
        second_counts = (
            self.db.query(HealthRecord).filter_by(user_id=account_id).count(),
            self.db.query(MedCourse).filter_by(user_id=account_id).count(),
        )

        self.db.refresh(self.user)
        self.assertEqual(self.user.id, account_id)
        self.assertEqual(self.user.consent_at, consent_at)
        self.assertEqual(self.user.region, "Владимирская область")
        self.assertTrue(is_demo_data(self.db, account_id))
        self.assertEqual(self.db.query(HealthSetting).filter_by(user_id=account_id).count(), 4)
        self.assertEqual(first_counts, second_counts)
        self.assertFalse(self.db.query(HealthSetting).filter_by(
            user_id=account_id, diary="bp", enabled=True,
        ).count())

    def test_demo_does_not_replace_user_data_after_demo(self):
        fill_demo(self.db, self.user)
        custom_record = HealthRecord(
            user_id=self.user.id, type="mood", at=datetime(2026, 10, 11, 9),
            mood="Хорошо", note="Добавлено пользователем после демо",
        )
        family = FamilyMember(owner_id=self.user.id, name="Помощник", role="Родственник")
        self.db.add_all([custom_record, family])
        self.db.commit()

        with self.assertRaises(ValueError):
            fill_demo(self.db, self.user)

        self.assertEqual(self.db.query(HealthRecord).filter_by(note=custom_record.note).count(), 1)
        self.assertEqual(self.db.query(FamilyMember).filter_by(name="Помощник").count(), 1)

    def test_demo_rolls_back_partial_failure(self):
        import core.db.demo as demo_module

        self.user.region = "Ивановская область"
        self.db.add(HealthSetting(user_id=self.user.id, diary="bp", enabled=False))
        self.db.commit()

        with patch.object(demo_module, "build_route_for", side_effect=RuntimeError("seed failed")):
            with self.assertRaises(RuntimeError):
                fill_demo(self.db, self.user)

        self.assertEqual(self.db.query(demo_module.Route).filter_by(user_id=self.user.id).count(), 0)
        self.assertEqual(self.db.query(HealthRecord).filter_by(user_id=self.user.id).count(), 0)
        self.assertEqual(self.db.query(HealthSetting).filter_by(user_id=self.user.id).count(), 1)

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

    def test_diary_defaults_and_put_share_one_source(self):
        initial = api.health_settings(user=self.user, db=self.db)
        self.assertEqual(
            [(d.diary, d.enabled, d.push_time) for d in initial.diaries],
            [("bp", True, None), ("weight", True, None), ("sugar", False, None), ("mood", True, None)],
        )
        self.assertEqual(api._get_diary_settings(self.db, self.user.id), {d.diary: d.enabled for d in initial.diaries})

        api.update_health_settings(
            HealthSettingsIn(diaries=[HealthSettingDto(diary="bp", enabled=False, push_time="09:30")]),
            user=self.user,
            db=self.db,
        )
        current = api.health_settings(user=self.user, db=self.db)
        self.assertEqual((current.diaries[0].enabled, current.diaries[0].push_time), (False, "09:30"))
        self.assertFalse(api._get_diary_settings(self.db, self.user.id)["bp"])

    def test_reminder_datetime_is_stored_utc_and_returned_in_user_zone(self):
        self.user.tz = "Asia/Irkutsk"
        self.db.commit()
        returned = api.add_reminder(
            ReminderAddIn(title="Визит", at="2026-09-29T10:00", place="Клиника"),
            user=self.user,
            db=self.db,
        )
        row = self.db.query(api.Reminder).one()
        self.assertEqual(row.at, datetime(2026, 9, 29, 2))
        self.assertEqual(returned.at.isoformat(), "2026-09-29T10:00:00+08:00")

    def test_reminder_requires_an_explicit_time_instead_of_defaulting_to_tomorrow(self):
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ReminderAddIn.model_validate({"title": "Не создавать без даты"})
        self.assertEqual(self.db.query(api.Reminder).count(), 0)

    def test_reminder_rejects_profile_dst_gap_and_ambiguous_wall_time(self):
        self.user.tz = "America/New_York"
        self.db.commit()
        for value in ("2030-03-10T02:30", "2030-11-03T01:30"):
            with self.subTest(value=value), self.assertRaises(HTTPException) as error:
                api.add_reminder(
                    ReminderAddIn(title="DST", at=value), user=self.user, db=self.db
                )
            self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.db.query(api.Reminder).count(), 0)

    def test_reminder_request_rejects_invalid_payloads(self):
        from pydantic import ValidationError

        for payload in (
            {},
            {"title": ""},
            {"title": "Визит", "at": "not-a-date"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ReminderAddIn.model_validate(payload)

    def test_report_window_uses_user_local_calendar(self):
        self.user.tz = "Asia/Tokyo"
        self.db.add(HealthSetting(user_id=self.user.id, diary="weight", enabled=True))
        self.db.add_all([
            HealthRecord(user_id=self.user.id, type="weight", at=datetime(2026, 8, 31, 16, 30), weight_kg=70),
            HealthRecord(user_id=self.user.id, type="weight", at=datetime(2026, 8, 31, 15, 30), weight_kg=60),
        ])
        self.db.commit()
        with patch.object(api, "utcnow", return_value=datetime(2026, 9, 30, 16, tzinfo=timezone.utc)):
            report = api.health_report(user=self.user, db=self.db)
        self.assertEqual(report.weight_count, 1)

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
