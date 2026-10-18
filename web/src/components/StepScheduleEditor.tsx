import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Step, StepReminderMode, StepUpdateIn, UserDto } from "../types";
import { reminderWallTime } from "../stepReminderTime";
import { Button } from "./ui";
import EventDateTimeInputs from "./EventDateTimeInputs";

export default function StepScheduleEditor({ step, user, now, onSaved, disabled = false }: {
  step: Step; user: UserDto; now: Date; onSaved: (step: Step) => void;
  disabled?: boolean;
}) {
  const [date, setDate] = useState(step.deadline ?? "");
  const [time, setTime] = useState(step.deadline_time ?? "");
  const [mode, setMode] = useState<StepReminderMode>(step.reminder_mode ?? "profile");
  const [moment, setMoment] = useState(reminderWallTime(step.reminder_at, user.tz));
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const saving = useRef(false);
  const controlsDisabled = busy || disabled;
  useEffect(() => {
    setDate(step.deadline ?? "");
    setTime(step.deadline_time ?? "");
    setMode(step.reminder_mode ?? "profile");
    setMoment(reminderWallTime(step.reminder_at, user.tz));
    setConfirmed(false);
  }, [step, user.tz]);

  const eventMoved = date !== (step.deadline ?? "") || time !== (step.deadline_time ?? "");
  const review = eventMoved && step.reminder_mode === "custom" && mode === "custom";
  const expiredOnActivation = step.reminder_at && step.activated_at && new Date(step.reminder_at) < new Date(step.activated_at);
  const past = step.reminder_mode === "custom" && step.reminder_at && new Date(step.reminder_at) <= now;
  const profileLeads = [
    user.notify_day_before && `накануне в ${user.step_day_before_time}`,
    user.notify_hour_before && "за час при точном времени",
    user.notify_at_deadline && "в день срока",
  ].filter(Boolean).join(", ");
  const save = async () => {
    if (saving.current || disabled) return;
    setMessage("");
    if (mode === "custom" && (!date || !moment)) { setMessage("Укажите дату события и время напоминания"); return; }
    if (review && !confirmed) { setMessage("Проверьте и подтвердите время напоминания после изменения срока"); return; }
    saving.current = true;
    setBusy(true);
    const body: StepUpdateIn = {
      deadline: date || null,
      ...(step.kind === "booking" ? (!date || !time ? { deadline_time: null } : {}) : { deadline_time: date && time ? time : null }),
      reminder_mode: mode,
      // Keep the precise instant (including offset/fold) when the field was
      // not edited. New wall input is interpreted and DST-validated by API.
      reminder_at: mode === "custom"
        ? moment === reminderWallTime(step.reminder_at, user.tz) ? step.reminder_at : moment
        : null,
    };
    try {
      const updated = await api.patch<Step>(`/api/v1/route/steps/${step.id}`, body);
      onSaved(updated);
      setMessage("Срок и напоминание сохранены");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось сохранить. Попробуйте ещё раз");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return <div className="card">
    <h3 className="h3">{step.kind === "booking" ? "Прежний срок действия записи" : "Срок события"}</h3>
    <p className="muted">{step.kind === "booking" ? "Это отдельный срок действия «записаться» и его напоминание, не дата полученного события. Прежнее точное время сохранено; новое время оформления записи не задаётся." : "Проверьте фактическую дату приёма или свой срок. Если дата неизвестна, её можно очистить. Время необязательно."} Часовой пояс: {user.tz}.</p>
    <div className="own-row" style={{ flexWrap: "wrap" }}>
      {step.kind === "booking" ? <label>Срок действия записи<input type="date" aria-label="Срок действия записи" value={date} disabled={controlsDisabled} onChange={(e) => {
        setDate(e.target.value); setConfirmed(false); if (!e.target.value) { setTime(""); setMode("profile"); setMoment(""); }
      }} /></label> : <EventDateTimeInputs date={date} time={time} disabled={controlsDisabled} label="Срок шага" onChange={(d, t) => {
        setDate(d); setTime(t); setConfirmed(false);
        if (!d) { setMode("profile"); setMoment(""); }
        else if (!t && mode === "hour") setMode("profile");
      }} />}
      {step.kind === "booking" && time && <p className="muted">Прежнее время действия: {time}. Не время события. <button type="button" disabled={controlsDisabled} onClick={() => { setTime(""); setConfirmed(false); if (mode === "hour") setMode("profile"); }}>Очистить прежнее время</button></p>}
    </div>
    {!date && step.deadline && <p role="status" className="muted">Очистка даты также уберёт время события и отдельное напоминание.</p>}
    <h3 className="h3" style={{ marginTop: 16 }}>Напоминание</h3>
    <p className="muted">Уведомления получает только текущий шаг. Следующий шаг можно настроить заранее — это не делает его текущим.</p>
    {!user.notifications_on && <p role="status" className="muted">Уведомления выключены в профиле. Настройка сохранится, но бот не отправит сообщение, пока вы их не включите.</p>}
    <fieldset disabled={controlsDisabled} style={{ border: 0, padding: 0, display: "grid", gap: 10 }}>
      <legend className="muted">Выберите один вариант</legend>
      {!date && <p className="muted">Сначала укажите дату события, чтобы настроить отдельное напоминание.</p>}
      {([
        ["profile", "Как в профиле"],
        ...(date ? [["day", "За день"]] : []),
        ...(date && time ? [["hour", "За час"]] : []),
        ...(date ? [["custom", "В другое время…"]] : []),
      ] as [StepReminderMode, string][]).map(([value, label]) => <label key={value}>
        <input type="radio" name={`reminder-${step.id}`} checked={mode === value} onChange={() => { setMode(value); setConfirmed(false); }} /> {label}
      </label>)}
      {mode === "custom" && <label>Дата и время уведомления ({user.tz})
        <input type="datetime-local" aria-label="Дата и время напоминания" value={moment}
          style={{ display: "block", width: "100%", minWidth: 0, padding: 10, marginTop: 6, font: "inherit", border: "1px solid var(--border)", borderRadius: 10 }}
          onChange={(e) => { setMoment(e.target.value); setConfirmed(false); }} />
      </label>}
      {review && <label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Проверил время напоминания для нового срока</label>}
    </fieldset>
    {mode === "profile" && <p className="muted">{profileLeads ? `Включено в профиле: ${profileLeads}.` : "В профиле все напоминания о шагах выключены."} Без даты уведомлений нет.</p>}
    {mode === "day" && <p className="muted">Накануне в {user.step_day_before_time} по поясу профиля. Остальные уведомления профиля для этого шага заменены.</p>}
    {mode === "hour" && <p className="muted">Одно напоминание за час до события. Остальные уведомления профиля для этого шага заменены.</p>}
    {mode === "custom" && <p className="muted">Отдельный момент уведомления, не время события. Он заменяет стандартные напоминания этого шага. Для неоднозначного времени при переводе часов выберите другое время.</p>}
    {(past || expiredOnActivation) && <p role="status">Время напоминания прошло.{expiredOnActivation ? " Шаг стал текущим позже — пропущенное уведомление не отправится." : " Чтобы назначить новое, измените время или выберите другой вариант."}</p>}
    <Button style={{ marginTop: 12 }} disabled={disabled || busy || (review && !confirmed)} onClick={save}>{busy ? "Сохраняем…" : "Сохранить срок и напоминание"}</Button>
    {message && <p role="status">{message}</p>}
  </div>;
}
