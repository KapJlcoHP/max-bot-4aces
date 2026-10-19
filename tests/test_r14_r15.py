"""Regression and integration coverage for the local R14/R15 acceptance slice."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bot import exporter
from core.db.models import Base, ExportRequest, HealthRecord, MedCourse, MedIntake, User
from core.schemas import HealthReportOut, MedIntakeToggleIn
from server import health_pdf
from server.api.v1 import health, meds


def test_bp_chart_survives_a_missing_pulse_value():
    rows = [
        HealthRecord(type="bp", at=datetime(2026, 10, 1), systolic=120, diastolic=80, pulse=None),
        HealthRecord(type="bp", at=datetime(2026, 10, 2), systolic=124, diastolic=82, pulse=70),
    ]

    assert health_pdf._bp_chart(rows, "UTC") is not None
    # One pulse point is not enough for a pulse line, but it must not remove
    # the pressure line from the PDF.
    assert health_pdf._pulse_chart(rows, "UTC") is None


def test_pressure_and_pulse_keep_separate_units_in_reportlab_series_and_pdf():
    rows = [
        HealthRecord(type="bp", at=datetime(2026, 10, 1), systolic=120, diastolic=80, pulse=70),
        HealthRecord(type="bp", at=datetime(2026, 10, 2), systolic=124, diastolic=82, pulse=72),
    ]

    with patch.object(health_pdf, "_line_chart", wraps=health_pdf._line_chart) as line_chart:
        health_pdf._bp_chart(rows, "UTC")
        health_pdf._pulse_chart(rows, "UTC")

    pressure_legend = [label for _, label in line_chart.call_args_list[0].kwargs["legend_items"]]
    pulse_legend = [label for _, label in line_chart.call_args_list[1].kwargs["legend_items"]]
    assert all("мм рт. ст." in label for label in pressure_legend)
    assert all("уд/мин" not in label for label in pressure_legend)
    assert pulse_legend == ["пульс, уд/мин"]

    _, record_text = health_pdf._record_line(rows[0], "UTC")
    assert "120/80 мм рт. ст." in record_text
    assert "пульс 70 уд/мин" in record_text

    paragraphs = []
    from reportlab.platypus import Paragraph

    def capture_paragraph(*args, **kwargs):
        paragraph = Paragraph(*args, **kwargs)
        paragraphs.append(paragraph)
        return paragraph

    report = HealthReportOut(bp_avg="122/81", bp_count=2, pulse_avg=71)
    user = User(max_user_id=941401, first_name="Тест")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db, patch("server.health_pdf.Paragraph", side_effect=capture_paragraph):
        data = health_pdf.build_health_pdf(db, user, report, {})
    engine.dispose()

    assert data.startswith(b"%PDF")
    text = "\n".join(paragraph.getPlainText() for paragraph in paragraphs)
    assert "122/81 мм рт. ст." in text
    assert "пульс ~71 уд/мин" in text


@pytest.fixture
def medication_store(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'r15-medication.sqlite'}",
        connect_args={"timeout": 10, "check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(max_user_id=941402, tz="UTC", consent_at=datetime(2026, 1, 1))
        db.add(user)
        db.flush()
        course = MedCourse(user_id=user.id, name="Курс", times=["08:00", "20:00"])
        db.add(course)
        db.commit()
        ids = user.id, course.id
    yield engine, sessions, ids
    engine.dispose()


def test_concurrent_medication_marks_preserve_both_slots(medication_store):
    _, sessions, (user_id, course_id) = medication_store
    from threading import Barrier

    start = Barrier(2)

    def mark(at_time):
        start.wait(timeout=5)
        with sessions() as db:
            user = db.get(User, user_id)
            return meds.toggle_intake(
                course_id, MedIntakeToggleIn(at_time=at_time), user=user, db=db,
            ).at_time

    with ThreadPoolExecutor(max_workers=2) as pool:
        marked = sorted(pool.map(mark, ("08:00", "20:00")))

    assert marked == ["08:00", "20:00"]
    with sessions() as db:
        assert [row.at_time for row in db.query(MedIntake).order_by(MedIntake.at_time)] == ["08:00", "20:00"]


def test_pdf_fallback_does_not_turn_a_queued_request_into_sent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(max_user_id=941403, consent_at=datetime(2026, 1, 1))
        db.add(user)
        db.flush()
        request = ExportRequest(user_id=user.id)
        db.add(request)
        db.commit()
        response = health.export_health_pdf_impl(
            SimpleNamespace(headers={}), None, db,
            auth_fn=lambda *args, **kwargs: user,
            report_fn=lambda **kwargs: HealthReportOut(),
            diary_settings_fn=lambda *args: {},
            pdf_builder=lambda *args: b"%PDF-fallback",
        )
        db.refresh(request)
        assert response.body == b"%PDF-fallback"
        assert (request.status, request.sent_at) == ("queued", None)
    engine.dispose()


def test_cancelled_export_worker_never_marks_processing_request_sent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(max_user_id=941404, consent_at=datetime(2026, 1, 1))
        db.add(user)
        db.flush()
        db.add(ExportRequest(user_id=user.id))
        db.commit()

    async def cancelled_send(*args):
        raise asyncio.CancelledError()

    async def stop_sleep(_):
        raise asyncio.CancelledError()

    async def run_worker():
        with (
            patch.object(exporter, "SessionLocal", sessions),
            patch.object(exporter, "send_health_pdf", side_effect=cancelled_send),
            patch.object(exporter.asyncio, "sleep", side_effect=stop_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await exporter.export_watcher_loop(object())

    asyncio.run(run_worker())

    with sessions() as db:
        row = db.query(ExportRequest).one()
        assert row.status == "processing"
        assert row.sent_at is None
    engine.dispose()
