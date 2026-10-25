"""Shared chat wording: booking information never substitutes a task deadline."""


def completion_label(step) -> str:
    if step.kind == "visit":
        return "✅ Завершить визит без назначений"
    if step.kind == "booking":
        return "✅ Я записался (без изменения даты)"
    return "✅ Выполнить шаг"


def booking_information(step) -> str:
    if step.kind != "booking":
        return ""
    date = step.appointment_date
    line = (f"Дата полученного события: {date.strftime('%d.%m.%Y')}."
            if date else "Дата полученного события пока неизвестна.")
    if step.booking_target_step_id is None:
        line += " Запись не связана с событием; эта дата не создаёт напоминание о нём."
    else:
        line += " Напоминания относятся к связанному событию и начнутся только когда оно станет текущим."
    return line


def deadline_label(step) -> str:
    return {
        "booking": "Срок действия «записаться» (не дата события)",
        "visit": "Дата приёма",
        "investigation": "Дата исследования/процедуры",
    }.get(step.kind, "Срок шага")
