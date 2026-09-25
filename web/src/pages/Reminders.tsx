import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fmtWhen, parseDate } from "../format";
import type { Reminder } from "../types";
import { Header, Toggle, useToast } from "../components/ui";
import { I } from "../icons";

export default function Reminders() {
  const [toast, showToast] = useToast();
  const [rows, setRows] = useState<Reminder[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<Reminder[]>("/api/v1/reminders")
      .then((r) => { setRows(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const toggle = async (id: number) => {
    try {
      const row = await api.post<Reminder>(`/api/v1/reminders/${id}/toggle`);
      setRows((rs) => rs?.map((r) => (r.id === id ? row : r)) ?? rs);
    } catch {
      showToast("Не удалось изменить напоминание");
    }
  };

  const now = Date.now();
  const upcoming = rows?.filter((r) => (parseDate(r.at)?.getTime() ?? 0) >= now) ?? [];
  const past = rows?.filter((r) => (parseDate(r.at)?.getTime() ?? 0) < now) ?? [];

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header
        title="Напоминания"
        right={
          <span className="icon-btn blue" style={{ cursor: "default" }}>
            <I.plus size={22} />
          </span>
        }
      />
      <div className="screen-body">
        {status === "error" && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Не удалось загрузить</h2>
            <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={load}>Повторить</button>
          </div>
        )}
        {status === "loading" && (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        )}
        {status === "ready" && (
          <>
            <div className="section-label">Предстоящие</div>
            {upcoming.length === 0 && <div className="card muted">Предстоящих напоминаний нет.</div>}
            {upcoming.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="badge badge-blue">{fmtWhen(r.at)}</span>
                  <Toggle on={r.enabled} onChange={() => toggle(r.id)} />
                </div>
                <h3 style={{ fontSize: 16, fontWeight: 700 }}>{r.title}</h3>
                {r.place && <p style={{ fontSize: 13, color: "#8E8E93" }}>{r.place}</p>}
              </div>
            ))}
            {past.length > 0 && <div className="section-label">Прошедшие</div>}
            {past.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 8, opacity: 0.75 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="badge badge-gray">{fmtWhen(r.at)}</span>
                  <Toggle on={r.enabled} onChange={() => toggle(r.id)} />
                </div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: "#6B6B6B" }}>{r.title}</h3>
                {r.place && <p style={{ fontSize: 13, color: "#9B9B9B" }}>{r.place}</p>}
              </div>
            ))}
          </>
        )}
      </div>
      {toast}
    </div>
  );
}
