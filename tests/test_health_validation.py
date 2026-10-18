"""Границы серверной валидации совпадают с формой дневника (P0-4)."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, HealthRecord, User
from core.schemas import HealthAddIn
from core.services import ServiceError, add_health_record


class HealthValidationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=740001)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_accepts_inclusive_boundaries_from_frontend(self):
        for diary, fields in (
            ("bp", {"systolic": 50, "diastolic": 30, "pulse": 25}),
            ("bp", {"systolic": 260, "diastolic": 150, "pulse": 220}),
            ("bp", {"systolic": 120, "diastolic": 80}),
            ("weight", {"weight_kg": 20}),
            ("weight", {"weight_kg": 300}),
            ("weight", {"weight_kg": 76.5}),
            ("sugar", {"sugar_mmol": 1}),
            ("sugar", {"sugar_mmol": 35}),
            ("sugar", {"sugar_mmol": 5.6}),
            ("mood", {"mood": "Хорошо", "pain": 0}),
            ("mood", {"mood": "Хорошо"}),
        ):
            with self.subTest(diary=diary, fields=fields):
                row = add_health_record(self.db, self.user.id, diary, **fields)
                for key, value in fields.items():
                    self.assertEqual(getattr(row, key), value)

    def test_mood_payload_defaults_leave_pain_missing(self):
        self.assertIsNone(HealthAddIn(mood="Хорошо").pain)
        self.assertEqual(HealthAddIn(mood="Хорошо", pain=0).pain, 0)

    def test_rejects_missing_out_of_range_and_nonfinite_values_without_saving(self):
        invalid = [
            ("bp", {}),
            ("bp", {"systolic": 999, "diastolic": 0}),
            ("bp", {"systolic": 49, "diastolic": 30}),
            ("bp", {"systolic": 261, "diastolic": 80}),
            ("bp", {"systolic": 120, "diastolic": 29}),
            ("bp", {"systolic": 200, "diastolic": 151}),
            ("bp", {"systolic": 120, "diastolic": 80, "pulse": 24}),
            ("bp", {"systolic": 120, "diastolic": 80, "pulse": 221}),
            ("bp", {"systolic": 80, "diastolic": 80}),
            ("bp", {"systolic": 80, "diastolic": 90}),
            ("weight", {}),
            ("weight", {"weight_kg": 19.9}),
            ("weight", {"weight_kg": 300.1}),
            ("sugar", {}),
            ("sugar", {"sugar_mmol": 0.9}),
            ("sugar", {"sugar_mmol": 35.1}),
        ]
        for value in (float("nan"), float("inf"), float("-inf")):
            invalid.extend((
                ("bp", {"systolic": value, "diastolic": 80}),
                ("bp", {"systolic": 120, "diastolic": value}),
                ("bp", {"systolic": 120, "diastolic": 80, "pulse": value}),
                ("weight", {"weight_kg": value}),
                ("sugar", {"sugar_mmol": value}),
                ("mood", {"mood": "Хорошо", "pain": value}),
            ))
        for diary, fields in invalid:
            with self.subTest(diary=diary, fields=fields):
                with self.assertRaises(ServiceError):
                    add_health_record(self.db, self.user.id, diary, **fields)
                self.assertEqual(self.db.query(HealthRecord).count(), 0)


if __name__ == "__main__":
    unittest.main()
