import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Input } from "@maxhub/max-ui";
import { useNavigate } from "react-router-dom";
import { fmtDeadline, fmtWhen, parseDate } from "../format";
import type { Reminder, RouteDto } from "../types";
import { Button, Header, LoadingView, Switch, useToast } from "../components/ui";
import { I } from "../icons";

export default function Reminders() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [rows, setRows] = useState<Reminder[] | null>(null);
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ title: "", place: "", at: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<Reminder[]>("/api/v1/reminders")
      .then((r) => { setRows(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
    api.get<RouteDto | null>("/api/v1/route").then(setRoute).catch(() => setRoute(null));
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

  const add = async () => {
    if (!draft.title.trim() || !draft.at || busy) { showToast("Укажите событие и время"); return; }
    setBusy(true);
    try {
      const row = await api.post<Reminder>("/api/v1/reminders", draft);
      setRows((current) => [...(current ?? []), row].sort((a, b) => a.at.localeCompare(b.at)));
      setDraft({ title: "", place: "", at: "" });
      setAdding(false);
      showToast("Напоминание добавлено");
    } catch {
      showToast("Не удалось добавить напоминание");
    } finally {
      setBusy(false);
    }
  };

  const now = Date.now();
  const upcoming = rows?.filter((r) => (parseDate(r.at)?.getTime() ?? 0) >= now) ?? [];
  const past = rows?.filter((r) => (parseDate(r.at)?.getTime() ?? 0) < now) ?? [];
  const nextStep = route?.steps.find((s) => s.status === "current");

  return (
    <div className="app">
      <Header title="Напоминания" subtitle="Ближайшие события маршрута" back="/" right={<button className="avatar" onClick={() => setAdding(true)} aria-label="Добавить"><I.plus size={18} /></button>} />
      <div className="screen-body">
        
        {adding && <div className="card reminder-form">
          <h3 className="h3">Новое напоминание</h3>
          <Input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Событие" aria-label="Событие" />
          <Input value={draft.place} onChange={(e) => setDraft({ ...draft, place: e.target.value })} placeholder="Место" aria-label="Место" />
          <input className="date-field" type="datetime-local" value={draft.at} onChange={(e) => setDraft({ ...draft, at: e.target.value })} aria-label="Дата и время" />
          <div className="btn-row"><Button variant="secondary" onClick={() => setAdding(false)}>Отмена</Button><Button onClick={add} disabled={busy}>Сохранить</Button></div>
        </div>}
        {status === "error" && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Не удалось загрузить</h2>
            <Button style={{ marginTop: 14 }} onClick={load}>Повторить</Button>
          </div>
        )}
        {status === "loading" && <LoadingView />}
        {status === "ready" && (
          <>
            {nextStep && <div className="card dashboard-next"><span className="badge badge-blue">СЛЕДУЮЩИЙ ШАГ</span><h3 className="h3" style={{ marginTop: 12 }}>{nextStep.title}</h3>{nextStep.deadline && <p className="muted">Срок: {fmtDeadline(nextStep.deadline, nextStep.deadline_time)}</p>}<Button style={{ marginTop: 14 }} onClick={() => nav(`/step/${nextStep.id}`)}>Открыть шаг</Button></div>}
            <div className="section-h"><b>Предстоящие</b></div>
            {upcoming.length === 0 && <div className="card muted">Предстоящих напоминаний нет.</div>}
            {upcoming.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="badge badge-blue">{fmtWhen(r.at)}</span>
                  <Switch on={r.enabled} onChange={() => toggle(r.id)} />
                </div>
                <h3 style={{ fontSize: 16, fontWeight: 700 }}>{r.title}</h3>
                {r.place && <p style={{ fontSize: 13, color: "#8E8E93" }}>{r.place}</p>}
              </div>
            ))}
            {past.length > 0 && <div className="section-h"><b>Прошедшие</b></div>}
            {past.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 8, opacity: 0.75 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span className="badge badge-gray">{fmtWhen(r.at)}</span>
                  <Switch on={r.enabled} onChange={() => toggle(r.id)} />
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
