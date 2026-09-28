import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { getInitData } from "../bridge";
import { fmtWhen } from "../format";
import type { HealthReport } from "../types";
import { Button, ErrorView, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";

const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : String(v).replace(".", ","));

export default function Report() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<HealthReport>("/api/v1/health/report")
      .then((r) => { setReport(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  /** Запасной путь (используется только если бот недоступен): каскад share → a.download → ссылка с токеном. */
  const downloadInWebview = async () => {
    const initData = getInitData();
    const resp = await fetch("/api/v1/health/export", {
      headers: initData ? { "X-Max-Init-Data": initData } : undefined,
    });
    if (!resp.ok) throw new Error(String(resp.status));
    const blob = await resp.blob();
    const today = new Date();
    const stamp = `${String(today.getDate()).padStart(2, "0")}.${String(today.getMonth() + 1).padStart(2, "0")}.${today.getFullYear()}`;
    const filename = `medroute-svodka-${stamp}.pdf`;

    const file = new File([blob], filename, { type: "application/pdf" });
    const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean };
    if (typeof nav.canShare === "function" && nav.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: "Сводка для врача" });
        showToast("Готово — PDF отправлен");
        return true;
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return true; // закрыли шер сами
        // шаринг не прошёл — пробуем скачать как обычно
      }
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("PDF скачан");
    return true;
  };

  /** Фолбэк для вебвью: одноразовая ссылка с токеном → открыть в обычном браузере. */
  const copyExportLink = async () => {
    const tok = await api.post<{ token: string }>("/api/v1/health/export-token", {});
    const link = `${window.location.origin}/api/v1/health/export?t=${tok.token}`;
    await navigator.clipboard.writeText(link);
    showToast("Ссылка на PDF скопирована — откройте её в обычном браузере");
  };

  const downloadPdf = async () => {
    setBusy(true);
    try {
      // единый путь для всех устройств: файл доставляет бот в чат
      await api.post("/api/v1/health/send-to-bot", {});
      showToast("Собираю — PDF придёт в чат бота через несколько секунд");
      return;
    } catch {
      showToast("Не удалось отправить в чат — пробуем скачать…");
    }
    // запасной путь (только если бот недоступен): скачивание из браузера
    try {
      await downloadInWebview();
    } catch {
      try {
        await copyExportLink();
      } catch {
        showToast("Не удалось подготовить PDF");
      }
    } finally {
      setBusy(false);
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
          <Button disabled={busy} onClick={downloadPdf}>
            <I.doc size={18} />{busy ? "Готовим…" : "PDF в чат"}
          </Button>
        </div>
      </div>
      {toast}
    </div>
  );
}
