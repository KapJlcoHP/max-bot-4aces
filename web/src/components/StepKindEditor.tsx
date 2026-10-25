import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Step, StepKind } from "../types";
import { bookingTargets } from "../stepKinds";
import StepKindSelect from "./StepKindSelect";
import { Button } from "./ui";

export default function StepKindEditor({ step, steps, onSaved, disabled = false }: { step: Step; steps: Step[]; onSaved: (step: Step) => void; disabled?: boolean }) {
  const [kind, setKind] = useState<StepKind>(step.kind ?? "unknown");
  const [targetId, setTargetId] = useState(step.booking_target_step_id ?? null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const saving = useRef(false);
  useEffect(() => { setKind(step.kind ?? "unknown"); setTargetId(step.booking_target_step_id ?? null); }, [step]);
  const targets = bookingTargets(steps, step);
  const save = async () => {
    if (saving.current || disabled || (step.status === "done" && step.kind !== "unknown")) return;
    saving.current = true; setBusy(true); setMessage("");
    try {
      const updated = await api.patch<Step>(`/api/v1/route/steps/${step.id}`, step.status === "done" ? { kind } : {
        kind, booking_target_step_id: kind === "booking" ? targetId : null,
      });
      onSaved(updated); setMessage("Вид и связь сохранены");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Не удалось сохранить"); }
    finally { saving.current = false; setBusy(false); }
  };
  return <div className="card">
    <h3 className="h3">Смысл шага</h3>
    {step.kind === "unknown" && <p className="muted">Это прежний шаг. Уточните вид явно: название и источник не определяют, является ли он приёмом врача.</p>}
    {step.status === "done" && <p className="muted">Уточняется только неизвестный вид. Дата, отметка выполнения и остальные исторические сведения не меняются.</p>}
    <StepKindSelect value={kind} disabled={busy || disabled} onChange={setKind} />
    {kind === "booking" && step.status !== "done" && <label className="kind-select">Связанное событие
      <select aria-label="Связанное событие" disabled={busy || disabled} value={targetId ?? ""} onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : null)}>
        <option value="">Без связи</option>
        {targetId !== null && !targets.some((s) => s.id === targetId) && <option value={targetId} disabled>Прежняя цель недоступна — выберите другую или уберите связь</option>}
        {targets.map((s) => <option key={s.id} value={s.id}>Шаг {s.position}: {s.title} (#{s.id})</option>)}
      </select>
    </label>}
    <p className="muted">Исследование и разовая процедура — не врачебная консультация. Для курса выберите конкретный конечный этап процесса. Расписание сохраняется отдельно.</p>
    <Button disabled={busy || disabled} onClick={save}>Сохранить вид и связь</Button>
    {message && <p role="status">{message}</p>}
  </div>;
}
