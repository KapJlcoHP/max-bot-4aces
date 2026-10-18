"""Новая запись: UTC в БД, время пользователя в API, таблицах и заметках PDF."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from reportlab.platypus import Paragraph
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import Base, HealthRecord, User
from core.schemas import HealthAddIn
from core.time import report_window
from server import health_pdf
from server.api.v1 import health


class HealthTimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=750001, consent_at=datetime(2026, 1, 1))
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def render_pdf(self, report):
        paragraphs, table_rows = [], []
        original_record_line = health_pdf._record_line

        def capture_paragraph(*args, **kwargs):
            paragraph = Paragraph(*args, **kwargs)
            paragraphs.append(paragraph)
            return paragraph

        def capture_record_line(*args, **kwargs):
            row = original_record_line(*args, **kwargs)
            table_rows.append(row)
            return row

        with (
            patch("server.health_pdf.Paragraph", side_effect=capture_paragraph),
            patch("server.health_pdf._record_line", side_effect=capture_record_line),
        ):
            pdf = health_pdf.build_health_pdf(
                self.db, self.user, report, health._get_diary_settings(self.db, self.user.id),
            )
        self.assertTrue(pdf.startswith(b"%PDF"))
        return "\n".join(p.getPlainText() for p in paragraphs), table_rows

    def test_fresh_measurement_keeps_real_time_in_api_and_pdf(self):
        measured_at = datetime(2026, 10, 17, 21, 15)
        for tz, expected_iso, expected_pdf in (
            ("Europe/Moscow", "2026-10-18T00:15:00+03:00", "18.10.2026 00:15"),
            ("Asia/Irkutsk", "2026-10-18T05:15:00+08:00", "18.10.2026 05:15"),
            ("America/New_York", "2026-10-17T17:15:00-04:00", "17.10.2026 17:15"),
        ):
            with self.subTest(tz=tz):
                self.db.query(HealthRecord).delete()
                self.user.tz = tz
                self.db.commit()
                with patch("core.services.utcnow", return_value=measured_at):
                    created = health.add_health_record(
                        "bp", HealthAddIn(systolic=123, diastolic=81, pulse=72, note="Свежая запись"),
                        user=self.user, db=self.db,
                    )
                stored = self.db.query(HealthRecord).one()
                self.assertEqual(stored.at, measured_at)
                self.assertIsNone(stored.at.tzinfo)
                self.assertEqual(created.at.isoformat(), expected_iso)
                listed = health.health_records("bp", limit=100, user=self.user, db=self.db)
                self.assertEqual(listed[0].at.isoformat(), expected_iso)

                report = health.health_report_impl(self.user, self.db, now_fn=lambda: measured_at)
                self.assertEqual(report.bp_count, 1)
                self.assertEqual(report.notes[0].at.isoformat(), expected_iso)
                text, table_rows = self.render_pdf(report)
                self.assertEqual(len(table_rows), 1)
                self.assertEqual(table_rows[0][0], expected_pdf)
                self.assertIn(f"{expected_pdf} — «Свежая запись»", text)
                self.assertIn(f"Сформировано {expected_pdf}", text)

    def test_pdf_graph_groups_measurements_by_users_local_day(self):
        rows = [
            HealthRecord(at=datetime(2026, 10, 17, 20, 30), systolic=120),
            HealthRecord(at=datetime(2026, 10, 17, 21, 30), systolic=140),
        ]
        labels, values = health_pdf._daily_averages(rows, lambda row: row.systolic, "Europe/Moscow")
        self.assertEqual(labels, ["17.10", "18.10"])
        self.assertEqual(values, [120, 140])

    def test_report_and_pdf_share_utc_window_across_daylight_saving_change(self):
        self.user.tz = "America/New_York"
        now = datetime(2026, 11, 2, 12)  # 07:00 EST; 30 дней назад — 07:00 EDT.
        start, end, local_start, local_end = report_window(now, self.user.tz)
        self.assertEqual(start, datetime(2026, 10, 3, 11))
        self.assertEqual(end, now)
        self.assertEqual(local_start.isoformat(), "2026-10-03T07:00:00-04:00")
        self.assertEqual(local_end.isoformat(), "2026-11-02T07:00:00-05:00")
        for at, note in (
            (start - timedelta(seconds=1), "OUTSIDE_OLD"),
            (start, "AT_START"),
            (end, "AT_END"),
            (end + timedelta(seconds=1), "OUTSIDE_FUTURE"),
        ):
            self.db.add(HealthRecord(
                user_id=self.user.id, type="bp", at=at,
                systolic=120, diastolic=80, pulse=70, note=note,
            ))
        self.db.commit()
        report = health.health_report_impl(self.user, self.db, now_fn=lambda: now)
        self.assertEqual(report.bp_count, 2)
        self.assertEqual({note.note for note in report.notes}, {"AT_START", "AT_END"})
        text, table_rows = self.render_pdf(report)
        self.assertEqual({row[0] for row in table_rows}, {"03.10.2026 07:00", "02.11.2026 07:00"})
        self.assertNotIn("OUTSIDE_OLD", text)
        self.assertNotIn("OUTSIDE_FUTURE", text)
        self.assertIn("Период: 03.10.2026 — 02.11.2026", text)

    def test_report_and_pdf_include_structured_mood_without_note(self):
        now = datetime(2026, 10, 18, 12)
        self.db.add_all([
            HealthRecord(
                user_id=self.user.id, type="mood", at=datetime(2026, 10, 17, 9),
                mood="Хорошо", pain=3,
            ),
            HealthRecord(
                user_id=self.user.id, type="mood", at=datetime(2026, 10, 16, 9),
                mood=None, pain=0, note="",
            ),
            HealthRecord(
                user_id=self.user.id, type="mood", at=datetime(2026, 10, 15, 9),
                mood=None, pain=None, note="",
            ),
        ])
        self.db.commit()

        report = health.health_report_impl(self.user, self.db, now_fn=lambda: now)

        self.assertEqual(len(report.notes), 2)
        self.assertIn("Самочувствие: Хорошо", report.notes[0].note)
        self.assertIn("боль 3/10", report.notes[0].note)
        self.assertIn("боль 0/10", report.notes[1].note)
        text, _ = self.render_pdf(report)
        self.assertIn("Самочувствие: Хорошо", text)
        self.assertIn("боль 3/10", text)
        self.assertIn("боль 0/10", text)
        self.assertNotIn("дневники пусты", text)


if __name__ == "__main__":
    unittest.main()
