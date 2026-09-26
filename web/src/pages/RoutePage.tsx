import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { Checklist, ChecklistItem, RouteDto, Step } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, useToast } from "../components/ui";
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
  const [sheet, setSheet] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDate, setNewDate] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.allSettled([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Checklist>("/api/v1/checklist"),
    ])
      .then(([r, c]) => {
        setRoute(r.status === "fulfilled" ? r.value : null);
        setChecklist(c.status === "fulfilled" && c.value.total > 0 ? c.value : null);
        setStatus("ready");
      });
  }, []);

  useEffect(load, []);

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
      <Header title="Мой маршрут" subtitle={route?.title ?? undefined} />
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
            <p>Все шаги пройдены. Можно построить маршрут для новой ситуации.</p>
            <Button onClick={() => nav("/builder")}>Свой маршрут</Button>
          </div>
        )}

        {route && !finished && (
          <>
            <div className="tl" style={{ marginTop: 4 }}>
              {route.steps.map((s) => (
                <div className="tl-item" key={s.id}>
                  <div className={`tl-dot ${s.status}`}>
                    {s.status === "done" && <I.check size={14} strokeWidth={2.6} />}
                    {s.status !== "done" && s.position}
                  </div>
                  <div
                    className={`tl-card ${s.status === "done" ? "muted-t" : ""} ${s.status === "current" ? "current-t press" : ""}`}
                    onClick={s.status !== "done" ? () => nav(`/step/${s.id}`) : undefined}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                      <b>{s.title}</b>
                      <StepBadge source={s.source} />
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

            <button className="add-dash" onClick={() => setSheet(true)}>
              <I.plus size={18} /> Добавить шаг
            </button>

            {checklist && (
              <>
                <div className="section-h" style={{ marginTop: 8 }}>
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
          </>
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
      {toast}
    </div>
  );
}
