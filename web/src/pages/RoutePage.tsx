import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { useNow } from "../hooks/useNow";
import StepCountdown from "../components/StepCountdown";
import EventDateTimeInputs from "../components/EventDateTimeInputs";
import StepKindSelect from "../components/StepKindSelect";
import { canBeBookingTarget, KIND_LABELS } from "../stepKinds";
import { fmtDeadline } from "../format";
import type { Checklist, ChecklistItem, RouteDto, Step, StepKind } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

function StepBadge({ source }: { source: Step["source"] }) {
  if (source === "doctor") return <span className="badge-assign">Назначено</span>;
  if (source === "user") return <span className="badge-mine">Мой шаг</span>;
  return null;
}

function userTimeZone(city: string | null, legacyTz?: string): string {
  return city === "Иваново" || city === "Владимир" || city === "Ярославль"
    ? "Europe/Moscow"
    : legacyTz || (Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Moscow");
}

export default function RoutePage() {
  const { user } = useApp();
  const now = useNow();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedBefore = searchParams.get("before_step_id");
  const [toast, showToast] = useToast();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sheet, setSheet] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newTime, setNewTime] = useState("");
  const [newKind, setNewKind] = useState<StepKind>("task");
  const [newTarget, setNewTarget] = useState("");
  const [beforeId, setBeforeId] = useState(requestedBefore ?? "");
  const adding = useRef(false);
  const [busy, setBusy] = useState(false);
  const [delStep, setDelStep] = useState<Step | null>(null);
  const [delRoute, setDelRoute] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.allSettled([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Checklist>("/api/v1/checklist"),
    ])
      .then(([r, c]) => {
        // An unavailable checklist is still a failed route load. Rendering a
        // partial response here can make an empty route look authoritative
        // while the API is actually unavailable; let the shared retry state
        // handle the whole screen instead.
        if (r.status === "rejected" || c.status === "rejected") {
          setRoute(null);
          setChecklist(null);
          setStatus("error");
          return;
        }
        setRoute(r.value);
        setChecklist(c.value.total > 0 ? c.value : null);
        setStatus("ready");
      });
  }, []);

  useEffect(load, []);
  useEffect(() => { if (requestedBefore) { setBeforeId(requestedBefore); setSheet(true); } }, [requestedBefore]);

  const toggleDoc = async (item: ChecklistItem) => {
    if (!checklist) return;
    try {
      const updated = await api.post<ChecklistItem>(`/api/v1/checklist/${item.id}/toggle`);
      setChecklist({
        ...checklist,
        items: checklist.items.map((i) => (i.id === updated.id ? updated : i)),
        collected: checklist.collected + (updated.collected ? 1 : -1),
      });
    } catch {
      showToast("Не удалось отметить документ");
    }
  };

  const addStep = async () => {
    if (!newTitle.trim() || adding.current) return;
    adding.current = true;
    setBusy(true);
    try {
      await api.post<RouteDto>(`/api/v1/route/steps${beforeId ? `?before_step_id=${Number(beforeId)}` : ""}`, {
        title: newTitle.trim(),
        kind: newKind,
        deadline: newKind === "booking" ? null : newDate || null,
        deadline_time: newKind !== "booking" && newDate && newTime ? newTime : null,
        appointment_date: newKind === "booking" ? newDate || null : null,
        booking_target_step_id: newKind === "booking" && newTarget ? Number(newTarget) : null,
        source: "user",
      });
      setSheet(false);
      setNewTitle("");
      setNewDate("");
      setNewTime("");
      setNewTarget("");
      showToast("Шаг добавлен в маршрут");
      load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Не удалось добавить шаг");
    } finally {
      adding.current = false;
      setBusy(false);
    }
  };

  const confirmDelStep = async () => {
    if (!delStep) return;
    setBusy(true);
    try {
      const updated = await api.del<RouteDto | null>(`/api/v1/route/steps/${delStep.id}`);
      setDelStep(null);
      if (updated === null) {
        setRoute(null);
      } else {
        setRoute(updated);
      }
      showToast("Шаг удалён");
    } catch {
      showToast("Не удалось удалить шаг");
    } finally {
      setBusy(false);
    }
  };

  const confirmDelRoute = async () => {
    setBusy(true);
    try {
      await api.del("/api/v1/route");
      setDelRoute(false);
      nav("/");
    } catch {
      showToast("Не удалось удалить маршрут");
      setDelRoute(false);
    } finally {
      setBusy(false);
    }
  };

  if (status === "error") {
    return (
      <div className="app">
        <Header title="Мой маршрут" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const finished = route !== null && route.total_steps > 0 && route.done_steps >= route.total_steps;
  const current = route?.steps.find((s) => s.status === "current") ?? null;
  const undated = route?.steps.find((s) => s.status !== "done" && s.kind !== "booking" && !s.deadline);
  const beforeStep = route?.steps.find((s) => String(s.id) === beforeId && s.status !== "done");
  const newTargets = route?.steps.filter((s) => s.status !== "done" && canBeBookingTarget(s.kind) && beforeStep && s.position >= beforeStep.position) ?? [];

  return (
    <div className="app">
      <Header
        title="Мой маршрут"
        subtitle={route?.title ?? undefined}
        right={route && !finished && (
          <button className="hdr-del" onClick={() => setDelRoute(true)} aria-label="Удалить маршрут">
            <I.trash size={19} />
          </button>
        )}
      />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}

        {status === "ready" && route === null && (
          <>
            <div className="empty-card" style={{ paddingTop: 40 }}>
              <div className="empty-ico" style={{ width: 64, height: 64 }}><I.route size={30} /></div>
              <b style={{ fontSize: 17 }}>Маршрута пока нет</b>
              <div className="muted">Выберите свою первую ситуацию — маршрут появится здесь, шаг за шагом.</div>
            </div>
            <Button onClick={() => nav("/builder")}>Выбрать ситуацию</Button>
          </>
        )}

        {route && finished && (
          <div className="route-complete">
            <div className="big-check"><I.check size={46} strokeWidth={2.4} /></div>
            <h2>Маршрут завершён!</h2>
            <p>Все шаги пройдены. История доступна ниже: можно открыть шаг, отменить выполнение или записать новые назначения. Также можно добавить шаг или построить новый маршрут.</p>
            <Button onClick={() => nav("/builder")}>Свой маршрут</Button>
          </div>
        )}

        {route && !finished && undated && <aside className="card tinted" aria-label="Сроки маршрута">
          <p className="muted">У некоторых шагов не указана дата. Укажите свои сроки — например, дату приёма. Если срок пока неизвестен, оставьте поле пустым.</p>
          <Button variant="secondary" onClick={() => nav(`/step/${undated.id}`)}>Указать дату</Button>
        </aside>}

        {route && (
          <div className="split">
            <div className="col">
              <div className="tl" style={{ marginTop: 4 }}>
                {route.steps.map((s) => (
                  <div className="tl-item" key={s.id}>
                    <div className={`tl-dot ${s.status}`}>
                      {s.status === "done" && <I.check size={14} strokeWidth={2.6} />}
                      {s.status !== "done" && s.position}
                    </div>
                    <div
                      className={`tl-card ${s.status === "done" ? "muted-t" : ""} ${s.status === "current" ? "current-t press" : ""} press`}
                      role="button"
                      tabIndex={0}
                      aria-label={`Открыть шаг ${s.title}`}
                      onClick={() => nav(`/step/${s.id}`)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          nav(`/step/${s.id}`);
                        }
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                        <b>{s.title}</b>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                          <StepBadge source={s.source} />
                          {s.status !== "done" && (
                            <button
                              className="rem-del"
                              onClick={(e) => { e.stopPropagation(); setDelStep(s); }}
                              aria-label="Удалить шаг"
                            >
                              <I.trash size={14} />
                            </button>
                          )}
                        </span>
                      </div>
                      {s.status === "current" && s.description && <div className="desc">{s.description}</div>}
                      <small className="muted">{KIND_LABELS[s.kind ?? "unknown"]}</small>
                      {s.kind === "booking" && <p className="muted">{s.appointment_date ? `Полученная дата события: ${s.appointment_date}` : "Дата события неизвестна"}{!route.steps.some((target) => target.id === s.booking_target_step_id) ? " · без связи с событием" : ""}</p>}
                      {s.deadline && (
                        <div className="when" style={{ marginTop: 4, display: "block" }}>
                          {s.kind === "booking" && "Прежний срок действия записи: "}{fmtDeadline(s.deadline, s.deadline_time)}
                        </div>
                      )}
                      <StepCountdown step={s} tz={userTimeZone(user.city, "tz" in user ? String(user.tz) : undefined)} now={now} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="col">
              <button className="add-dash" onClick={() => setSheet(true)}>
                <I.plus size={18} /> Добавить шаг
              </button>

              {checklist && (
                <>
                  <div className="section-h" style={{ marginTop: 4 }}>
                    <b>Документы на приём</b>
                    <span className="muted" style={{ fontSize: 13 }}>{checklist.collected} из {checklist.total}</span>
                  </div>
                  <div className="card docs-card">
                    {checklist.items.map((item) => (
                      <div className={`doc${item.collected ? " ok" : ""}`} key={item.id}>
                        <button className="ck" onClick={() => toggleDoc(item)} aria-label="Отметить">
                          {item.collected && <I.check size={12} strokeWidth={3} />}
                        </button>
                        {item.title}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {route && !finished && current && (
        <div className="foot">
          <div className="btn-row">
            <Button variant="secondary" onClick={() => nav("/builder")}>Свой маршрут</Button>
            <Button onClick={() => nav(`/step/${current.id}`)}>Продолжить — шаг {current.position}</Button>
          </div>
        </div>
      )}

      <Sheet open={sheet} onClose={() => setSheet(false)}>
        <h3>Добавить шаг</h3>
        <div className="sub">Проверьте фактическую дату; неизвестную можно оставить пустой. Время необязательно (в вашем местном времени). Уведомления получает только текущий шаг.</div>
        <StepKindSelect value={newKind} onChange={(kind) => { setNewKind(kind); setNewTime(""); }} disabled={busy} />
        <label className="kind-select">Размещение
          <select aria-label="Добавить перед шагом" value={beforeId} disabled={busy} onChange={(e) => { setBeforeId(e.target.value); setNewTarget(""); }}>
            <option value="">После текущего шага (в конец, если всё выполнено)</option>
            {beforeId && !beforeStep && <option value={beforeId} disabled>Выбранный шаг недоступен — уточните размещение</option>}
            {route?.steps.filter((s) => s.status !== "done").map((s) => <option key={s.id} value={s.id}>Перед шагом {s.position}: {s.title} (#{s.id})</option>)}
          </select>
        </label>
        {newKind === "booking" && <><label className="kind-select">Связанное событие
          <select aria-label="Цель нового шага записи" value={newTarget} disabled={busy} onChange={(e) => setNewTarget(e.target.value)}>
            <option value="">Без связи</option>
            {newTargets.map((s) => <option key={s.id} value={s.id}>Шаг {s.position}: {s.title} (#{s.id})</option>)}
          </select>
        </label><p className="muted">Для связи разместите запись перед выбранным событием. Полученная дата сохраняется в записи, но не меняет событие до явного подтверждения в карточке. Без связи напоминаний о событии из этой записи нет.</p></>}
        <div className="own-row route-add-row">
          <input
            placeholder="Например, МРТ"
            aria-label="Название шага"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          {newKind === "booking" ? <label className="date-only-field">На какую дату вы записались?<input type="date" aria-label="На какую дату вы записались?" value={newDate} onChange={(e) => setNewDate(e.target.value)} /></label> : <EventDateTimeInputs date={newDate} time={newTime} onChange={(d, t) => { setNewDate(d); setNewTime(t); }} />}
          <button className="add" onClick={addStep} disabled={busy || !newTitle.trim()} aria-label="Добавить">+</button>
        </div>
        <Button style={{ marginTop: 14 }} disabled={busy || !newTitle.trim()} onClick={addStep}>
          Добавить в маршрут
        </Button>
      </Sheet>

      <Sheet open={!!delStep} onClose={() => setDelStep(null)}>
        <h3>Удалить шаг?</h3>
        <div className="sub">«{delStep?.title}» уберём из маршрута — это нельзя отменить.</div>
        <div className="btn-row">
          <Button variant="secondary" onClick={() => setDelStep(null)}>Отмена</Button>
          <Button disabled={busy} onClick={confirmDelStep}>Удалить</Button>
        </div>
      </Sheet>

      <Sheet open={delRoute} onClose={() => setDelRoute(false)}>
        <h3>Удалить маршрут целиком?</h3>
        <div className="sub">Все шаги маршрута «{route?.title}» будут удалены. Это нельзя отменить.</div>
        <div className="btn-row">
          <Button variant="secondary" onClick={() => setDelRoute(false)}>Отмена</Button>
          <Button disabled={busy} onClick={confirmDelRoute}>Удалить</Button>
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
