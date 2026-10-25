"""Согласованность настроек UI и состава PDF при частичных обновлениях."""

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from reportlab.platypus import Paragraph
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bot.exporter import _build_pdf
from core.db.models import Base, HealthRecord, HealthSetting, User, utcnow
from core.diary_settings import DEFAULT_DIARIES, DIARIES
from core.schemas import HealthSettingDto, HealthSettingsIn
from server import health_pdf
from server.api.v1 import health


class DiarySettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(max_user_id=730001, consent_at=utcnow(), tz="Europe/Moscow")
        self.db.add(self.user)
        self.db.flush()
        at = utcnow() - timedelta(minutes=1)
        for diary, fields in (
            ("bp", {"systolic": 123, "diastolic": 81, "pulse": 72}),
            ("weight", {"weight_kg": 76.5}),
            ("sugar", {"sugar_mmol": 5.6}),
            ("mood", {"mood": "Хорошо", "pain": 2}),
        ):
            self.db.add(HealthRecord(
                user_id=self.user.id, type=diary, at=at,
                note=f"PRIVATE_NOTE_{diary}", **fields,
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_missing_rows_have_same_defaults_in_settings_and_report(self):
        settings = health.health_settings(user=self.user, db=self.db)
        visible = {item.diary: item.enabled for item in settings.diaries}
        self.assertEqual(visible, DEFAULT_DIARIES)
        self.assertEqual(health._get_diary_settings(self.db, self.user.id), visible)
        report = health.health_report(user=self.user, db=self.db)
        self.assertEqual((report.bp_count, report.weight_count, report.sugar_count), (1, 1, 0))
        self.assertNotIn("PRIVATE_NOTE_sugar", [note.note for note in report.notes])
        self.assertEqual(self.db.query(HealthSetting).count(), 0)

    def test_partial_put_preserves_other_diaries_and_reminder_times(self):
        health.update_health_settings(
            HealthSettingsIn(diaries=[
                HealthSettingDto(diary="weight", enabled=False, push_time="08:15"),
                HealthSettingDto(diary="sugar", enabled=True, push_time="12:30"),
                HealthSettingDto(diary="mood", enabled=True, push_time="20:45"),
            ]), user=self.user, db=self.db,
        )
        before = health.health_settings(user=self.user, db=self.db)
        after = health.update_health_settings(
            HealthSettingsIn(diaries=[HealthSettingDto(diary="bp", enabled=False)]),
            user=self.user, db=self.db,
        )
        self.assertEqual(
            [item.model_dump() for item in after.diaries if item.diary != "bp"],
            [item.model_dump() for item in before.diaries if item.diary != "bp"],
        )
        self.assertFalse(health._get_diary_settings(self.db, self.user.id)["bp"])

    def test_web_and_bot_pdf_exclude_disabled_diary_records_and_notes(self):
        for disabled in DIARIES:
            for delivery in ("web", "bot"):
                with self.subTest(disabled=disabled, delivery=delivery):
                    health.update_health_settings(
                        HealthSettingsIn(diaries=[
                            HealthSettingDto(diary=diary, enabled=diary != disabled)
                            for diary in DIARIES
                        ]), user=self.user, db=self.db,
                    )
                    paragraphs = []

                    def capture_paragraph(*args, **kwargs):
                        paragraph = Paragraph(*args, **kwargs)
                        paragraphs.append(paragraph)
                        return paragraph

                    with (
                        patch("server.health_pdf.Paragraph", side_effect=capture_paragraph),
                        patch("server.health_pdf._record_line", wraps=health_pdf._record_line) as record_line,
                    ):
                        if delivery == "web":
                            response = health.export_health_pdf_impl(
                                SimpleNamespace(headers={}), None, self.db,
                                auth_fn=lambda *args, **kwargs: self.user,
                            )
                            pdf = response.body
                        else:
                            pdf, _ = _build_pdf(self.db, self.user)

                    self.assertTrue(pdf.startswith(b"%PDF"))
                    text = "\n".join(paragraph.getPlainText() for paragraph in paragraphs)
                    self.assertNotIn(f"PRIVATE_NOTE_{disabled}", text)
                    rendered_diaries = {call.args[0].type for call in record_line.call_args_list}
                    self.assertEqual(rendered_diaries, set(("bp", "weight", "sugar")) - {disabled})
                    for diary, heading in (
                        ("bp", "Давление:"), ("weight", "Вес:"), ("sugar", "Сахар крови:"),
                    ):
                        if diary == disabled:
                            self.assertNotIn(heading, text)
                        else:
                            self.assertIn(heading, text)
                    if disabled != "mood":
                        self.assertIn("PRIVATE_NOTE_mood", text)

    def test_disabling_all_diaries_removes_all_diary_data_from_report(self):
        health.update_health_settings(
            HealthSettingsIn(diaries=[
                HealthSettingDto(diary=diary, enabled=False) for diary in DIARIES
            ]), user=self.user, db=self.db,
        )
        report = health.health_report(user=self.user, db=self.db)
        self.assertEqual((report.bp_count, report.weight_count, report.sugar_count), (0, 0, 0))
        self.assertIsNone(report.bp_avg)
        self.assertIsNone(report.weight_latest)
        self.assertIsNone(report.sugar_avg)
        self.assertEqual(report.notes, [])
        self.assertEqual(self.db.query(HealthRecord).count(), 4)


if __name__ == "__main__":
    unittest.main()
