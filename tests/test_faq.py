import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.schemas import FaqOut
from server.api.v1.faq import router


CONTENT_PATH = Path(__file__).parents[1] / "content" / "faq.json"


def test_faq_content_matches_schema_and_covers_required_topics():
    payload = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    faq = FaqOut.model_validate(payload)
    assert len(faq.items) >= 15
    assert all(item.order >= 1 and item.category and item.question and item.answer for item in faq.items)
    ids = {item.id for item in faq.items}
    assert {
        "start-route", "future-step-not-current", "booking-vs-visit", "appointment-date",
        "event-vs-notification-time", "local-clinic-setting", "model-data", "delete-data",
    } <= ids
    text = json.dumps(payload, ensure_ascii=False).lower()
    for prohibited in ("часовой пояс", "timezone", "искусственный интеллект", "нейросет", "диагноз", "назначение лечения"):
        assert prohibited not in text


def test_faq_endpoint_is_read_only_and_returns_categories():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.get("/api/v1/faq")

    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert {"id", "category", "question", "answer", "order"} <= body["items"][0].keys()
