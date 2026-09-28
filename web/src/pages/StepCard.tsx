import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline, fmtDayMonth } from "../format";
import type { CompleteStepResult, RouteDto, Step } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

interface Picked {
  title: string;
  date: string; // YYYY-MM-DD или ""
  own: boolean;
}

const CHIPS = ["Анализы", "УЗИ", "Специалист", "Процедуры", "Прививка"];

export default function StepCard() {
  const { stepId } = useParams();
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [assignSheet, setAssignSheet] = useState(false);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [ownName, setOwnName] = useState("");
  const [ownDate, setOwnDate] = useState("");
  const [ownAttempted, setOwnAttempted] = useState(false);

  const load = () => {
    setStatus("loading");
    api.get<RouteDto | null>("/api/v1/route")
      .then((r) => { setRoute(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  };
  useEffect(load, [stepId]);

  const step: Step | null = useMemo(() => route?.steps.find((s) => String(s.id) === stepId) ?? null, [route, stepId]);

  const remind = async () => {
    if (!step) return;
    try {
      await api.post("/api/v1/reminders", { title: step.title, place: step.place });
      showToast("Напоминание создано — бот пришлёт его в MAX");
    } catch {
      showToast("Не удалось создать напоминание");
    }
  };

  const complete = async () => {
    if (!step) return;
    setBusy(true);
    try {
      await api.post<CompleteStepResult>(`/api/v1/route/steps/${step.id}/complete`, {});
      setAssignSheet(true); // «врач назначил — записал»: сразу предлагаем записать назначения
    } catch {
      showToast("Не удалось отметить шаг");
    } finally {
      setBusy(false);
    }
  };

  const uncomplete = async () => {
    if (!step) return;
    setBusy(true);
    try {
      await api.post<RouteDto>(`/api/v1/route/steps/${step.id}/uncomplete`);
      showToast("Выполнение отменено");
      nav("/route");
    } catch {
      showToast("Не удалось отменить выполнение");
    } finally {
      setBusy(false);
    }
  };

  const saveDeadline = async (value: string | null) => {
    if (!step) return;
    try {
      await api.patch<Step>(`/api/v1/route/steps/${step.id}`, { deadline: value });
      showToast(value ? "Срок обновлён" : "Срок убран");
      load();
    } catch {
      showToast("Не удалось изменить срок");
    }
  };

  const toggleChip = (title: string) => {
    setPicked((prev) =>
      prev.some((p) => p.title === title && !p.own)
        ? prev.filter((p) => !(p.title === title && !p.own))
        : [...prev, { title, date: "", own: false }],
    );
  };

  const addOwn = () => {
    const name = ownName.trim();
    if (!name) {
      setOwnAttempted(true);
      showToast("Напишите название назначения — оно подсвечено красным");
      return;
    }
    setPicked((prev) => [{ title: name, date: ownDate, own: true }, ...prev]);
    setOwnName("");
    setOwnDate("");
    setOwnAttempted(false);
  };

  const saveAssignments = async () => {
    setBusy(true);
    try {
      let afterId = step?.id;
      for (const p of picked) {
        const res = await api.post<RouteDto>(
          `/api/v1/route/steps?after_step_id=${afterId}`,
          { title: p.title, deadline: p.date || null, source: "doctor" },
        );
        afterId = res.steps.find((s) => s.title === p.title)?.id ?? afterId;
      }
      setAssignSheet(false);
      showToast(picked.length ? `Добавлено шагов: ${picked.length}` : "Шаг выполнен");
      nav("/route");
    } catch {
      showToast("Не удалось добавить назначения");
    } finally {
      setBusy(false);
    }
  };

  if (status === "error") {
    return (
      <div className="app narrow">
        <Header title="Шаг" back="/route" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const count = picked.length;

  return (
    <div className="app narrow">
      <Header title={step ? step.title : "Шаг"} subtitle={step ? `Шаг ${step.position} из ${route?.total_steps ?? "…"}` : undefined} back="/route" />
      <div className="screen-body">
        {status === "loading" || !step ? (
          <LoadingView />
        ) : (
          <>
            <div className="card">
              {step.status !== "done" ? (
                <div className="kv" style={{ gap: 10 }}>
                  <I.cal size={18} />
                  <input
                    className="step-date"
                    type="date"
                    aria-label="Срок шага"
                    value={step.deadline ?? ""}
                    onChange={(e) => saveDeadline(e.target.value || null)}
                  />
                </div>
              ) : (
                step.deadline && (
                  <div className="kv"><I.cal size={18} />{fmtDeadline(step.deadline, step.deadline_time)}</div>
                )
              )}
              {step.place && <div className="kv"><I.pin size={18} />{step.place}</div>}
              {step.description && (
                <div className="kv" style={{ fontWeight: 500, color: "var(--muted)", marginTop: 12 }}>{step.description}</div>
              )}
            </div>

            {step.status === "done" && (
              <div className="card tinted">
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--blue)" }}>Шаг выполнен</div>
                <div className="muted" style={{ marginTop: 4 }}>
                  {fmtDayMonth(step.completed_at ?? null) && `Отмечен ${fmtDayMonth(step.completed_at)}. `}
                  Можно записать назначения врача — маршрут перестроится.
                </div>
                <Button style={{ marginTop: 12 }} variant="secondary" onClick={() => setAssignSheet(true)}>
                  <I.plus size={16} /> Записать назначения врача
                </Button>
                <Button style={{ marginTop: 8 }} variant="secondary" disabled={busy} onClick={uncomplete}>
                  {busy ? "Отменяем…" : "Отменить выполнение"}
                </Button>
              </div>
            )}

            {step.has_checklist && (
              <div className="card docs-card">
                <div className="section-h" style={{ marginBottom: 6 }}><b>Что взять с собой</b></div>
                <button className="row-item" style={{ boxShadow: "none", padding: "6px 0" }} onClick={() => nav("/route")}>
                  <div className="row-body"><h3>Чек-лист документов</h3><p>Отметьте собранное в разделе «Маршрут»</p></div>
                  <span className="row-chev"><I.chev size={18} /></span>
                </button>
              </div>
            )}

            {step.note && (
              <div className="card">
                <h3 className="h3">Заметка</h3>
                <p className="muted" style={{ marginTop: 8 }}>{step.note}</p>
              </div>
            )}
          </>
        )}
      </div>

      {step && step.status !== "done" && (
        <div className="foot">
          <div className="btn-row">
            <Button variant="secondary" onClick={remind}><I.bell size={18} />Напомнить</Button>
            <Button disabled={busy} onClick={complete}>{busy ? "Отмечаем…" : "Я это сделал"}</Button>
          </div>
        </div>
      )}

      <Sheet open={assignSheet} onClose={() => { setAssignSheet(false); nav("/route"); }}>
        <h3>Что назначил врач?</h3>
        <div className="sub">Добавим шагами в маршрут — бот напомнит о каждом</div>
        <div className="pick-chips">
          {CHIPS.map((c) => (
            <button
              key={c}
              className={`pick${picked.some((p) => p.title === c) ? " on" : ""}`}
              onClick={() => toggleChip(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="own-row">
          <input
            placeholder="Своё: например, МРТ"
            aria-label="Название назначения"
            value={ownName}
            className={ownAttempted && !ownName.trim() ? "invalid" : undefined}
            onChange={(e) => setOwnName(e.target.value)}
          />
          <input className="date" type="date" aria-label="Срок" value={ownDate} onChange={(e) => setOwnDate(e.target.value)} />
          <button className="add" onClick={addOwn} aria-label="Добавить">+</button>
        </div>
        {picked.length > 0 && (
          <div className="picked">
            {picked.map((p, i) => (
              <div className="picked-item" key={`${p.title}-${i}`}>
                {p.title}
                {p.date && <small>до {fmtDayMonth(p.date)}</small>}
                <button className="x" aria-label="Убрать" onClick={() => setPicked((prev) => prev.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
          </div>
        )}
        <div className="btn-row" style={{ marginTop: 14 }}>
          <Button variant="secondary" onClick={() => { setAssignSheet(false); nav("/route"); }}>
            Без назначений
          </Button>
          <Button disabled={busy} onClick={saveAssignments}>
            {busy ? "Добавляем…" : count > 0 ? <>Готово — добавить {count}</> : "Готово"}
          </Button>
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
