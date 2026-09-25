import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { RouteDto } from "../types";
import { useApp } from "../App";
import { Button, ErrorView, HomeHeader } from "../components/ui";
import { I } from "../icons";

export default function Dashboard() {
  const nav = useNavigate();
  const { user } = useApp();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<RouteDto | null>("/api/v1/route")
      .then((r) => {
        setRoute(r);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  if (status === "error") {
    return (
      <div className="app" style={{ display: "flex", flexDirection: "column" }}>
        <HomeHeader onBell={() => nav("/reminders")} />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const nextStep = route?.steps.find((s) => s.status === "current") ?? null;
  const percent = route && route.total_steps > 0 ? Math.round((route.done_steps / route.total_steps) * 100) : 0;

  return (
    <>
      <HomeHeader onBell={() => nav("/reminders")} />
      <div className="screen-body dashboard-body">
        <h2 className="dashboard-greeting">Здравствуйте, {user.first_name}</h2>
        {status === "loading" ? (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        ) : route === null ? (
          <div className="card" style={{ padding: 32, textAlign: "center" }}>
            <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
              <I.route size={64} />
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>У вас пока нет маршрутов</h2>
            <p className="muted" style={{ marginTop: 6 }}>
              Выберите жизненную ситуацию, чтобы построить оптимальный маршрут
            </p>
            <Button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => nav("/catalog")}>
              Выбрать ситуацию
            </Button>
          </div>
        ) : (
          <>
            <div className="card press dashboard-progress" onClick={() => nav("/route")}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 13, color: "#8E8E93" }}>Ваш прогресс маршрута</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#2563EB" }}>
                  {route.done_steps} из {route.total_steps} выполнено
                </span>
              </div>
              <div className="progress" style={{ marginTop: 12 }}>
                <i style={{ width: `${percent}%` }} />
              </div>
              <p className="dashboard-route-status" style={{ fontSize: 13, color: "#8E8E93", marginTop: 12, display: "flex", alignItems: "center", gap: 6 }}>
                <i style={{ width: 8, height: 8, borderRadius: "50%", background: "#22C55E", display: "inline-block" }} />
                Маршрут активен&nbsp;&nbsp;•&nbsp;&nbsp;{route.title}
              </p>
            </div>

            {nextStep && (
              <div className="card dashboard-next">
                <span className="badge badge-blue">СЛЕДУЮЩИЙ ШАГ</span>
                <h3 style={{ fontSize: 18, fontWeight: 700, marginTop: 10 }}>{nextStep.title}</h3>
                {nextStep.deadline && (
                  <p className="kv" style={{ marginTop: 8, color: "#8E8E93" }}>
                    <I.cal size={17} />
                    Срок: {fmtDeadline(nextStep.deadline, nextStep.deadline_time)}
                  </p>
                )}
                <Button className="btn btn-primary" style={{ marginTop: 14 }} onClick={() => nav(`/step/${nextStep.id}`)}>
                  Открыть шаг
                </Button>
              </div>
            )}
          </>
        )}

      </div>
    </>
  );
}
