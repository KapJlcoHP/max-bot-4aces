import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import type { FamilySnapshot } from "../types";
import { Badge, BrandMark, ErrorView, Header, LoadingView } from "../components/ui";
import { fmtDeadline, fmtWhen } from "../format";
import { I } from "../icons";

const statusLabel: Record<string, string> = { done: "Готово", current: "Сейчас", pending: "Далее" };

export default function FamilyView() {
  const { accessId } = useParams();
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<FamilySnapshot | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    if (!accessId) return;
    setStatus("loading");
    api.get<FamilySnapshot>(`/api/v1/family/observed/${accessId}`)
      .then((value) => { setSnapshot(value); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, [accessId]);

  useEffect(load, [load]);

  return (
    <div className="app narrow">
      <Header title={snapshot ? `Маршрут ${snapshot.owner_name}` : "Маршрут близкого"} subtitle="Только просмотр" back="/family" right={<BrandMark />} />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "error" && <ErrorView onRetry={load} />}
        {status === "ready" && snapshot && (
          <>
            <div className="card family-readonly-banner">
              <I.shield size={22} />
              <div><b>Режим только для чтения</b><p className="muted">Изменять маршрут, дневники и лекарства может только владелец.</p></div>
            </div>

            {snapshot.route ? (
              <>
                <div className="family-route-summary card">
                  <div><h2>{snapshot.route.title}</h2><p className="muted">{snapshot.route.done_steps} из {snapshot.route.total_steps} шагов выполнено</p></div>
                  <div className="family-progress" aria-label={`Выполнено ${snapshot.route.done_steps} из ${snapshot.route.total_steps}`}><span style={{ width: `${snapshot.route.total_steps ? Math.round(snapshot.route.done_steps / snapshot.route.total_steps * 100) : 0}%` }} /></div>
                </div>
                <div className="section-h"><b>Шаги маршрута</b></div>
                <div className="family-step-list">
                  {snapshot.route.steps.map((step) => (
                    <div className={`card family-step-card family-step-${step.status}`} key={step.id}>
                      <div className="family-step-marker">{step.status === "done" ? <I.check size={17} /> : step.position}</div>
                      <div className="row-body">
                        <div className="family-step-top"><h3>{step.title}</h3><Badge color={step.status === "done" ? "green" : step.status === "current" ? "blue" : "gray"}>{statusLabel[step.status] ?? step.status}</Badge></div>
                        {(step.appointment_date || step.deadline) && <p className="muted"><I.cal size={14} /> {step.appointment_date ? `Приём: ${fmtDeadline(step.appointment_date, null)}` : fmtDeadline(step.deadline, step.deadline_time)}</p>}
                        {step.place && <p className="muted"><I.pin size={14} /> {step.place}</p>}
                        {step.completed_at && <p className="cell-note">Отмечено: {fmtWhen(step.completed_at)}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : <div className="card muted">У владельца пока нет активного маршрута.</div>}

            <div className="section-h"><b>Статусы</b></div>
            <div className="card family-status-list">
              {snapshot.diaries.filter((item) => item.enabled).map((item) => (
                <div className="family-status-row" key={item.diary}><span>{item.label}</span><span className={item.filled_today ? "status-ok" : "muted"}>{item.filled_today ? "Сегодня заполнен" : "Сегодня не заполнен"}</span></div>
              ))}
              <div className="family-status-row"><span>Лекарства</span><span className={snapshot.medication.planned_today === snapshot.medication.taken_today && snapshot.medication.planned_today > 0 ? "status-ok" : "muted"}>{snapshot.medication.planned_today ? `${snapshot.medication.taken_today} из ${snapshot.medication.planned_today} отмечено сегодня` : "На сегодня нет активных приёмов"}</span></div>
            </div>
            <p className="family-updated">Обновлено: {fmtWhen(snapshot.generated_at)}</p>
          </>
        )}
      </div>
    </div>
  );
}
