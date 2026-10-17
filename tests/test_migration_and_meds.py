"""Проверки переноса данных и локальной даты приёма лекарств."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, BpRecord, HealthRecord, MedCourse, MedIntake, User
from core.db.session import _migrate_bp_records
from core.services import take_med, user_today
from core.time import normalize_clock_time
from core.schemas import MedAddIn
from server.api.v1 import meds as meds_api


class MigrationTests(unittest.TestCase):
    def test_legacy_bp_rows_are_added_to_nonempty_diary_once(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        measured_at = datetime(2026, 9, 1, 8)
        with Session(engine) as db:
            db.add(User(max_user_id=101))
            db.flush()
            db.add_all([
                BpRecord(user_id=1, at=measured_at, systolic=120, diastolic=80, pulse=70),
                BpRecord(user_id=1, at=measured_at, systolic=120, diastolic=80, pulse=70),
                HealthRecord(user_id=1, type="bp", at=measured_at, systolic=120, diastolic=80, pulse=70),
                HealthRecord(user_id=1, type="weight", at=measured_at, weight_kg=75),
            ])
            db.commit()

        with patch("core.db.session.engine", engine):
            _migrate_bp_records()
            _migrate_bp_records()
        with Session(engine) as db:
            self.assertEqual(db.query(HealthRecord).filter(HealthRecord.type == "bp").count(), 2)
            db.delete(db.query(HealthRecord).filter(HealthRecord.type == "bp").first())
            db.commit()
        with patch("core.db.session.engine", engine):
            _migrate_bp_records()
        with Session(engine) as db:
            self.assertEqual(db.query(HealthRecord).filter(HealthRecord.type == "bp").count(), 1)
        engine.dispose()


class MedicineDateTests(unittest.TestCase):
    def test_medication_times_are_normalized_to_canonical_minutes(self):
        self.assertEqual(normalize_clock_time("8:00"), "08:00")
        self.assertEqual(normalize_clock_time("08:00"), "08:00")
        self.assertEqual(normalize_clock_time("08:00:00"), "08:00")
        self.assertIsNone(normalize_clock_time("08:00:01"))
        self.assertIsNone(normalize_clock_time("25:00"))

    def test_intake_uses_users_date_around_utc_midnight(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(max_user_id=201, tz="Asia/Irkutsk")
            db.add(user)
            db.flush()
            course = MedCourse(user_id=user.id, name="Medicine", times=["08:00"])
            db.add(course)
            db.commit()

            instant = datetime(2026, 9, 28, 18, tzinfo=timezone.utc)
            irkutsk = timezone(timedelta(hours=8))
            with patch("core.services.ZoneInfo", return_value=irkutsk):
                self.assertEqual(str(user_today(user, instant)), "2026-09-29")
            with patch("core.services.ZoneInfo", return_value=irkutsk), patch("core.services.utcnow", return_value=instant):
                intake = take_med(db, user.id, course.id, "08:00")
            self.assertEqual(str(intake.day), "2026-09-29")
            self.assertEqual(db.query(MedIntake).count(), 1)
        engine.dispose()

    def test_api_normalizes_new_and_legacy_medication_times(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(max_user_id=202, consent_at=datetime(2026, 1, 1))
            db.add(user)
            db.flush()

            result = meds_api.add_med(
                MedAddIn(name="Препарат", times=["8:00", "08:00:00", "20:00"]),
                user=user,
                db=db,
            )
            self.assertEqual(result.courses[0].times, ["08:00", "20:00"])
            stored = db.query(MedCourse).filter_by(user_id=user.id).one()
            self.assertEqual(stored.times, ["08:00", "20:00"])

            legacy = MedCourse(user_id=user.id, name="Старый курс", times=["8:00"])
            db.add(legacy)
            db.commit()
            legacy_result = meds_api._meds_out(db, user)
            legacy_dto = next(course for course in legacy_result.courses if course.id == legacy.id)
            self.assertEqual(legacy_dto.times, ["08:00"])

        engine.dispose()


if __name__ == "__main__":
    unittest.main()
