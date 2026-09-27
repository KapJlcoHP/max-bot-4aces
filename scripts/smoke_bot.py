"""Смоук-проверка бота и планировщика без запуска бота (серверный экземпляр 24/7!).

Запуск из корня zabota:  .venv/Scripts/python.exe scripts/smoke_bot.py
Временная SQLite-БД, живых сообщений MAX не отправляет.
"""

import os
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# временная БД ДО импортов (session.py читает settings один раз)
os.environ["DATABASE_URL"] = "sqlite:///./database/_smoke_bot.db"

from core.db.models import (  # noqa: E402
    HealthSetting,
    MedCourse,
    MedIntake,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.db.session import SessionLocal, init_db  # noqa: E402
from core.services import (  # noqa: E402
    ServiceError,
    add_health_record,
    complete_route_step,
    take_med,
)
from bot.handlers.actions import parse_bp  # noqa: E402
from bot.scheduler import collect_due, mark_sent  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        sys.exit(1)
    PASS += 1


def seed(db, max_user_id: int = 1001) -> dict[int, int]:
    user = User(max_user_id=max_user_id, first_name="Анна", consent_at=utcnow())
    db.add(user)
    db.commit()
    route = Route(user_id=user.id, situation_key="disp", title="Диспансеризация", active=True)
    db.add(route)
    db.commit()
    s1 = RouteStep(route_id=route.id, position=0, title="Анализы крови", deadline=date.today(), deadline_time="14:00", status="current")
    s2 = RouteStep(route_id=route.id, position=1, title="ЭКГ", status="pending")
    db.add_all([s1, s2])
    db.add(Reminder(user_id=user.id, title="Офтальмолог", place="Поликлиника №2", at=datetime.now() + timedelta(days=1)))
    db.add(MedCourse(user_id=user.id, name="Магний B6", times=["09:00", "18:00"]))
    db.add(HealthSetting(user_id=user.id, diary="bp", enabled=True, push_time="08:00"))
    db.add(HealthSetting(user_id=user.id, diary="weight", enabled=True))  # без push_time
    db.commit()
    return {"user_id": user.id, "step1": s1.id, "step2": s2.id}


def main() -> None:
    db_file = Path("database/_smoke_bot.db")
    if db_file.exists():
        db_file.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(db_file) + suffix)
        if extra.exists():
            extra.unlink()
    init_db()

    # --- парсеры ---
    check("parse_bp 120/80", parse_bp("120/80") == (120, 80, None))
    check("parse_bp с пульсом и запятой", parse_bp("давление 120/80, пульс 72") == (120, 80, 72))
    try:
        parse_bp("не понял")
        check("parse_bp отклоняет мусор", False)
    except ServiceError:
        check("parse_bp отклоняет мусор", True)

    # --- сервисы ---
    with SessionLocal() as db:
        ids = seed(db)
        step = complete_route_step(db, ids["user_id"], ids["step1"])
        check("complete_route_step → done", step.status == "done")
        nxt = db.get(RouteStep, ids["step2"])
        check("следующий шаг продвинут в current", nxt.status == "current")
        try:
            complete_route_step(db, ids["user_id"], ids["step1"])
            check("повторное выполнение → 409", False)
        except ServiceError as e:
            check("повторное выполнение → 409", e.status == 409)

        intake = take_med(db, ids["user_id"], 1, "09:00")
        check("take_med ставит taken_at", intake.taken_at is not None)
        intake2 = take_med(db, ids["user_id"], 1, "09:00")
        check("take_med идемпотентен (один слот)", intake2.id == intake.id)

        rec = add_health_record(db, ids["user_id"], "bp", systolic=125, diastolic=82, pulse=70)
        check("add_health_record bp", rec.systolic == 125)
        try:
            add_health_record(db, ids["user_id"], "bp", systolic=300, diastolic=100)
            check("диапазоны проверяются", False)
        except ServiceError as e:
            check("диапазоны проверяются", e.status == 422 and "диапазон" in str(e))
        try:
            add_health_record(db, ids["user_id"], "bp", systolic=100, diastolic=120)
            check("нижнее > верхнего отклоняется", False)
        except ServiceError:
            check("нижнее > верхнего отклоняется", True)

    # --- планировщик ---
    with SessionLocal() as db:
        ids = seed(db, max_user_id=2002)
        user = db.query(User).filter(User.max_user_id == 2002).first()
        step = db.get(RouteStep, ids["step1"])
        due_at = datetime.combine(step.deadline, dtime(14, 0))
        reminder = db.query(Reminder).filter(Reminder.user_id == user.id).first()
        reminder.at = due_at + timedelta(days=1)  # детерминизм: день-лид сработает ровно в due_at
        course = db.query(MedCourse).filter(MedCourse.user_id == user.id).first()
        setting = (
            db.query(HealthSetting)
            .filter(HealthSetting.user_id == user.id, HealthSetting.push_time.is_not(None))
            .first()
        )
        db.commit()

        # 1) за сутки до всего (порог day-лида пройден 5 минут назад)
        now = due_at - timedelta(days=1) + timedelta(minutes=5)
        pushes = collect_due(db, now)
        kinds = {(p.kind, p.lead) for p in pushes}
        check("лид day: шаг", ("step", "day") in kinds)
        check("напоминанию до day-лида рано", ("reminder", "day") not in kinds)
        check("лид day: дневник по времени 08:00", any(p.kind == "diary" for p in pushes))
        check("weight без push_time не пушится", all(p.kind != "diary" or p.ref_id == setting.id for p in pushes))
        for p in pushes:  # эмулируем успешную отправку → дедуп
            mark_sent(db, p)

        # 2) за час до срока (лекарство 09:00 уже в окне: 09:00–15:00)
        now = due_at - timedelta(minutes=30)
        pushes = collect_due(db, now)
        kinds = {(p.kind, p.lead) for p in pushes}
        check("лид hour: шаг", ("step", "hour") in kinds)
        check("лид day не повторяется", ("step", "day") not in kinds)
        check("лекарство 09:00 в окне", any(p.kind == "med" and "Магний" in p.text for p in pushes))
        med_leads = [p.lead for p in pushes if p.kind == "med"]
        check("лид лекарства посуточный", all(len(lead) == 13 for lead in med_leads), str(med_leads))
        for p in pushes:
            mark_sent(db, p)

        # 3) в момент срока + время лекарства + напоминание «сейчас»
        db.add(Reminder(user_id=user.id, title="Срочно", at=due_at - timedelta(minutes=1)))
        db.commit()
        now = due_at + timedelta(minutes=5)
        pushes = collect_due(db, now)
        kinds = {(p.kind, p.lead) for p in pushes}
        check("лид now: шаг", ("step", "now") in kinds)
        check("лид day: напоминание на завтра", ("reminder", "day") in kinds)
        check("лекарство 09:00 не повторяется после дедупа", all(p.kind != "med" for p in pushes))
        check("напоминание now (за 6 мин до)", ("reminder", "now") in kinds)

        # отметим приём — пуш пропадает (лекарство 18:00 ещё не наступило, берём напрямую)
        take_med(db, user.id, course.id, "18:00")
        now2 = datetime.combine(due_at.date(), dtime(18, 5))
        pushes = collect_due(db, now2)
        bad = [f"{p.kind}/{p.lead}:{p.text[:40]}" for p in pushes if p.kind == "med" and p.user_id == user.id and "18:00" in p.text]
        check("после приёма пуш не приходит", not bad, str(bad))

        # дневник: запись сегодня есть — пуша нет
        add_health_record(db, user.id, "bp", systolic=120, diastolic=80)
        pushes = collect_due(db, now)
        check("запись дня есть → дневник молчит", all(p.kind != "diary" for p in pushes))

    # --- дедуп после отправки: mark_sent проверен выше по ходу сценария ---

    with SessionLocal() as db:
        ids = seed(db, max_user_id=3003)
        user = db.query(User).filter(User.max_user_id == 3003).first()
        step = db.get(RouteStep, ids["step1"])
        due_at = datetime.combine(step.deadline, dtime(14, 0))
        now = due_at - timedelta(days=1) + timedelta(minutes=5)
        pushes = collect_due(db, now)
        step_push = next(p for p in pushes if p.kind == "step")
        mark_sent(db, step_push)
        pushes2 = collect_due(db, now)
        check("mark_sent убирает повтор", all(p.kind != "step" for p in pushes2))

    print(f"\nВсе проверки пройдены: {PASS}")
    print("(временная БД database/_smoke_bot.db остаётся для инспекции, в прод не попадает)")


if __name__ == "__main__":
    main()
