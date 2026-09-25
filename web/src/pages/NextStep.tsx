import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { RouteDto } from "../types";
import { Button, Header } from "../components/ui";
import { I } from "../icons";

export default function NextStep() {
  const nav = useNavigate();
  const [route, setRoute] = useState<RouteDto | null>(null);

  useEffect(() => {
    api.get<RouteDto | null>("/api/v1/route").then(setRoute).catch(() => setRoute(null));
  }, []);

  const step = route?.steps.find((s) => s.status === "current") ?? null;
  const stepNumber = step && route ? route.steps.findIndex((s) => s.id === step.id) + 1 : 0;

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Следующий шаг" subtitle={route?.title ?? undefined} back="/route" />
      <div className="screen-body next-step-body">
        {step && <>
          <div className="card next-step-card">
            <div className="next-step-heading"><div className="circ"><I.calCheck size={40} /></div><div><h2>{step.title}</h2>{step.deadline && <span className="badge badge-yellow">Срок: {fmtDeadline(step.deadline, step.deadline_time)}</span>}</div></div>
            {step.description && <p className="muted">{step.description}</p>}
            <div className="route-stats"><span>Шаг<strong>{stepNumber} из {route?.total_steps}</strong></span><span>Статус<strong>{fmtDeadline(step.deadline, step.deadline_time) || "Текущий"}</strong></span></div>
          </div>
          {step.place && <div className="card"><h3 className="h3">Где пройти</h3><p className="kv" style={{ marginTop: 12 }}><I.pin size={18} />{step.place}</p></div>}
          {step.has_checklist && <div className="card"><h3 className="h3">Что взять с собой</h3><Button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => nav("/checklist")}>Открыть чек-лист</Button></div>}
        </>}
      </div>
      <div className="foot">
        {step && <Button className="btn btn-primary" onClick={() => nav(`/step/${step.id}`)}>Открыть</Button>}
        <Button className="btn btn-secondary" onClick={() => nav("/route")}>К маршруту</Button>
      </div>
    </div>
  );
}
