import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { useNow } from "../hooks/useNow";
import StepCountdown from "../components/StepCountdown";
import StepScheduleEditor from "../components/StepScheduleEditor";
import EventDateTimeInputs from "../components/EventDateTimeInputs";
import { openExternalLink } from "../bridge";
import { fmtDateNumeric, fmtDeadline, fmtDayMonth } from "../format";
import type { CompleteStepResult, RouteDto, Step } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, StateView, useToast } from "../components/ui";
import { I } from "../icons";

interface Picked {
  title: string;
  date: string; // YYYY-MM-DD или ""
  time: string;
  own: boolean;
}

const CHIPS = ["Анализы", "УЗИ", "Специалист", "Процедуры", "Прививка"];

export default function StepCard() {
  const { user } = useApp();
  const now = useNow();
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
  const [ownTime, setOwnTime] = useState("");
  const [ownAttempted, setOwnAttempted] = useState(false);
  const loadRequestId = useRef(0);

  const load = () => {
    const requestId = ++loadRequestId.current;
    setStatus("loading");
    api.get<RouteDto | null>("/api/v1/route")
      .then((r) => {
        if (requestId !== loadRequestId.current) return;
        setRoute(r);
        setStatus("ready");
      })
      .catch(() => {
        if (requestId === loadRequestId.current) setStatus("error");
      });
  };
  useEffect(load, [stepId]);

  const step: Step | null = useMemo(() => route?.steps.find((s) => String(s.id) === stepId) ?? null, [route, stepId]);

  const complete = async () => {
    if (!step || step.status !== "current" || busy) return;
    const routeRequestId = loadRequestId.current;
    setBusy(true);
    try {
      await api.post<CompleteStepResult>(`/api/v1/route/steps/${step.id}/complete`, {});
      if (routeRequestId !== loadRequestId.current) return;
      setAssignSheet(true); // «врач назначил — записал»: сразу предлагаем записать назначения
    } catch {
      if (routeRequestId === loadRequestId.current) showToast("Не удалось отметить шаг");
    } finally {
      setBusy(false);
    }
  };

  const uncomplete = async () => {
    if (!step || busy) return;
    const routeRequestId = loadRequestId.current;
    setBusy(true);
    try {
      await api.post<RouteDto>(`/api/v1/route/steps/${step.id}/uncomplete`);
      if (routeRequestId !== loadRequestId.current) return;
      showToast("Выполнение отменено");
      nav("/route");
    } catch {
      if (routeRequestId === loadRequestId.current) showToast("Не удалось отменить выполнение");
    } finally {
      setBusy(false);
    }
  };

  const toggleChip = (title: string) => {
    setPicked((prev) =>
      prev.some((p) => p.title === title && !p.own)
        ? prev.filter((p) => !(p.title === title && !p.own))
        : [...prev, { title, date: "", time: "", own: false }],
    );
  };

  const addOwn = () => {
    const name = ownName.trim();
    if (!name) {
      setOwnAttempted(true);
      showToast("Напишите название назначения — оно подсвечено красным");
      return;
    }
    setPicked((prev) => [{ title: name, date: ownDate, time: ownTime, own: true }, ...prev]);
    setOwnName("");
    setOwnDate("");
    setOwnTime("");
    setOwnAttempted(false);
  };

  const saveAssignments = async () => {
    if (busy) return;
    const routeRequestId = loadRequestId.current;
    setBusy(true);
    try {
      let afterId = step?.id;
      for (const p of picked) {
        const res = await api.post<RouteDto>(
          `/api/v1/route/steps?after_step_id=${afterId}`,
          { title: p.title, deadline: p.date || null, deadline_time: p.date && p.time ? p.time : null, source: "doctor" },
        );
        afterId = res.steps.find((s) => s.title === p.title)?.id ?? afterId;
      }
      if (routeRequestId !== loadRequestId.current) return;
      setAssignSheet(false);
      showToast(picked.length ? `Добавлено шагов: ${picked.length}` : "Шаг выполнен");
      nav("/route");
    } catch {
      if (routeRequestId === loadRequestId.current) showToast("Не удалось добавить назначения");
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

  if (status === "loading") {
    return (
      <div className="app narrow">
        <Header title="Шаг" back="/route" />
        <div className="screen-body"><LoadingView /></div>
      </div>
    );
  }

  if (!step) {
    return (
      <div className="app narrow">
        <Header title="Шаг" back="/route" />
        <StateView
          title="Шаг не найден"
          text="Этот шаг больше не доступен в маршруте."
          button="Вернуться к маршруту"
          onButton={() => nav("/route")}
        />
      </div>
    );
  }

  const count = picked.length;

  return (
    <div className="app narrow">
      <Header title={step ? step.title : "Шаг"} subtitle={step ? `Шаг ${step.position} из ${route?.total_steps ?? "…"}` : undefined} back="/route" />
      <div className="screen-body">
        <>
            <div className="card">
              {step.deadline && <div className="kv"><I.cal size={18} />{fmtDeadline(step.deadline, step.deadline_time)}</div>}
              <div className="step-deadline-meta">
                {step.status !== "done" && step.deadline && step.deadline_time && <span className="muted">В {step.deadline_time}</span>}
                <StepCountdown step={step} tz={user.tz} now={now} />
              </div>
              {step.place && <div className="kv"><I.pin size={18} />{step.place}</div>}
              {step.description && (
                <div className="kv" style={{ fontWeight: 500, color: "var(--muted)", marginTop: 12 }}>{step.description}</div>
              )}
            </div>

            {step.status !== "done" && <StepScheduleEditor key={step.id} step={step} user={user} now={now}
              onSaved={(updated) => setRoute((r) => r ? { ...r, steps: r.steps.map((s) => s.id === updated.id ? updated : s) } : r)} />}

            {step.reason && (
              <details className="card step-origin" key={step.id}>
                <summary>Почему этот шаг появился</summary>
                <p className="muted">{step.reason}</p>
              </details>
            )}

            <div className="card step-source">
              <h3 className="h3">Источник</h3>
              {step.source_info ? (
                <>
                  <p className="step-source-title">
                    {step.source_info.title}
                    {step.source_info.checked_at && <> · проверено {fmtDateNumeric(step.source_info.checked_at)}</>}
                  </p>
                  {!step.source_info.checked_at && <p className="muted">Редакционная проверка не проведена.</p>}
                  {step.source_info.checked_by && <p className="muted">Кем проверено: {step.source_info.checked_by}</p>}
                  {step.source_info.checked_where && <p className="muted">Где проверено: {step.source_info.checked_where}</p>}
                  <p className="muted">{step.source_info.scope}</p>
                  <Button variant="secondary" onClick={() => openExternalLink(step.source_info!.url)}>Открыть источник</Button>
                </>
              ) : (
                <p className="muted">
                  {step.source === "doctor"
                    ? "Назначение врача внесено вами. Ссылка на документ и дата проверки не указаны."
                    : step.source === "user"
                      ? "Шаг добавлен вами. Внешний источник и дата проверки не указаны."
                      : "Источник и дата проверки пока не указаны."}
                </p>
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
                <button type="button" className="row-item" style={{ boxShadow: "none", padding: "6px 0" }} onClick={() => nav("/route")}>
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
      </div>

      {step && step.status !== "done" && (
        <div className="foot">
          <div className="btn-row">
            <Button disabled={busy || step.status !== "current"} onClick={complete}>{busy ? "Отмечаем…" : "Я это сделал"}</Button>
          </div>
          {step.status === "pending" && <p className="muted">Сначала завершите текущий шаг. Срок и напоминание этого шага можно настроить заранее.</p>}
        </div>
      )}

      <Sheet open={assignSheet} onClose={() => { setAssignSheet(false); nav("/route"); }}>
        <h3>Что назначил врач?</h3>
        <div className="sub">Добавим шагами в маршрут. Проверьте даты назначений, время необязательно ({user.tz}); уведомления получает только текущий шаг.</div>
        <div className="pick-chips">
          {CHIPS.map((c) => (
            <button
              type="button"
              key={c}
              className={`pick${picked.some((p) => p.title === c) ? " on" : ""}`}
              aria-pressed={picked.some((p) => p.title === c)}
              onClick={() => toggleChip(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="own-row" style={{ flexWrap: "wrap" }}>
          <input
            placeholder="Своё: например, МРТ"
            aria-label="Название назначения"
            value={ownName}
            className={ownAttempted && !ownName.trim() ? "invalid" : undefined}
            onChange={(e) => setOwnName(e.target.value)}
          />
          <EventDateTimeInputs date={ownDate} time={ownTime} onChange={(d, t) => { setOwnDate(d); setOwnTime(t); }} />
          <button type="button" className="add" onClick={addOwn} aria-label="Добавить назначение">+</button>
        </div>
        {picked.length > 0 && (
          <div className="picked">
            {picked.map((p, i) => (
              <div className="picked-item" key={`${p.title}-${i}`} style={{ flexWrap: "wrap" }}>
                <b style={{ flex: 1 }}>{p.title}</b>
                <EventDateTimeInputs date={p.date} time={p.time} label={`Срок: ${p.title}`} onChange={(date, time) => setPicked((prev) => prev.map((item, j) => j === i ? { ...item, date, time } : item))} />
                <button type="button" className="x" aria-label={`Убрать назначение ${p.title}`} onClick={() => setPicked((prev) => prev.filter((_, j) => j !== i))}>✕</button>
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
