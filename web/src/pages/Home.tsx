import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline, fmtWhen } from "../format";
import type { HealthRecord, MedsOut, Reminder, RouteDto } from "../types";
import { useApp } from "../App";
import { ErrorView, LoadingView, RootHeader } from "../components/ui";
import { I } from "../icons";

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

export default function Home() {
  const nav = useNavigate();
  const { user } = useApp();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [meds, setMeds] = useState<MedsOut | null>(null);
  const [bp, setBp] = useState<HealthRecord | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    Promise.allSettled([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Reminder[]>("/api/v1/reminders"),
      api.get<MedsOut>("/api/v1/meds"),
      api.get<HealthRecord[]>("/api/v1/health/bp/records?limit=1"),
    ])
      .then(([r, rem, m, b]) => {
        setRoute(r.status === "fulfilled" ? r.value : null);
        setReminders(rem.status === "fulfilled" ? rem.value : []);
        setMeds(m.status === "fulfilled" ? m.value : null);
        setBp(b.status === "fulfilled" && b.value.length ? b.value[0] : null);
        setStatus("ready");
      });
  }, []);

  useEffect(load, []);

  if (status === "error") {
    return (
      <div className="app">
        <RootHeader name={`${user.first_name} ${user.last_name}`} url={user.avatar_url} onProfile={() => nav("/profile")} />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const now = new Date();
  const dateLine = `${WEEKDAYS[now.getDay()]}, ${now.getDate()} ${MONTHS[now.getMonth()]}`;
  const nextStep = route?.steps.find((s) => s.status === "current") ?? null;
  const upcoming = reminders.filter((r) => r.enabled).slice(0, 3);
  const nextMed = meds?.today.find((s) => !s.taken) ?? null;
  const docsDone = null; // чек-лист считаем на маршруте; на плитке — без значения

  const empty = route === null;

  return (
    <div className="app">
      <RootHeader name={`${user.first_name} ${user.last_name}`} url={user.avatar_url} onProfile={() => nav("/profile")} />
      <div className="screen-body">
        {status === "loading" && (
          <LoadingView />
        )}

        {status === "ready" && (
          <>
            <div className="greeting">
              <h2>Здравствуйте, {user.first_name}</h2>
              <p>{dateLine}</p>
            </div>
            <div className="split">
              <div className="col">
                <div className="section-h">
                  <b>Маршрут</b>
                  {!empty && <button onClick={() => nav("/route")}>Открыть</button>}
                </div>
                {empty ? (
                  <div className="card hero tinted press" onClick={() => nav("/builder")}>
                    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                      <div className="cta-ic"><I.plus size={22} /></div>
                      <div>
                        <b style={{ color: "var(--blue)", fontSize: 16 }}>Выберите свою первую ситуацию</b>
                        <div className="muted" style={{ marginTop: 4 }}>
                          Например, «Подготовка к приёму у врача» — и маршрут появится здесь, шаг за шагом.
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="card hero route-status press" onClick={() => nav("/route")}>
                    <div className="label"><span>{route!.title}</span></div>
                    <div className="big-nums">
                      <span className="n">{route!.done_steps}</span>
                      <span className="of">из {route!.total_steps} шагов</span>
                    </div>
                    <div className="progress"><i style={{ width: `${Math.round((route!.done_steps / route!.total_steps) * 100)}%` }} /></div>
                    {nextStep && (
                      <div className="next">
                        <span className="dot" />
                        Дальше: {nextStep.title.toLowerCase()}
                        {nextStep.deadline && <small>· {fmtDeadline(nextStep.deadline, nextStep.deadline_time)}</small>}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="col">
                <div className="section-h">
                  <b>Напоминания</b>
                  {!empty && <button onClick={() => nav("/reminders")}>Все</button>}
                </div>
                {upcoming.length === 0 ? (
                  <div className="card empty-card">
                    <div className="empty-ico"><I.bell size={20} /></div>
                    <b style={{ fontSize: 14.5 }}>Пока тихо</b>
                    <div className="muted">
                      {empty
                        ? "Напоминания появятся после первого шага маршрута — бот пришлёт их прямо в MAX."
                        : "Все напоминания выключены или уже прошли."}
                    </div>
                  </div>
                ) : (
                  <div className="card" style={{ padding: "8px 16px" }}>
                    {upcoming.map((r) => {
                      const d = new Date(r.at);
                      const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
                      const sameDay = d.toDateString() === now.toDateString();
                      return (
                        <div className="rem-item" key={r.id}>
                          <div className="when">
                            {sameDay ? (
                              hhmm
                            ) : (
                              <>
                                {d.getDate()} {MONTHS[d.getMonth()]}
                                <br />
                                {hhmm}
                              </>
                            )}
                          </div>
                          <div className="what">
                            <b>{r.title}</b>
                            <small>{r.place || fmtWhen(r.at)}</small>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        <div className="section-h"><b>Быстрый доступ</b></div>
        <div className="tiles">
          <button className="tile" onClick={() => nav("/route")}>
            {docsDone}
            <div className="ic b"><I.clipboard size={20} /></div>
            <b>Документы</b><span>для приёма</span>
          </button>
          <button className="tile" onClick={() => nav("/orgs")}>
            <div className="ic r"><I.building size={20} /></div>
            <b>Организации</b><span>поликлиники рядом</span>
          </button>
          <button className="tile" onClick={() => nav("/meds")}>
            {nextMed && <span className="val">{nextMed.at_time}</span>}
            <div className="ic r"><I.pill size={20} /></div>
            <b>Приём лекарств</b><span>{nextMed ? "следующий приём" : "добавьте курс"}</span>
          </button>
          <button className="tile" onClick={() => nav("/health")}>
            {bp && bp.systolic !== null && <span className="val">{bp.systolic}/{bp.diastolic}</span>}
            <div className="ic g"><I.pulse size={20} /></div>
            <b>Дневник здоровья</b><span>{bp ? fmtWhen(bp.at) : "настроить под себя"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
