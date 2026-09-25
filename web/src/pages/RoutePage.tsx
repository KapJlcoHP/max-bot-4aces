import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { RouteDto } from "../types";
import { Button, ErrorView, Header, StateView } from "../components/ui";
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
    <div className="app route-screen" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Ваш маршрут" subtitle={route?.title ?? undefined} back="/" />
      <div className="screen-body route-body">
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
          <div className="route-complete">
            <div className="big-check"><I.check size={46} /></div>
            <h2>Маршрут завершён!</h2>
            <p>Поздравляем! Вы прошли все шаги маршрута. Все необходимые процедуры и сбор документов успешно завершены.</p>
            <div className="card route-complete-summary">
              <div className="tl-top"><h3>{route.title}</h3><span className="badge badge-blue">100% готово</span></div>
              <div className="progress"><i style={{ width: "100%" }} /></div>
              <div className="route-stats"><span>Шаги<strong>{route.total_steps}</strong></span><span>Готово<strong>{route.done_steps}</strong></span><span>Следующий<strong>0</strong></span></div>
            </div>
            <Button className="btn btn-primary" onClick={() => nav("/catalog")}>Выбрать новую ситуацию</Button>
          </div>
        )}
        {route && !finished && (
          <>
            <div className="card route-progress">
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

            <div className="tl route-timeline" style={{ marginTop: 4 }}>
              <h2 className="route-timeline-title">Этапы прохождения</h2>
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
            {current && <div className="card route-current-detail">
              <span className="badge badge-blue">ТЕКУЩИЙ ЭТАП</span>
              <h2>{current.title}</h2>
              {current.deadline && <p className="kv"><I.cal size={18} />Срок: {fmtDeadline(current.deadline, current.deadline_time)}</p>}
              {current.place && <p className="kv"><I.pin size={18} />{current.place}</p>}
              <h3>Что нужно сделать</h3>
              <p className="muted">{current.description}</p>
              <Button className="btn btn-primary" onClick={() => nav(`/step/${current.id}`)}>Открыть шаг</Button>
            </div>}
          </>
        )}
      </div>
      {route && !finished && current && (
        <div className="foot">
          <Button className="btn btn-primary" onClick={() => nav(`/step/${current.id}`)}>
            Перейти к следующему шагу
          </Button>
          <Button className="btn btn-secondary" onClick={() => nav("/catalog")}>
            Сменить ситуацию
          </Button>
        </div>
      )}
    </div>
  );
}
