import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { RouteDto } from "../types";
import { ErrorView, Header, StateView } from "../components/ui";
import { I } from "../icons";

export default function RoutePage() {
  const nav = useNavigate();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<RouteDto | null>("/api/v1/route")
      .then((r) => { setRoute(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  if (status === "error") {
    return (
      <div className="app" style={{ display: "flex", flexDirection: "column" }}>
        <Header title="��аш маршрут" back="/" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const finished = route !== null && route.done_steps >= route.total_steps;
  const current = route?.steps.find((s) => s.status === "current") ?? null;

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Ваш маршрут" subtitle={route?.title ?? undefined} back="/" />
      <div className="screen-body">
        {status === "loading" && <div className="skel blk" />}
        {status === "ready" && route === null && (
          <StateView
            icon={<I.route size={64} />}
            title="Маршрута пока нет"
            text="Выберите ситуацию в каталоге — и маршрут появится здесь"
            button="Открыть каталог"
            onButton={() => nav("/catalog")}
          />
        )}
        {route && finished && (
          <StateView
            icon={<div className="big-check"><I.check size={46} /></div>}
            title="Маршрут завершён!"
            text="Поздравляем! Вы прошли все шаги маршрута. Все необходимые процедуры и документы — выполнены."
            button="Выбрать новую ситуацию"
            onButton={() => nav("/catalog")}
          />
        )}
        {route && !finished && (
          <>
            <div className="card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 13, color: "#8E8E93" }}>Прогресс маршрута</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#2563EB" }}>
                  {route.done_steps} из {route.total_steps} выполнено
                </span>
              </div>
              <div className="progress" style={{ marginTop: 12 }}>
                <i style={{ width: `${Math.round((route.done_steps / route.total_steps) * 100)}%` }} />
              </div>
            </div>

            <div className="tl" style={{ marginTop: 4 }}>
              {route.steps.map((s, i) => {
                const last = i === route.steps.length - 1;
                return (
                  <div className="tl-item" key={s.id}>
                    <div className="tl-left">
                      <div className={`tl-dot ${s.status}`}>
                        {s.status === "done" && <I.check size={15} />}
                        {s.status === "current" && <i />}
                      </div>
                      {!last && <div className="tl-line" />}
                    </div>
                    <div
                      className={`tl-card ${s.status === "current" ? "current" : ""} ${s.status !== "done" ? "press" : ""}`}
                      onClick={s.status === "current" ? () => nav(`/step/${s.id}`) : undefined}
                    >
                      <div className="tl-top">
                        <h3>{s.title}</h3>
                        {s.status === "done" ? (
                          <span className="ok">Выполнено</span>
                        ) : (
                          <span>{fmtDeadline(s.deadline, s.deadline_time)}</span>
                        )}
                      </div>
                      {s.status === "current" && s.description && <p>{s.description}</p>}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
      {route && !finished && current && (
        <div className="foot">
          <button className="btn btn-primary" onClick={() => nav(`/step/${current.id}`)}>
            Перейти к следующему шагу
          </button>
          <button className="btn btn-secondary" onClick={() => nav("/catalog")}>
            Сменить ситуацию
          </button>
        </div>
      )}
    </div>
  );
}
