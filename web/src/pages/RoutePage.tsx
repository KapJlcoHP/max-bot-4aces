import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { Checklist, ChecklistItem, RouteDto, Step } from "../types";
import { Button, ErrorView, Header, InlineError, LoadingView, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

function StepBadge({ source }: { source: Step["source"] }) {
  if (source === "doctor") return <span className="badge-assign">Назначено</span>;
  if (source === "user") return <span className="badge-mine">Мой шаг</span>;
  return null;
}

export default function RoutePage() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [routeError, setRouteError] = useState(false);
  const [checklistError, setChecklistError] = useState(false);
  const [retryingChecklist, setRetryingChecklist] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const loadId = useRef(0);
  const [sheet, setSheet] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDate, setNewDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [delStep, setDelStep] = useState<Step | null>(null);
  const [delRoute, setDelRoute] = useState(false);

  const load = useCallback(() => {
    const requestId = ++loadId.current;
    setRefreshing(true);
    setStatus((previous) => previous === "ready" ? "ready" : "loading");
    Promise.allSettled([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Checklist>("/api/v1/checklist"),
    ])
      .then(([r, c]) => {
        if (requestId !== loadId.current) return;
        if (r.status === "fulfilled") setRoute(r.value);
        if (c.status === "fulfilled") setChecklist(c.value.total > 0 ? c.value : null);
        setRouteError(r.status === "rejected");
        setChecklistError(c.status === "rejected");
        setStatus((previous) => r.status === "fulfilled" || previous === "ready" ? "ready" : "error");
        setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    load();
    return () => { loadId.current += 1; };
  }, [load]);

  const retryChecklist = async () => {
    setRetryingChecklist(true);
    try {
      const updated = await api.get<Checklist>("/api/v1/checklist");
      setChecklist(updated.total > 0 ? updated : null);
      setChecklistError(false);
    } catch {
      setChecklistError(true);
    } finally {
      setRetryingChecklist(false);
    }
  };

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
    if (!newTitle.trim()) return;
    setBusy(true);
    try {
      await api.post<RouteDto>("/api/v1/route/steps", {
        title: newTitle.trim(),
        deadline: newDate || null,
        source: "user",
      });
      setSheet(false);
      setNewTitle("");
      setNewDate("");
      showToast("Шаг добавлен в маршрут");
      load();
    } catch {
      showToast("Не удалось добавить шаг");
    } finally {
      setBusy(false);
    }
  };

  const confirmDelStep = async () => {
    if (!delStep) return;
    setBusy(true);
    try {
      const updated = await api.del<RouteDto>(`/api/v1/route/steps/${delStep.id}`);
      setDelStep(null);
      if (updated.total_steps === 0) {
        // последний шаг убрали — маршрут пуст, удаляем целиком
        await api.del("/api/v1/route");
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
        {status === "ready" && routeError && <InlineError message="Не удалось обновить маршрут. Показаны последние данные." onRetry={load} retrying={refreshing} />}

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
            <p>Все шаги пройдены. Можно построить маршрут для новой ситуации.</p>
            <Button onClick={() => nav("/builder")}>Свой маршрут</Button>
          </div>
        )}
        {route && finished && checklistError && (
          <InlineError message="Не удалось загрузить документы." onRetry={retryChecklist} retrying={retryingChecklist} />
        )}

        {route && !finished && (
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
                      onClick={() => nav(`/step/${s.id}`)}
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
                      {(s.deadline || s.status === "current") && (
                        <div className="when" style={{ marginTop: 4, display: "block" }}>
                          {s.status === "current" && s.description
                            ? s.description
                            : fmtDeadline(s.deadline, s.deadline_time)}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="col">
              <button className="add-dash" onClick={() => setSheet(true)}>
                <I.plus size={18} /> Добавить шаг
              </button>

              {checklistError && (
                <InlineError message="Не удалось загрузить документы." onRetry={retryChecklist} retrying={retryingChecklist} />
              )}

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
        <div className="sub">Назначение врача или свой пункт — бот напомнит</div>
        <div className="own-row">
          <input
            placeholder="Например, МРТ"
            aria-label="Название шага"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <input
            className="date"
            type="date"
            aria-label="Срок"
            value={newDate}
            onChange={(e) => setNewDate(e.target.value)}
          />
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
