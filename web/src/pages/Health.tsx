import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { fmtWhen, parseDate } from "../format";
import type { BpRecord } from "../types";
import { Button, Badge, BrandMark, Header, useToast } from "../components/ui";
import { I } from "../icons";

function Chart({ records }: { records: BpRecord[] }) {
  // Записи за последние 14 дней в хронологическом порядке.
  const pts = useMemo(
    () => [...records].filter((r) => (parseDate(r.at)?.getTime() ?? 0) >= Date.now() - 14 * 86400000).reverse(),
    [records],
  );
  if (pts.length < 2) return <div className="muted" style={{ marginTop: 10 }}>Нужно минимум две записи для графика.</div>;

  const W = 320, H = 150, PAD = 14;
  const values = pts.flatMap((r) => [r.systolic, r.diastolic]);
  const min = Math.max(0, Math.min(...values) - 10);
  const max = Math.max(...values) + 10;
  const xs = (i: number) => PAD + (i * (W - 2 * PAD)) / (pts.length - 1);
  const ys = (v: number) => H - 20 - ((v - min) * (H - 40)) / (max - min);
  const line = (get: (r: BpRecord) => number) => pts.map((r, i) => `${xs(i)},${ys(get(r))}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", marginTop: 10 }}>
      {[35, 75, 115].map((y) => (
        <line key={y} x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="#E7E7EA" strokeDasharray="3 4" />
      ))}
      <polyline points={line((r) => r.systolic)} fill="none" stroke="#2563EB" strokeWidth="2.5" strokeLinejoin="round" />
      <polyline points={line((r) => r.diastolic)} fill="none" stroke="#8B5CF6" strokeWidth="2.5" strokeLinejoin="round" />
      {pts.map((r, i) => (
        <g key={r.id}>
          <circle cx={xs(i)} cy={ys(r.systolic)} r="3.2" fill="#2563EB" />
          <circle cx={xs(i)} cy={ys(r.diastolic)} r="3.2" fill="#8B5CF6" />
        </g>
      ))}
    </svg>
  );
}

export default function Health() {
  const [toast, showToast] = useToast();
  const [rows, setRows] = useState<BpRecord[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [form, setForm] = useState({ sys: "", dia: "", pulse: "" });
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<BpRecord[]>("/api/v1/health/records")
      .then((r) => { setRows(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const add = async () => {
    const sys = Number(form.sys), dia = Number(form.dia), pulse = Number(form.pulse);
    if (!sys || !dia || !pulse) { showToast("Заполните все показатели"); return; }
    setBusy(true);
    try {
      const rec = await api.post<BpRecord>("/api/v1/health/records", {
        systolic: sys, diastolic: dia, pulse,
      });
      setRows((r) => [rec, ...(r ?? [])]);
      setForm({ sys: "", dia: "", pulse: "" });
      setShowForm(false);
      showToast("Запись сохранена");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось сохранить запись");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Дневник здоровья" subtitle="Мониторинг давления" back="/profile" right={<BrandMark />} />
      <div className="screen-body">
        {status === "error" && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Не удалось загрузить</h2>
            <Button className="btn btn-primary" style={{ marginTop: 14 }} onClick={load}>Повторить</Button>
          </div>
        )}
        {status === "loading" && (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        )}
        {status === "ready" && rows !== null && (
          <>
            <div className="card">
              <div className="health-chart-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 className="h3">Давление за 14 дней</h3>
                <div className="legend">
                  <span><i style={{ background: "#2563EB" }} />Сис.</span>
                  <span><i style={{ background: "#8B5CF6" }} />Диас.</span>
                </div>
              </div>
              <Chart records={rows} />
            </div>

            {showForm && (
              <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <h3 className="h3">Новая запись</h3>
                <div className="btn-row health-form-fields">
                  <div className="field"><input inputMode="numeric" placeholder="Систол." value={form.sys} onChange={(e) => setForm({ ...form, sys: e.target.value })} /></div>
                  <div className="field"><input inputMode="numeric" placeholder="Диастол." value={form.dia} onChange={(e) => setForm({ ...form, dia: e.target.value })} /></div>
                  <div className="field"><input inputMode="numeric" placeholder="Пульс" value={form.pulse} onChange={(e) => setForm({ ...form, pulse: e.target.value })} /></div>
                </div>
                <Button className="btn btn-primary" onClick={add} disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</Button>
              </div>
            )}

            <div className="section-label">История записей</div>
            {rows.length === 0 && <div className="card muted">Записей пока нет.</div>}
            {rows.map((r) => {
              const normal = r.systolic < 130 && r.diastolic < 85;
              return (
                <div key={r.id} className="card health-record" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: 13, color: "#8E8E93" }}>{fmtWhen(r.at)}</p>
                    <p style={{ fontSize: 13, color: "#8E8E93", marginTop: 2 }}>{r.pulse} уд/мин</p>
                  </div>
                  <span className="bp-val">{r.systolic}/{r.diastolic}</span>
                  <Badge color={normal ? "green" : "yellow"}>{normal ? "Норма" : "Выше нормы"}</Badge>
                </div>
              );
            })}
            <p className="muted" style={{ fontSize: 12 }}>
              Оценка «Норма / Выше нормы» — ориентировочная и не заменяет консультацию врача.
            </p>
          </>
        )}
      </div>
      <div className="foot">
        <Button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Свернуть форму" : "Новая запись"}
        </Button>
      </div>
      {toast}
    </div>
  );
}
