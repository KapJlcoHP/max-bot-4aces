import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { CompleteStepResult, Step, StepBookingIn } from "../types";
import { bookingTargets } from "../stepKinds";
import { fmtDeadline } from "../format";
import { Button } from "./ui";

export default function BookingEditor({ step, steps, onSaved, onReload, onLocked, disabled = false }: {
  step: Step; steps: Step[]; onSaved: (result: CompleteStepResult) => void; onReload: () => void;
  onLocked?: (locked: boolean) => void;
  disabled?: boolean;
}) {
  const targets = bookingTargets(steps, step);
  const [date, setDate] = useState(step.appointment_date ?? "");
  const [targetId, setTargetId] = useState<number | null>(step.booking_target_step_id ?? null);
  const [action, setAction] = useState<"keep" | "profile">("keep");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [message, setMessage] = useState("");
  const inFlight = useRef(false);
  const pending = useRef<StepBookingIn | null>(null);
  const generation = useRef(0);
  useEffect(() => { ++generation.current; return () => { ++generation.current; }; }, [step.id]);
  useEffect(() => {
    if (pending.current) return;
    setDate(step.appointment_date ?? ""); setTargetId(step.booking_target_step_id ?? null); setConfirmed(false);
  }, [step]);
  const target = targets.find((s) => s.id === targetId) ?? null;
  const needsConfirmation = Boolean(date && target && ((target.deadline && target.deadline !== date) || target.deadline_time || target.reminder_mode !== "profile"));
  const locked = busy || uncertain || disabled;
  const edit = (change: () => void) => { if (!inFlight.current && !pending.current) { change(); setConfirmed(false); } };
  const save = async (complete: boolean, retry = false) => {
    if (inFlight.current || disabled || step.status === "done" || (complete && step.status !== "current")) return;
    if (pending.current && !retry || retry && !pending.current) return;
    if (!retry && targetId !== null && !target) { setMessage("Прежняя цель недоступна. Выберите событие или явно оставьте запись без связи."); return; }
    if (!retry && needsConfirmation && !confirmed) { setMessage("Проверьте прежнее расписание и подтвердите изменение цели"); return; }
    const body: StepBookingIn = pending.current ?? {
      request_id: crypto.randomUUID(), complete, appointment_date: date || null,
      target_step_id: target?.id ?? null, expected_target_revision: target?.reminder_revision ?? null,
      confirm_target_change: confirmed, target_reminder_action: action,
    };
    pending.current = body; inFlight.current = true; onLocked?.(true); setBusy(true); setMessage("");
    const version = generation.current;
    try {
      const result = await api.post<CompleteStepResult>(`/api/v1/route/steps/${step.id}/booking`, body);
      if (version !== generation.current) return;
      pending.current = null; onLocked?.(false); setUncertain(false); setConfirmed(false);
      setMessage(body.appointment_date ? (target?.kind === "visit" ? "Приём назначен на " : "Событие назначено на ") + body.appointment_date + (body.target_step_id === null ? ". Дата не связана с событием; напоминаний о нём из этой записи нет." : "") : "Запись сохранена. Дата пока неизвестна.");
      onSaved(result);
    } catch (error) {
      if (version !== generation.current) return;
      if (error instanceof ApiError && [400, 409, 422].includes(error.status)) {
        pending.current = null; setUncertain(false); setMessage(error.message);
      } else {
        setUncertain(true); setMessage("Ответ не подтверждён. Запись могла сохраниться. Поля заморожены: повторите исходную отправку с тем же ключом — без дубликатов.");
      }
    } finally { if (version === generation.current) { inFlight.current = false; onLocked?.(pending.current !== null); setBusy(false); } }
  };
  return <div className="card booking-editor">
    <h3 className="h3">Запись на событие</h3>
    <label className="kind-select">На какую дату вы записались?
      <input type="date" aria-label="На какую дату вы записались?" value={date} disabled={locked} onChange={(e) => edit(() => setDate(e.target.value))} />
    </label>
    <label className="kind-select">На какое событие?
      <select aria-label="Цель записи" value={targetId ?? ""} disabled={locked} onChange={(e) => edit(() => setTargetId(e.target.value ? Number(e.target.value) : null))}>
        <option value="">Без связи с событием</option>
        {targetId !== null && !target && <option value={targetId} disabled>Цель недоступна — запись не связана</option>}
        {targets.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
      </select>
    </label>
    {!date && <p className="muted">Дата пока неизвестна — её можно сохранить позже.</p>}
    {!target && <p className="muted">Без связи с событием; дата останется только в этой записи.</p>}
    <details className="booking-advanced">
      <summary>Подробности записи</summary>
      <p className="muted">Это дата полученного события, не срок действия «записаться». Точное время события меняется в его карточке. Очистка этого поля не удаляет дату и таймер события.</p>
      {target && date && <>
        <p className="muted">Цель: {target.title}. Прежнее расписание: {target.deadline ? fmtDeadline(target.deadline, target.deadline_time) : "без даты"}. Новая дата: {date}; время {target.deadline_time ?? "не указано"} сохраняется. Режим: {target.reminder_mode}{target.reminder_at ? `, отдельный таймер ${target.reminder_at}` : ""}.</p>
        <label className="kind-select">Напоминание целевого события
          <select aria-label="Напоминание цели" value={action} disabled={locked} onChange={(e) => edit(() => setAction(e.target.value as "keep" | "profile"))}>
            <option value="keep">Сохранить текущий режим и отдельный таймер</option>
            <option value="profile">Сбросить отдельный режим — как в профиле</option>
          </select>
        </label>
        {target.reminder_mode === "custom" && action === "keep" && <p className="muted">Абсолютный таймер останется в прежний момент, не сдвинется вместе с датой. Проверьте его; прошедший таймер сервер не сохранит.</p>}
        {needsConfirmation && <label><input type="checkbox" aria-label="Подтвердить изменение цели" checked={confirmed} disabled={locked} onChange={(e) => { if (!inFlight.current && !pending.current) setConfirmed(e.target.checked); }} /> Проверил прежние дату, точное время и напоминание; подтверждаю изменение цели</label>}
      </>}
      {target && <p className="muted">Цель получает уведомления только когда станет текущей; подготовка перед ней задерживает уведомления.</p>}
      {step.status === "pending" && <p className="muted">Будущую запись можно редактировать, но завершить можно только текущую.</p>}
    </details>
    {message && <p role="status">{message}</p>}
    {uncertain ? <Button disabled={busy || disabled} onClick={() => save(false, true)}>Повторить исходную отправку записи</Button> : <div className="btn-row">
      <Button variant="secondary" disabled={locked || needsConfirmation && !confirmed} onClick={() => save(false)}>Сохранить дату</Button>
      <Button disabled={locked || step.status !== "current" || needsConfirmation && !confirmed} onClick={() => save(true)}>Я записался</Button>
    </div>}
    {message && !uncertain && <Button variant="secondary" disabled={busy} onClick={() => { if (!inFlight.current && !pending.current) onReload(); }}>Обновить маршрут</Button>}
  </div>;
}
