"""Смоук REST API после рефакторинга на core/services (TestClient, без живого сервера).

Запуск из корня zabota:  DEV_BYPASS_AUTH=true .venv/Scripts/python.exe scripts/smoke_api.py
Временная SQLite-БД, сервер не поднимается.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite:///./database/_smoke_api.db"
os.environ["DEV_BYPASS_AUTH"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from core.db.session import init_db  # noqa: E402
from server.main import app  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        sys.exit(1)
    PASS += 1


def main() -> None:
    db_file = Path("database/_smoke_api.db")
    if db_file.exists():
        db_file.unlink()
    init_db()

    with TestClient(app) as client:
        r = client.post("/api/v1/me/consent", json={"tz": "Asia/Irkutsk"})
        check("consent 200 + tz сохранён", r.status_code == 200 and r.json()["tz"] == "Asia/Irkutsk", r.text)
        r = client.post("/api/v1/me/consent", json={"tz": "Mars/Olympus"})
        check("незнакомая зона не сохраняется", r.json()["tz"] == "Asia/Irkutsk", r.text)

        r = client.post("/api/v1/route/start", json={"situation_key": "dispanserizaciya"})
        if r.status_code != 200:
            r2 = client.get("/api/v1/catalog")
            catalog = r2.json()
            situations = catalog.get("situations") if isinstance(catalog, dict) else catalog
            keys = [s["key"] for s in situations]
            r = client.post("/api/v1/route/start", json={"situation_key": keys[0]})
        check("маршрут запущен", r.status_code == 200, r.text)
        route = r.json()
        step = next(s for s in route["steps"] if s["status"] == "current")

        r = client.post(f"/api/v1/route/steps/{step['id']}/complete")
        check("complete шага", r.status_code == 200, r.text)
        check("следующий шаг current", r.json()["next_step"] is not None)

        r = client.post(f"/api/v1/route/steps/{step['id']}/complete")
        check("повтор complete → 409", r.status_code == 409, r.text)

        r = client.post("/api/v1/reminders", json={"title": "Тест", "at": "2026-10-01T14:00:00"})
        check("напоминание создано", r.status_code == 200, r.text)
        rid = r.json()["id"]
        r = client.post(f"/api/v1/reminders/{rid}/toggle")
        check("toggle", r.status_code == 200)

        r = client.post("/api/v1/health/bp", json={"systolic": 122, "diastolic": 81, "pulse": 68})
        check("запись АД", r.status_code == 200, r.text)
        r = client.post("/api/v1/health/bp", json={"systolic": 999, "diastolic": 81})
        check("невалидное АД → 422", r.status_code == 422, r.text)

        r = client.get("/api/v1/health/settings")
        check("health/settings GET", r.status_code == 200 and "push_time" in r.json()["diaries"][0], r.text)
        r = client.put("/api/v1/health/settings", json={"diaries": [{"diary": "bp", "enabled": True, "push_time": "08:30"}]})
        check("push_time сохраняется", r.json()["diaries"][0]["push_time"] == "08:30", r.text)
        r = client.put("/api/v1/health/settings", json={"diaries": [{"diary": "bp", "enabled": True, "push_time": None}]})
        check("push_time=None сбрасывает", r.json()["diaries"][0]["push_time"] is None, r.text)
        r = client.put("/api/v1/health/settings", json={"diaries": [{"diary": "bp", "enabled": True, "push_time": "не время"}]})
        check("плохое время → 422", r.status_code == 422, r.text)

        r = client.post("/api/v1/meds", json={"name": "Магний B6", "times": ["09:00"]})
        check("курс создан", r.status_code == 200, r.text)
        course_id = r.json()["courses"][-1]["id"]
        r = client.post(f"/api/v1/meds/{course_id}/intake-toggle", json={"at_time": "09:00"})
        check("приём отмечен", r.json()["taken"] is True, r.text)
        r = client.post(f"/api/v1/meds/{course_id}/intake-toggle", json={"at_time": "09:00"})
        check("toggle снимает приём", r.json()["taken"] is False, r.text)

        r = client.get("/api/v1/health/report")
        check("сводка", r.status_code == 200 and r.json()["bp_count"] >= 1, r.text)

        # экспорт PDF: initData-путь и путь токена
        r = client.get("/api/v1/health/export")
        check("PDF по initData", r.status_code == 200 and r.headers["content-type"] == "application/pdf", str(r.status_code))
        r = client.post("/api/v1/health/export-token")
        check("токен экспорта выдан", r.status_code == 200 and r.json().get("token"), r.text)
        token = r.json()["token"]
        r = client.get(f"/api/v1/health/export?t={token}")
        check("PDF по токену", r.status_code == 200 and r.content[:4] == b"%PDF", str(r.status_code))
        r = client.get(f"/api/v1/health/export?t={token}")
        check("токен одноразовый → 401", r.status_code == 401, str(r.status_code))
        r = client.get("/api/v1/health/export?t=deadbeef")
        check("мусорный токен → 401", r.status_code == 401, str(r.status_code))

        # PDF через бота: заявка кладётся в export_requests, бот-вотчер её заберёт
        r = client.post("/api/v1/health/send-to-bot")
        check("заявка PDF в чат принята", r.status_code == 200 and r.json()["status"] == "queued", r.text)
        from core.db.models import ExportRequest

        with_session = None
        from core.db.session import SessionLocal

        with SessionLocal() as s:
            pending = s.query(ExportRequest).filter(ExportRequest.sent_at.is_(None)).count()
        check("заявка в очереди", pending >= 1, str(pending))

    print(f"\nВсе проверки пройдены: {PASS}")


if __name__ == "__main__":
    main()
