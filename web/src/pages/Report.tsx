import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { fmtDayMonth, fmtWhen } from "../format";
import type { HealthReport } from "../types";
import { Button, ErrorView, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";

const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : String(v).replace(".", ","));

export default function Report() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<HealthReport>("/api/v1/health/report")
      .then((r) => { setReport(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const share = async () => {
    const r = report;
    if (!r) return;
    const lines: string[] = ["Сводка «МедМаршрут» за 30 дней:"];
    if (r.bp_avg) lines.push(`Давление: ${r.bp_avg} среднее (${r.bp_count} измерений${r.pulse_avg ? `, пульс ~${r.pulse_avg}` : ""})`);
    if (r.weight_latest) lines.push(`Вес: ${num(r.weight_latest)} кг (${r.weight_delta !== null && r.weight_delta !== undefined ? (r.weight_delta > 0 ? "+" : "") + num(r.weight_delta) : "0"} кг за период)`);
    if (r.sugar_avg) lines.push(`Сахар: ${num(r.sugar_avg)} ммоль/л среднее (${r.sugar_count} измерений)`);
    if (r.meds.length) lines.push("Лекарства: " + r.meds.map((m) => `${m.name} — ${m.taken}/${m.planned} (${m.pct}%)`).join("; "));
    if (r.notes.length) lines.push("Заметки: " + r.notes.map((n) => `«${n.note}» (${fmtDayMonth(n.at)})`).join("; "));
    const text = lines.join("\n");
    try {
      await navigator.clipboard.writeText(text);
      showToast("Сводка скопирована — можно вставить врачу в чат");
    } catch {
      showToast("Не удалось скопировать");
    }
  };

  if (status === "error") {
    return (
      <div className="app narrow">
        <Header title="Сводка для врача" back="/health" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  return (
    <div className="app narrow">
      <Header title="Сводка для врача" subtitle="Только факты за 30 дней" back="/health" />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "ready" && report && (
          <>
            {report.bp_avg && (
              <div className="card">
                <b style={{ fontSize: 15 }}>Давление и пульс</b>
                <div className="big-nums" style={{ margin: "8px 0 4px" }}>
                  <span className="n" style={{ fontSize: 30 }}>{report.bp_avg}</span>
                  <span className="of">среднее</span>
                </div>
                <div className="muted" style={{ fontSize: 13 }}>
                  {report.bp_count} измерений{report.pulse_avg ? ` · пульс в среднем ${report.pulse_avg} уд/мин` : ""}
                </div>
              </div>
            )}
            {report.weight_latest && (
              <div className="card">
                <b style={{ fontSize: 15 }}>Вес</b>
                <div style={{ marginTop: 6, fontSize: 14.5, fontWeight: 600 }}>
                  {num(report.weight_latest)} кг
                  {report.weight_delta !== null && report.weight_delta !== undefined && (
                    <span style={{ color: "var(--muted)" }}> · {report.weight_delta > 0 ? "+" : ""}{num(report.weight_delta)} кг за период</span>
                  )}
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>{report.weight_count} измерений</div>
              </div>
            )}
            {report.sugar_avg && (
              <div className="card">
                <b style={{ fontSize: 15 }}>Сахар крови</b>
                <div style={{ marginTop: 6, fontSize: 14.5, fontWeight: 600 }}>
                  {num(report.sugar_avg)} ммоль/л — среднее
                  <span style={{ color: "var(--muted)", fontWeight: 500 }}> · {report.sugar_count} измерений</span>
                </div>
              </div>
            )}
            {report.meds.length > 0 && (
              <div className="card">
                <b style={{ fontSize: 15 }}>Приём лекарств</b>
                {report.meds.map((m) => (
                  <div className="rem-item" key={m.name}>
                    <div className="what"><b>{m.name}</b><small>принято {m.taken} из {m.planned} · {m.pct}%</small></div>
                  </div>
                ))}
              </div>
            )}
            {report.notes.length > 0 && (
              <div className="card">
                <b style={{ fontSize: 15 }}>Заметки о самочувствии</b>
                {report.notes.map((n, i) => (
                  <div className="rem-item" key={i}>
                    <div className="what"><b>«{n.note}»</b><small>{fmtWhen(n.at)}</small></div>
                  </div>
                ))}
              </div>
            )}
            {!report.bp_avg && !report.weight_latest && !report.sugar_avg && report.meds.length === 0 && (
              <div className="empty-card">
                <b style={{ fontSize: 15 }}>Пока нечего показывать</b>
                <div className="muted">Записи дневников и приёмы лекарств появятся в сводке по мере накопления.</div>
              </div>
            )}
          </>
        )}
      </div>
      <div className="foot">
        <div className="btn-row">
          <Button variant="secondary" onClick={() => nav("/health")}><I.back size={18} />Назад</Button>
          <Button onClick={share}><I.share size={18} />Показать врачу</Button>
        </div>
      </div>
      {toast}
    </div>
  );
}
