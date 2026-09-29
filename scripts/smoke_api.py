"""Смоук основного сценария REST API (TestClient, без живого сервера).

Установить зависимости: python -m pip install -r requirements-smoke.txt
Запуск из корня проекта: python scripts/smoke_api.py
Скрипт сам включает dev-доступ и использует отдельную database/_smoke_api.db.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite:///./database/_smoke_api.db"
os.environ["DEV_BYPASS_AUTH"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from core.db.models import ExportRequest, User  # noqa: E402
from core.db.session import SessionLocal, init_db  # noqa: E402
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
        r = client.get("/api/v1/me")
        check("до согласия временный профиль", r.status_code == 200 and r.json()["id"] == 0 and r.json()["consent_at"] is None, r.text)
        with SessionLocal() as db:
            check("первый GET /me не создаёт аккаунт", db.query(User).count() == 0)
        r = client.get("/api/v1/regions")
        check("регионы доступны до согласия", r.status_code == 200 and len(r.json()) == 3 and r.json()[0]["pilot"], r.text)
        r = client.get("/api/v1/route")
        check("маршрут до согласия закрыт", r.status_code == 403, r.text)

        r = client.post("/api/v1/me/consent", json={
            "tz": "Asia/Irkutsk",
            "region": "Владимирская область",
            "diaries": [{"diary": "bp", "enabled": True}],
        })
        check("согласие, регион и часовой пояс сохранены", r.status_code == 200 and r.json()["id"] > 0 and r.json()["consent_at"] is not None and r.json()["tz"] == "Asia/Irkutsk" and r.json()["region"] == "Владимирская область", r.text)
        r = client.post("/api/v1/me/consent", json={"tz": "Mars/Olympus"})
        check("неизвестный часовой пояс → 422", r.status_code == 422, r.text)
        r = client.get("/api/v1/me")
        check("после ошибки часовой пояс не изменился", r.status_code == 200 and r.json()["tz"] == "Asia/Irkutsk", r.text)

        r = client.post("/api/v1/route/start", json={"situation_key": "chronic"})
        check("маршрут запущен", r.status_code == 200, r.text)
        route = r.json()
        step = next(s for s in route["steps"] if s["status"] == "current")
        check(
            "новый маршрут без выполненных шагов",
            route["done_steps"] == 0 and route["steps"][0]["status"] == "current",
            r.text,
        )

        r = client.post(f"/api/v1/route/steps/{step['id']}/complete")
        check("complete шага", r.status_code == 200, r.text)
        check("следующий шаг current", r.json()["next_step"] is not None)

        r = client.post(f"/api/v1/route/steps/{step['id']}/complete")
        check("повтор complete → 409", r.status_code == 409, r.text)

        r = client.post(f"/api/v1/route/steps/{step['id']}/uncomplete")
        step_after = next((s for s in r.json()["steps"] if s["id"] == step["id"]), None)
        check("uncomplete возвращает шаг в текущие", r.status_code == 200 and step_after and step_after["status"] == "current", r.text)
        r = client.post(f"/api/v1/route/steps/{step['id']}/uncomplete")
        check("uncomplete невыполненного → 409", r.status_code == 409, r.text)

        r = client.patch(f"/api/v1/route/steps/{step['id']}", json={"deadline": "2026-10-15"})
        check("срок шага изменён", r.status_code == 200 and r.json()["deadline"] == "2026-10-15", r.text)
        r = client.patch(f"/api/v1/route/steps/{step['id']}", json={"deadline": None})
        check("срок шага сброшен", r.status_code == 200 and r.json()["deadline"] is None, r.text)
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
        check(
            "настройки дневников сохранены при согласии",
            r.status_code == 200 and len(r.json()["diaries"]) == 4 and r.json()["diaries"][0]["diary"] == "bp" and r.json()["diaries"][0]["enabled"] and all(not d["enabled"] for d in r.json()["diaries"][1:]),
            r.text,
        )
        r = client.put("/api/v1/health/settings", json={"diaries": [{"diary": "bp", "enabled": True, "push_time": "08:30"}]})
        check("health/settings PUT", r.status_code == 200 and r.json()["diaries"][0]["diary"] == "bp", r.text)
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

        r = client.patch("/api/v1/me/settings", json={"region": "Ярославская область"})
        check("регион сохранён", r.status_code == 200 and r.json()["region"] == "Ярославская область", r.text)
        r = client.get("/api/v1/orgs")
        orgs = r.json()
        check(
            "организации по региону",
            r.status_code == 200 and len(orgs) > 0
            and all(o["region"] == "Ярославская область" for o in orgs)
            and any("диагностический" in o["title"].lower() for o in orgs),
            r.text,
        )
        r = client.patch("/api/v1/me/settings", json={"region": "Москва"})
        check("неизвестный регион → 422", r.status_code == 422, r.text)

        # экспорт PDF: dev-доступ и одноразовый токен
        r = client.get("/api/v1/health/export")
        check("PDF при dev-доступе", r.status_code == 200 and r.headers["content-type"] == "application/pdf", str(r.status_code))
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
        with SessionLocal() as s:
            pending = s.query(ExportRequest).filter(ExportRequest.sent_at.is_(None)).count()
        check("заявка в очереди", pending >= 1, str(pending))

        # Удаление данных возвращает к временному профилю: GET /me не создаёт аккаунт.
        r = client.delete("/api/v1/me/data")
        check("удаление данных", r.status_code == 200, r.text)
        r = client.get("/api/v1/me")
        check(
            "после удаления временный профиль без согласия",
            r.status_code == 200 and r.json()["id"] == 0 and r.json()["consent_at"] is None,
            r.text,
        )
        with SessionLocal() as db:
            check("после удаления аккаунта нет в БД", db.query(User).count() == 0)
        check("регион по умолчанию — пилотный", r.json()["region"] == "Ивановская область", r.text)
        r = client.get("/api/v1/route")
        check("данные без согласия → 403", r.status_code == 403, str(r.status_code))
        r = client.post("/api/v1/me/consent", json={})
        check("повторное согласие", r.status_code == 200, r.text)
        r = client.get("/api/v1/route")
        check("аккаунт чистый: маршрута нет", r.status_code == 200 and r.json() is None, r.text)
        r = client.get("/api/v1/meds")
        check("аккаунт чистый: курсов лекарств нет", r.status_code == 200 and r.json()["courses"] == [], r.text)
        r = client.get("/api/v1/health/report")
        check("аккаунт чистый: записи дневников нет", r.status_code == 200 and r.json()["bp_count"] == 0, r.text)
        r = client.post("/api/v1/route/start", json={"situation_key": "custom"})
        check("новый маршрут создаётся", r.status_code == 200 and r.json()["done_steps"] == 0, r.text)

    print(f"\nВсе проверки пройдены: {PASS}")


if __name__ == "__main__":
    main()
