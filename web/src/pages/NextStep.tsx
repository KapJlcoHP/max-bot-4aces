import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline } from "../format";
import type { RouteDto } from "../types";
import { Header } from "../components/ui";
import { I } from "../icons";

export default function NextStep() {
  const nav = useNavigate();
  const [route, setRoute] = useState<RouteDto | null>(null);

  useEffect(() => {
    api.get<RouteDto | null>("/api/v1/route").then(setRoute).catch(() => setRoute(null));
  }, []);

  const step = route?.steps.find((s) => s.status === "current") ?? null;

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Следующий шаг" back="/route" />
      <div className="screen-body center">
        <div className="circ"><I.calCheck size={44} /></div>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginTop: 18 }}>{step ? step.title : "Маршрут завершён"}</h2>
        {step?.deadline && <span className="badge badge-yellow" style={{ marginTop: 8 }}>Срок: {fmtDeadline(step.deadline, step.deadline_time)}</span>}
        {step?.description && (
          <p className="muted" style={{ fontSize: 14.5, marginTop: 14, maxWidth: 320 }}>{step.description}</p>
        )}
        {step?.place && <p className="kv" style={{ marginTop: 10 }}><I.pin size={17} />{step.place}</p>}
      </div>
      <div className="foot">
        {step && <button className="btn btn-primary" onClick={() => nav(`/step/${step.id}`)}>Открыть</button>}
        <button className="btn btn-secondary" onClick={() => nav("/route")}>К маршруту</button>
      </div>
    </div>
  );
}
