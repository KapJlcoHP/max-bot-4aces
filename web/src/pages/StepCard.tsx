import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { fmtDeadline, fmtDayMonth } from "../format";
import type { CompleteStepResult, RouteDto } from "../types";
import { Button, Header, useToast } from "../components/ui";
import { I } from "../icons";

export default function StepCard() {
  const { stepId } = useParams();
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [route, setRoute] = useState<RouteDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sheet, setSheet] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setStatus("loading");
    api.get<RouteDto | null>("/api/v1/route")
      .then((r) => { setRoute(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  };
  useEffect(load, [stepId]);

  const step = useMemo(() => route?.steps.find((s) => String(s.id) === stepId) ?? null, [route, stepId]);

  const remind = async () => {
    if (!step) return;
    try {
      await api.post("/api/v1/reminders", { title: step.title, place: step.place });
      showToast("Напоминание создано — смотрите раздел «Напоминания»");
    } catch (e) {
      showToast("Не удалось создать напоминание");
    }
  };

  const complete = async () => {
    if (!step) return;
    setBusy(true);
    try {
      const res = await api.post<CompleteStepResult>(`/api/v1/route/steps/${step.id}/complete`, {
        note: note || null,
      });
      setSheet(false);
      if (res.next_step) nav("/next-step");
      else nav("/route"); // маршрут завершён — там экран-поздравление
    } catch {
      showToast("Не удалось отметить шаг");
    } finally {
      setBusy(false);
    }
  };

  if (status === "error") {
    return (
      <div className="app" style={{ display: "flex", flexDirection: "column" }}>
        <Header title="Шаг" back="/route" />
        <div className="state-wrap">
          <div className="alert-circle"><I.alert size={30} /></div>
          <h2>Ошибка загрузки</h2>
          <Button className="btn btn-primary" onClick={load}>Повторить</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title={step ? `Шаг: ${step.title}` : "Шаг"} back="/route" />
      <div className="screen-body">
        {status === "loading" || !step ? (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        ) : (
          <>
            <div className="card">
              <h3 className="h3">Когда и где</h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                {step.deadline && (
                  <p className="kv"><I.cal size={18} />Срок: {fmtDeadline(step.deadline, step.deadline_time)}</p>
                )}
                {step.place && <p className="kv"><I.pin size={18} />{step.place}</p>}
              </div>
            </div>
            {step.description && (
              <div className="card">
                <h3 className="h3">Что нужно сделать</h3>
                <p className="muted" style={{ marginTop: 10 }}>{step.description}</p>
              </div>
            )}
            {step.has_checklist && (
              <>
                <button className="row-item" onClick={() => nav("/checklist")}>
                  <div className="row-ico"><I.doc /></div>
                  <div className="row-body"><h3>Чек-лист документов</h3><p>Отметьте собранные документы к этому шагу</p></div>
                  <span className="row-chev"><I.chev size={20} /></span>
                </button>
                <button className="row-item" onClick={() => nav("/prep")}>
                  <div className="row-ico"><I.calCheck /></div>
                  <div className="row-body"><h3>Подготовка к приёму</h3><p>Вещи и вопросы врачу</p></div>
                  <span className="row-chev"><I.chev size={20} /></span>
                </button>
              </>
            )}
            {step.note && (
              <div className="card">
                <h3 className="h3">Ваша заметка</h3>
                <p className="muted" style={{ marginTop: 8 }}>{step.note}</p>
              </div>
            )}
          </>
        )}
      </div>

      {step && step.status !== "done" && (
        <div className="foot">
          <div className="btn-row">
            <Button className="btn btn-secondary" onClick={remind}>
              <I.bell size={18} />Напомнить
            </Button>
            <Button className="btn btn-primary" onClick={() => setSheet(true)}>
              <I.check size={18} />Выполнено
            </Button>
          </div>
        </div>
      )}

      {sheet && (
        <div className="sheet-overlay" onClick={(e) => { if (e.target === e.currentTarget) setSheet(false); }}>
          <div className="sheet">
            <div className="grab" />
            <div style={{ display: "flex", justifyContent: "center", marginTop: 6 }}>
              <div style={{ width: 64, height: 64, borderRadius: "50%", background: "#DFF5E6", display: "flex", alignItems: "center", justifyContent: "center", color: "#22C55E" }}>
                <I.check size={28} />
              </div>
            </div>
            <h2>Шаг выполнен?</h2>
            <p className="sub">Подтвердите, что вы завершили шаг «{step?.title}». Это переведёт вас к следующему шагу маршрута.</p>
            <div className="field" style={{ color: "#9B9B9B" }}>
              Дата: {fmtDayMonth(new Date().toISOString())} — отметим сегодняшней
            </div>
            <div className="field">
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Заметка (опционально)…" />
            </div>
            <div className="btn-row" style={{ marginTop: 4 }}>
              <Button className="btn btn-secondary" onClick={() => setSheet(false)}>Отмена</Button>
              <Button className="btn btn-primary" disabled={busy} onClick={complete}>
                {busy ? "Сохраняем…" : "Подтвердить"}
              </Button>
            </div>
          </div>
        </div>
      )}
      {toast}
    </div>
  );
}
