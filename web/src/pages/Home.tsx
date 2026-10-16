import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useNow } from "../hooks/useNow";
import { deadlineCountdown, fmtDeadline, fmtWhen } from "../format";
import type { HealthRecord, MedsOut, Reminder, RouteDto } from "../types";
import { useApp } from "../App";
import { Button, ErrorView, LoadingView, RootHeader } from "../components/ui";
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
  const now = useNow();

  const load = useCallback(() => {
    setStatus("loading");
    Promise.allSettled([
      api.get<RouteDto | null>("/api/v1/route"),
      api.get<Reminder[]>("/api/v1/reminders"),
      api.get<MedsOut>("/api/v1/meds"),
      api.get<HealthRecord[]>("/api/v1/health/bp/records?limit=1"),
    ])
      .then(([r, rem, m, b]) => {
        if (r.status === "rejected") {
          setStatus("error");
          return;
        }
        setRoute(r.value);
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

  const dateLine = `${WEEKDAYS[now.getDay()]}, ${now.getDate()} ${MONTHS[now.getMonth()]}`;
  const nextStep = route?.steps.find((s) => s.status === "current")
    ?? route?.steps.find((s) => s.status === "pending") ?? null;
  const countdown = deadlineCountdown(nextStep?.deadline, nextStep?.deadline_time, user.tz, now);
  const finished = route !== null && route.total_steps > 0 && route.done_steps === route.total_steps;
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
            <section className={`card home-focus${nextStep && countdown.overdue ? " is-overdue" : ""}`} aria-labelledby="home-focus-title">
              <div className="home-focus-top">
                <p className="home-focus-label">Главное сейчас</p>
                <span className={`badge badge-${finished ? "green" : nextStep && countdown.overdue ? "red" : "blue"}`}>
                  {nextStep ? nextStep.status === "current" ? "Текущий шаг" : "Следующий шаг"
                    : finished ? "Маршрут завершён" : route ? "Маршрут создан" : "Начало маршрута"}
                </span>
              </div>
              <h2 id="home-focus-title">
                {nextStep?.title ?? (finished ? "Все шаги пройдены" : route ? "Добавьте первый шаг" : "Выберите свою первую ситуацию")}
              </h2>
              {nextStep ? (
                <>
                  <p className="home-focus-deadline">
                    {nextStep.deadline && <span>{fmtDeadline(nextStep.deadline, nextStep.deadline_time)}</span>}
                    <strong>{countdown.text}</strong>
                  </p>
                  <p className="muted">{route!.title} · Шаг {nextStep.position} из {route!.total_steps}</p>
                </>
              ) : (
                <p className="muted">
                  {finished ? "Можно выбрать новую ситуацию и построить следующий маршрут."
                    : route ? "Добавьте свои назначения или дела, чтобы начать движение по маршруту."
                      : "Выберите шаблон или создайте свой маршрут — здесь появятся следующий шаг и его срок."}
                </p>
              )}
              <Button onClick={() => nav(nextStep ? `/step/${nextStep.id}` : finished || !route ? "/builder" : "/route")}>
                {nextStep ? "Открыть шаг" : finished ? "Создать новый маршрут" : route ? "Открыть маршрут" : "Создать маршрут"}
              </Button>
            </section>
            <div className="split">
              <div className="col">
                <div className="section-h">
                  <b>Маршрут</b>
                  {!empty && <button onClick={() => nav("/route")}>Открыть</button>}
                </div>
                {empty ? (
                  <div className="card muted">После создания маршрута здесь появится прогресс выполнения.</div>
                ) : (
                  <div className="card route-status home-route-summary press" onClick={() => nav("/route")}>
                    <div className="label"><span>{route!.title}</span></div>
                    <div className="big-nums">
                      <span className="n">{route!.done_steps}</span>
                      <span className="of">из {route!.total_steps} шагов</span>
                    </div>
                    <div className="progress"><i style={{ width: `${route!.total_steps ? Math.round((route!.done_steps / route!.total_steps) * 100) : 0}%` }} /></div>
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
