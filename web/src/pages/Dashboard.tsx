import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline, fmtWhen, parseDate } from "../format";
import type { Reminder, RouteDto } from "../types";
import { ErrorView, HomeHeader } from "../components/ui";
import { I, SituationIcon } from "../icons";

export default function Dashboard() {
  const nav = useNavigate();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [firstName, setFirstName] = useState("Анна");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Reminder[]>("/api/v1/reminders"),
      api.get<import("../types").UserDto>("/api/v1/me"),
    ])
      .then(([r, rems, me]) => {
        setRoute(r);
        setReminders(rems);
        setFirstName(me.first_name);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  if (status === "error") {
    return (
      <div className="app" style={{ display: "flex", flexDirection: "column" }}>
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const now = Date.now();
  const upcoming = reminders
    .filter((r) => r.enabled && (parseDate(r.at)?.getTime() ?? 0) >= now)
    .slice(0, 3);

  const nextStep = route?.steps.find((s) => s.status === "current") ?? null;
  const percent = route && route.total_steps > 0 ? Math.round((route.done_steps / route.total_steps) * 100) : 0;

  return (
    <>
      <HomeHeader firstName={firstName} onBell={() => nav("/reminders")} />
      <div className="screen-body">
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
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => nav("/catalog")}>
              Выбрать ситуацию
            </button>
          </div>
        ) : (
          <>
            <div className="card press" onClick={() => nav("/route")}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontSize: 13, color: "#8E8E93" }}>Ваш прогресс маршрута</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#2563EB" }}>
                  {route.done_steps} из {route.total_steps} выполнено
                </span>
              </div>
              <div className="progress" style={{ marginTop: 12 }}>
                <i style={{ width: `${percent}%` }} />
              </div>
              <p style={{ fontSize: 13, color: "#8E8E93", marginTop: 12, display: "flex", alignItems: "center", gap: 6 }}>
                <i style={{ width: 8, height: 8, borderRadius: "50%", background: "#22C55E", display: "inline-block" }} />
                Маршрут активен&nbsp;&nbsp;•&nbsp;&nbsp;{route.title}
              </p>
            </div>

            {nextStep && (
              <div className="card">
                <span className="badge badge-blue">СЛЕДУЮЩИЙ ШАГ</span>
                <h3 style={{ fontSize: 18, fontWeight: 700, marginTop: 10 }}>{nextStep.title}</h3>
                {nextStep.deadline && (
                  <p className="kv" style={{ marginTop: 8, color: "#8E8E93" }}>
                    <I.cal size={17} />
                    Срок: {fmtDeadline(nextStep.deadline, nextStep.deadline_time)}
                  </p>
                )}
                <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={() => nav(`/step/${nextStep.id}`)}>
                  Открыть шаг
                </button>
              </div>
            )}
          </>
        )}

        {status === "ready" && (
          <>
            <div className="section-label">Ближайшие события</div>
            {upcoming.length === 0 ? (
              <div className="card muted">Запланированных событий нет. Напоминания появятся тут.</div>
            ) : (
              upcoming.map((r) => (
                <div key={r.id} className="card press" style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 14px" }} onClick={() => nav("/reminders")}>
                  <span className="badge badge-blue">{fmtWhen(r.at)}</span>
                  <span style={{ flex: 1, fontSize: 13.5, lineHeight: 1.35 }}>{r.title}</span>
                </div>
              ))
            )}
            <div className="card press" style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 14px" }} onClick={() => nav("/catalog")}>
              <div className="row-ico" style={{ width: 40, height: 40 }}>
                <SituationIcon name="plus" size={20} />
              </div>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>Выбрать новую ситуацию</span>
              <I.chev size={20} />
            </div>
          </>
        )}
      </div>
    </>
  );
}
