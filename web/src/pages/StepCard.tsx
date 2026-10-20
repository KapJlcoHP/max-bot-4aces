import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useApp } from "../App";
import { useNow } from "../hooks/useNow";
import StepCountdown from "../components/StepCountdown";
import StepScheduleEditor from "../components/StepScheduleEditor";
import EventDateTimeInputs from "../components/EventDateTimeInputs";
import StepKindSelect from "../components/StepKindSelect";
import StepKindEditor from "../components/StepKindEditor";
import BookingEditor from "../components/BookingEditor";
import { openExternalLink } from "../bridge";
import { fmtDateNumeric, fmtDeadline, fmtDayMonth } from "../format";
import type { CompleteStepResult, RouteDto, Step, StepKind, StepAssignmentsIn, StepAssignmentsResult } from "../types";
import { KIND_LABELS } from "../stepKinds";
import { Button, ErrorView, Header, LoadingView, Sheet, StateView, useToast } from "../components/ui";
import { I } from "../icons";

interface Picked {
  title: string;
  kind: StepKind;
  date: string; // YYYY-MM-DD или ""
  time: string;
  own: boolean;
}

const CHIPS: { title: string; kind: StepKind }[] = [
  { title: "Анализы", kind: "investigation" }, { title: "УЗИ", kind: "investigation" },
  { title: "Приём специалиста", kind: "visit" }, { title: "Разовая процедура", kind: "investigation" },
  { title: "Этап курса процедур", kind: "process" }, { title: "Прививка", kind: "investigation" },
];

function userTimeZone(city: string | null, legacyTz?: string): string {
  return city === "Иваново" || city === "Владимир" || city === "Ярославль"
    ? "Europe/Moscow"
    : legacyTz || (Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Moscow");
}

export default function StepCard() {
  const { user } = useApp();
  const now = useNow();
  const { stepId } = useParams();
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const [bookingLocked, setBookingLocked] = useState(false);
  const bookingLock = useRef(false);
  const [assignSheet, setAssignSheet] = useState(false);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [ownName, setOwnName] = useState("");
  const [ownDate, setOwnDate] = useState("");
  const [ownTime, setOwnTime] = useState("");
  const [ownKind, setOwnKind] = useState<StepKind>("task");
  const [ownAttempted, setOwnAttempted] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [assignmentError, setAssignmentError] = useState("");
  const loadRequestId = useRef(0);
  const inFlight = useRef(false);
  const pendingSubmission = useRef<StepAssignmentsIn | null>(null);
  const scope = `${user.id}:${user.max_user_id}:${stepId}`;
  const activeScope = useRef(scope);
  activeScope.current = scope;

  const clearDraft = () => {
    setPicked([]);
    setOwnName("");
    setOwnDate("");
    setOwnTime("");
    setOwnKind("task");
    setOwnAttempted(false);
    setUncertain(false);
    setAssignmentError("");
    pendingSubmission.current = null;
  };

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
  useEffect(() => {
    inFlight.current = false;
    bookingLock.current = false; setBookingLocked(false);
    setBusy(false);
    setAssignSheet(false);
    clearDraft();
    load();
    return () => { ++loadRequestId.current; };
  }, [scope]);

  const step: Step | null = useMemo(() => route?.steps.find((s) => String(s.id) === stepId) ?? null, [route, stepId]);

  const complete = async () => {
    if (!step || step.status !== "current" || inFlight.current || bookingLock.current || scope !== activeScope.current) return;
    if (step.kind === "visit") { setAssignSheet(true); return; }
    const version = loadRequestId.current;
    inFlight.current = true; setBusy(true);
    try {
      const result = await api.post<CompleteStepResult>(`/api/v1/route/steps/${step.id}/complete`);
      if (version !== loadRequestId.current || scope !== activeScope.current) return;
      setRoute(result.route); showToast("Шаг выполнен"); nav("/route");
    } catch { if (version === loadRequestId.current && scope === activeScope.current) showToast("Не удалось подтвердить выполнение. Обновите маршрут"); }
    finally { if (version === loadRequestId.current && scope === activeScope.current) { inFlight.current = false; setBusy(false); } }
  };

  const closeAssignments = () => {
    if (inFlight.current || pendingSubmission.current || scope !== activeScope.current) return;
    setAssignSheet(false);
  };

  const uncomplete = async () => {
    if (!step || inFlight.current || pendingSubmission.current || scope !== activeScope.current) return;
    const routeRequestId = loadRequestId.current;
    inFlight.current = true;
    setBusy(true);
    try {
      await api.post<RouteDto>(`/api/v1/route/steps/${step.id}/uncomplete`);
      if (routeRequestId !== loadRequestId.current || scope !== activeScope.current) return;
      showToast("Выполнение отменено");
      nav("/route");
    } catch {
      if (routeRequestId === loadRequestId.current && scope === activeScope.current) showToast("Не удалось отменить выполнение");
    } finally {
      if (routeRequestId === loadRequestId.current && scope === activeScope.current) {
        inFlight.current = false;
        setBusy(false);
      }
    }
  };

  const toggleChip = ({ title, kind }: { title: string; kind: StepKind }) => {
    if (inFlight.current || pendingSubmission.current) return;
    setPicked((prev) =>
      prev.some((p) => p.title === title && !p.own)
        ? prev.filter((p) => !(p.title === title && !p.own))
        : [...prev, { title, kind, date: "", time: "", own: false }],
    );
  };

  const addOwn = () => {
    if (inFlight.current || pendingSubmission.current) return;
    const name = ownName.trim();
    if (!name) {
      setOwnAttempted(true);
      showToast("Напишите название назначения — оно подсвечено красным");
      return;
    }
    setPicked((prev) => [{ title: name, kind: ownKind, date: ownDate, time: ownTime, own: true }, ...prev]);
    setOwnName("");
    setOwnDate("");
    setOwnTime("");
    setOwnAttempted(false);
  };

  const saveAssignments = async (withoutAssignments = false, retry = false) => {
    if (!step || step.kind !== "visit" || !["current", "done"].includes(step.status) || inFlight.current || scope !== activeScope.current) return;
    // An unknown outcome can only retry the frozen original request, never the edited draft.
    if (pendingSubmission.current && !retry) return;
    if (retry && !pendingSubmission.current) return;
    const body: StepAssignmentsIn = pendingSubmission.current ?? {
      request_id: crypto.randomUUID(),
      complete: step.status === "current",
      assignments: withoutAssignments ? [] : picked.map((p) => ({
        title: p.title,
        kind: p.kind,
        ...(p.kind === "booking" ? { appointment_date: p.date || null } : {}),
        deadline: p.kind === "booking" ? null : p.date || null,
        deadline_time: p.kind !== "booking" && p.date && p.time ? p.time : null,
      })),
    };
    pendingSubmission.current = body;
    const routeRequestId = loadRequestId.current;
    inFlight.current = true;
    setBusy(true);
    setAssignmentError("");
    let succeeded = false;
    try {
      const result = await api.post<StepAssignmentsResult>(`/api/v1/route/steps/${step.id}/assignments`, body);
      if (routeRequestId !== loadRequestId.current || scope !== activeScope.current) return;
      succeeded = true;
      setRoute(result.route);
      clearDraft();
      setAssignSheet(false);
      showToast(body.assignments.length ? `Добавлено шагов: ${result.added_step_ids.length}` : "Шаг выполнен");
      nav("/route");
    } catch (error) {
      if (routeRequestId !== loadRequestId.current || scope !== activeScope.current) return;
      // Auth/proxy errors during a retry do not resolve a previous lost response.
      // Only explicit validation/state rejections let this draft use a new key.
      if (error instanceof ApiError && [400, 409, 422].includes(error.status)) {
        pendingSubmission.current = null;
        setUncertain(false);
        setAssignmentError(error.message);
      } else {
        setUncertain(true);
        setAssignmentError("Ответ не получен или результат не подтверждён. Назначения могли сохраниться. Изменение и закрытие формы временно недоступны: повторите исходную отправку — повтор не создаст дубликаты.");
      }
    } finally {
      if (routeRequestId === loadRequestId.current && scope === activeScope.current) {
        // Keep the synchronous guard after success until navigation finishes.
        if (!succeeded) inFlight.current = false;
        setBusy(false);
      }
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
  const draftLocked = busy || uncertain || bookingLocked;

  return (
    <div className="app narrow">
      <Header title={step ? step.title : "Шаг"} subtitle={step ? `Шаг ${step.position} из ${route?.total_steps ?? "…"}` : undefined} back="/route" />
      <div className="screen-body">
        <>
            {step.kind === "booking" && step.status !== "done" && <BookingEditor key={`booking-${scope}`} step={step} steps={route?.steps ?? []} disabled={busy}
              onLocked={(locked) => { bookingLock.current = locked; setBookingLocked(locked); }} onSaved={(result) => setRoute(result.route)} onReload={load} />}
            {step.kind === "booking" && step.status === "done" && <div className="card booking-summary">
              <h3 className="h3">Запись на событие</h3>
              <div className="kv" style={{ marginTop: 10 }}><I.cal size={18} />На какую дату вы записались? {step.appointment_date ? fmtDateNumeric(step.appointment_date) : "Дата пока неизвестна"}</div>
              <div className="kv" style={{ marginTop: 10 }}><I.route size={18} />{route?.steps.find((s) => s.id === step.booking_target_step_id)?.title ?? "Без связи с событием"}</div>
            </div>}

            {step.kind !== "booking" && <div className="card">
              <p className="muted">{KIND_LABELS[step.kind ?? "unknown"]}</p>
              {step.deadline && <div className="kv"><I.cal size={18} />{fmtDeadline(step.deadline, step.deadline_time)}</div>}
              <div className="step-deadline-meta">
                {step.status !== "done" && step.deadline && step.deadline_time && <span className="muted">В {step.deadline_time}</span>}
                <StepCountdown step={step} tz={userTimeZone(user.city, "tz" in user ? String(user.tz) : undefined)} now={now} />
              </div>
              {step.place && <div className="kv"><I.pin size={18} />{step.place}</div>}
              {step.description && (
                <div className="kv" style={{ fontWeight: 500, color: "var(--muted)", marginTop: 12 }}>{step.description}</div>
              )}
            </div>}

            {step.status !== "done" && <details className="step-advanced" open={step.kind === "unknown" || step.source === "user"}>
              <summary>Срок и напоминание</summary>
              <StepScheduleEditor key={step.id} step={step} user={user} now={now} disabled={bookingLocked || busy}
                onSaved={(updated) => setRoute((r) => r ? { ...r, steps: r.steps.map((s) => s.id === updated.id ? updated : s) } : r)} />
            </details>}

            {(step.status !== "done" || step.kind === "unknown") && <details className="step-advanced" open={step.kind === "unknown" || step.source === "user"}>
              <summary>Вид шага и связь</summary>
              <StepKindEditor key={`kind-${step.id}`} step={step} steps={route?.steps ?? []} disabled={bookingLocked || busy}
                onSaved={(updated) => setRoute((r) => r ? { ...r, steps: r.steps.map((s) => s.id === updated.id ? updated : s) } : r)} />
            </details>}
            {step.status !== "done" && step.kind !== "booking" && <Button className="prep-action secondary-action" variant="secondary" onClick={() => nav(`/route?before_step_id=${step.id}`)}>Добавить подготовку перед этим событием</Button>}

            <details className="card step-source">
              <summary>Источник</summary>
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
            </details>

            {step.status === "done" && (
              <div className="card tinted">
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--blue)" }}>Шаг выполнен</div>
                <div className="muted" style={{ marginTop: 4 }}>
                  {fmtDayMonth(step.completed_at ?? null) && `Отмечен ${fmtDayMonth(step.completed_at)}. `}
                  {step.kind === "visit" && "Можно записать назначения врача — маршрут перестроится."}
                </div>
                {step.kind === "visit" && <Button style={{ marginTop: 12 }} variant="secondary" disabled={busy} onClick={() => { if (!inFlight.current) setAssignSheet(true); }}>
                  <I.plus size={16} /> Записать назначения врача
                </Button>}
                <Button style={{ marginTop: 8 }} variant="secondary" disabled={draftLocked} onClick={uncomplete}>
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
            <Button disabled={draftLocked || step.status !== "current"} onClick={complete}>{busy ? "Отмечаем…" : step.kind === "booking" ? "Завершить без внесения даты" : "Я это сделал"}</Button>
          </div>
          {step.status === "pending" && <p className="muted">Сначала завершите текущий шаг. Срок и напоминание этого шага можно настроить заранее.</p>}
        </div>
      )}

      <Sheet open={assignSheet} onClose={closeAssignments}>
        <h3>Что назначил врач?</h3>
        <div className="sub">{step.status === "current" && "Шаг будет выполнен только после подтверждения. "}Добавим шагами в маршрут. Дата и время необязательны (в вашем местном времени); уведомления получает только текущий шаг.</div>
        {assignmentError && <p role="alert" className="muted">{assignmentError}</p>}
        {assignmentError && !uncertain && <Button variant="secondary" disabled={busy} onClick={() => {
          if (inFlight.current || pendingSubmission.current) return;
          setAssignSheet(false);
          load();
        }}>Обновить маршрут</Button>}
        {uncertain && <p className="muted">Исходная отправка: {pendingSubmission.current?.assignments.length ?? 0} назначений{pendingSubmission.current?.complete ? " и выполнение шага" : ""}.</p>}
        <div className="pick-chips">
          {CHIPS.map((c) => (
            <button
              type="button"
              key={c.title}
              className={`pick${picked.some((p) => p.title === c.title) ? " on" : ""}`}
              aria-pressed={picked.some((p) => p.title === c.title)}
              disabled={draftLocked}
              onClick={() => toggleChip(c)}
            >
              {c.title}
            </button>
          ))}
        </div>
        <div className="own-row" style={{ flexWrap: "wrap" }}>
          <StepKindSelect label="Вид своего назначения" value={ownKind} disabled={draftLocked} onChange={(kind) => { if (!inFlight.current && !pendingSubmission.current) { setOwnKind(kind); if (kind === "booking") setOwnTime(""); } }} />
          <input
            placeholder="Своё: например, МРТ"
            aria-label="Название назначения"
            value={ownName}
            disabled={draftLocked}
            className={ownAttempted && !ownName.trim() ? "invalid" : undefined}
            onChange={(e) => { if (!inFlight.current && !pendingSubmission.current) setOwnName(e.target.value); }}
          />
          {ownKind === "booking" ? <label className="date-only-field">На какую дату вы записались?<input type="date" aria-label="Дата полученной записи назначения" value={ownDate} disabled={draftLocked} onChange={(e) => { if (!inFlight.current && !pendingSubmission.current) setOwnDate(e.target.value); }} /></label> : <EventDateTimeInputs date={ownDate} time={ownTime} disabled={draftLocked} onChange={(d, t) => { if (!inFlight.current && !pendingSubmission.current) { setOwnDate(d); setOwnTime(t); } }} />}
          <button type="button" className="add" disabled={draftLocked} onClick={addOwn} aria-label="Добавить назначение">+</button>
        </div>
        {picked.length > 0 && (
          <div className="picked">
            {picked.map((p, i) => (
              <div className="picked-item" key={`${p.title}-${i}`} style={{ flexWrap: "wrap" }}>
                <b style={{ flex: 1 }}>{p.title}<small className="muted"> · {KIND_LABELS[p.kind]}</small></b>
                {p.kind === "booking" ? <label className="date-only-field">На какую дату вы записались?<input type="date" aria-label={`Дата полученной записи: ${p.title}`} value={p.date} disabled={draftLocked} onChange={(e) => { if (!inFlight.current && !pendingSubmission.current) setPicked((prev) => prev.map((item, j) => j === i ? { ...item, date: e.target.value, time: "" } : item)); }} /><small className="muted">После добавления выберите целевое событие в карточке записи. Пока дата не привязана.</small></label> : <EventDateTimeInputs date={p.date} time={p.time} disabled={draftLocked} label={`Срок: ${p.title}`} onChange={(date, time) => { if (!inFlight.current && !pendingSubmission.current) setPicked((prev) => prev.map((item, j) => j === i ? { ...item, date, time } : item)); }} />}
                <button type="button" className="x" disabled={draftLocked} aria-label={`Убрать назначение ${p.title}`} onClick={() => { if (!inFlight.current && !pendingSubmission.current) setPicked((prev) => prev.filter((_, j) => j !== i)); }}>✕</button>
              </div>
            ))}
          </div>
        )}
        <div className="btn-row" style={{ marginTop: 14 }}>
          <Button variant="secondary" disabled={draftLocked} onClick={closeAssignments}>Отмена</Button>
          {!uncertain && step.status === "current" && <Button variant="secondary" disabled={busy} onClick={() => saveAssignments(true)}>Без назначений</Button>}
          {uncertain ? (
            <Button disabled={busy} onClick={() => saveAssignments(false, true)}>{busy ? "Отправляем…" : "Повторить исходную отправку"}</Button>
          ) : (
            <Button disabled={busy || (step.status === "done" && count === 0)} onClick={() => saveAssignments()}>
              {busy ? "Отправляем…" : count > 0 ? <>Готово — добавить {count}</> : "Готово"}
            </Button>
          )}
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
