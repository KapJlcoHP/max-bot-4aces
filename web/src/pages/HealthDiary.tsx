import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Line } from "react-chartjs-2";
import { CategoryScale, Chart as ChartJS, LinearScale, LineElement, PointElement, Tooltip } from "chart.js";
import { api } from "../api";
import { fmtDateNumeric, fmtHhmm, fmtWhen, parseDate } from "../format";
import type { HealthRecord, HealthType } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

ChartJS.register(CategoryScale, LinearScale, LineElement, PointElement, Tooltip);

const TITLES: Record<HealthType, string> = {
  bp: "Давление и пульс",
  weight: "Вес",
  sugar: "Сахар крови",
  mood: "Самочувствие",
};

const UNITS: Record<HealthType, string> = {
  bp: "мм рт. ст.",
  weight: "кг",
  sugar: "ммоль/л",
  mood: "",
};

/** Серии давления на общей шкале: цвет = фирменная палитра. */
const BP_SERIES = [
  { key: "sys", label: "Систолическое", color: "#006DF8", get: (r: HealthRecord) => r.systolic },
  { key: "dia", label: "Диастолическое", color: "#DE2129", get: (r: HealthRecord) => r.diastolic },
  { key: "pulse", label: "Пульс", color: "#22C55E", get: (r: HealthRecord) => r.pulse },
] as const;

type BpSeriesKey = (typeof BP_SERIES)[number]["key"];

type Period = "day" | "month" | "year" | "custom";

const PERIODS: { key: Period; label: string }[] = [
  { key: "day", label: "День" },
  { key: "month", label: "Месяц" },
  { key: "year", label: "Год" },
  { key: "custom", label: "Свой срок" },
];

const toIsoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Дата в полночь (локальная) из «YYYY-MM-DD» */
const fromIsoDay = (iso: string, endOfDay = false): Date | null => {
  const d = parseDate(iso);
  if (!d) return null;
  return endOfDay ? new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59) : new Date(d.getFullYear(), d.getMonth(), d.getDate());
};

export default function HealthDiary() {
  const { type: rawType } = useParams<{ type: string }>();
  const type = (rawType ?? "bp") as HealthType;
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [records, setRecords] = useState<HealthRecord[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [period, setPeriod] = useState<Period>("month");
  const [from, setFrom] = useState(() => toIsoDay(new Date(Date.now() - 6 * 86400000)));
  const [to, setTo] = useState(() => toIsoDay(new Date()));
  const [delRec, setDelRec] = useState<HealthRecord | null>(null);
  const [hidden, setHidden] = useState<Record<BpSeriesKey, boolean>>({ sys: false, dia: false, pulse: false });

  // форма новой записи
  const [sys, setSys] = useState("");
  const [dia, setDia] = useState("");
  const [pulse, setPulse] = useState("");
  const [weight, setWeight] = useState("");
  const [sugar, setSugar] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [mealTag, setMealTag] = useState("до еды");
  const [mood, setMood] = useState("Хорошо");
  const [pain, setPain] = useState(2);
  const [tag, setTag] = useState("утром");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    setStatus("loading");
    api.get<HealthRecord[]>(`/api/v1/health/${type}/records?limit=500`)
      .then((r) => { setRecords(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, [type]);

  useEffect(load, [type]);

  const latest = records[0];

  const range = useMemo((): [Date, Date] | null => {
    const now = new Date();
    const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
    if (period === "day") return [new Date(now.getFullYear(), now.getMonth(), now.getDate()), todayEnd];
    if (period === "month") return [new Date(todayEnd.getTime() - 29 * 86400000), todayEnd];
    if (period === "year") return [new Date(todayEnd.getTime() - 364 * 86400000), todayEnd];
    const f = fromIsoDay(from);
    const t = fromIsoDay(to, true);
    return f && t && f <= t ? [f, t] : null;
  }, [period, from, to]);

  const chartData = useMemo(() => {
    if (type === "mood" || !range) return null;
    const getters: { key: string; get: (r: HealthRecord) => number | null }[] =
      type === "bp"
        ? BP_SERIES.map((s) => ({ key: s.key, get: (r: HealthRecord) => s.get(r) as number | null }))
        : [{ key: "v", get: (r: HealthRecord) => (type === "weight" ? r.weight_kg : type === "sugar" ? r.sugar_mmol : null) }];

    const inRange = records
      .filter((r) => {
        const d = parseDate(r.at);
        return d !== null && d >= range[0] && d <= range[1] && getters.some((g) => g.get(r) !== null);
      })
      .sort((a, b) => +parseDate(a.at)! - +parseDate(b.at)!);
    if (inRange.length === 0) return null;

    const spanDays = (+range[1] - +range[0]) / 86400000;
    // длинный период: усредняем по дням, иначе линия превращается в частокол
    let groups: { at: Date; rows: HealthRecord[] }[];
    if (spanDays > 31) {
      const byDay = new Map<string, { at: Date; rows: HealthRecord[] }>();
      for (const r of inRange) {
        const d = parseDate(r.at)!;
        const key = toIsoDay(d);
        const g = byDay.get(key);
        if (g) g.rows.push(r);
        else byDay.set(key, { at: d, rows: [r] });
      }
      groups = [...byDay.values()];
    } else {
      groups = inRange.map((r) => ({ at: parseDate(r.at)!, rows: [r] }));
    }

    const avg = (rows: HealthRecord[], get: (r: HealthRecord) => number | null): number | null => {
      const vals = rows.map(get).filter((v): v is number => v !== null);
      return vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10 : null;
    };

    return {
      byDay: spanDays > 31,
      labels: groups.map((g) => (spanDays <= 1 ? fmtHhmm(g.at) : fmtDateNumeric(g.at).slice(0, 5))),
      tooltips: groups.map((g) =>
        spanDays <= 1 ? `${fmtDateNumeric(g.at)} ${fmtHhmm(g.at)}` : fmtDateNumeric(g.at),
      ),
      series: Object.fromEntries(getters.map((g) => [g.key, groups.map((gr) => avg(gr.rows, g.get))])),
    };
  }, [records, type, range]);

  const submit = async () => {
    setBusy(true);
    try {
      if (type === "bp") {
        await api.post("/api/v1/health/bp", { systolic: Number(sys), diastolic: Number(dia), pulse: pulse ? Number(pulse) : null, tag, note: note || null });
      } else if (type === "weight") {
        await api.post("/api/v1/health/weight", { weight_kg: Number(weight.replace(",", ".")), tag, note: note || null });
      } else if (type === "sugar") {
        await api.post("/api/v1/health/sugar", { sugar_mmol: Number(sugar.replace(",", ".")), meal_tag: mealTag, note: note || null });
      } else {
        await api.post("/api/v1/health/mood", { mood, pain, note: note || null, tag: "вечером" });
      }
      setSheet(false);
      setNote("");
      showToast("Запись сохранена");
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось сохранить запись");
    } finally {
      setBusy(false);
    }
  };

  const confirmDelRec = async () => {
    if (!delRec) return;
    setBusy(true);
    try {
      await api.del(`/api/v1/health/${type}/${delRec.id}`);
      setDelRec(null);
      showToast("Запись удалена");
      load();
    } catch {
      showToast("Не удалось удалить запись");
    } finally {
      setBusy(false);
    }
  };

  const bigValue = useMemo(() => {
    if (!latest) return null;
    if (type === "bp") return `${latest.systolic}/${latest.diastolic}`;
    if (type === "weight") return String(latest.weight_kg).replace(".", ",");
    if (type === "sugar") return String(latest.sugar_mmol).replace(".", ",");
    return latest.mood;
  }, [latest, type]);

  const historyLine = (r: HealthRecord): { b: string; s: string } => {
    if (type === "bp") return { b: `${r.systolic}/${r.diastolic} · ${r.pulse ?? "—"} уд/мин`, s: `${fmtWhen(r.at)}${r.tag ? ` · ${r.tag}` : ""}` };
    if (type === "weight") return { b: `${String(r.weight_kg).replace(".", ",")} кг`, s: `${fmtWhen(r.at)}${r.tag ? ` · ${r.tag}` : ""}` };
    if (type === "sugar") return { b: `${String(r.sugar_mmol).replace(".", ",")} ммоль/л`, s: `${fmtWhen(r.at)}${r.meal_tag ? ` · ${r.meal_tag}` : ""}` };
    return { b: `${r.mood}${r.pain ? ` · боль ${r.pain}/10` : " · без боли"}`, s: `${fmtWhen(r.at)}${r.note ? ` · ${r.note}` : ""}` };
  };

  const stroke = type === "weight" ? "#22C55E" : type === "sugar" ? "#DE2129" : "#006DF8";
  const unit = UNITS[type];

  const activeSeries = useMemo(() => {
    if (type === "bp") return BP_SERIES.filter((s) => !hidden[s.key]).map((s) => ({ key: s.key, label: s.label, color: s.color }));
    if (type === "weight" || type === "sugar") return [{ key: "v", label: TITLES[type], color: stroke }];
    return [];
  }, [type, hidden, stroke]);

  return (
    <div className="app narrow">
      <Header title={TITLES[type] ?? "Дневник"} subtitle={type === "mood" ? "Как вы себя чувствуете" : "Последние записи"} back="/health" />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "error" && <ErrorView onRetry={load} />}
        {status === "ready" && !latest && (
          <div className="empty-card" style={{ paddingTop: 32 }}>
            <div className="empty-ico" style={{ width: 64, height: 64 }}><I.pulse size={28} /></div>
            <b style={{ fontSize: 17 }}>Записей пока нет</b>
            <div className="muted">Добавьте первую запись — история и график появятся здесь.</div>
            <Button style={{ marginTop: 8 }} onClick={() => setSheet(true)}>Новая запись</Button>
          </div>
        )}
        {status === "ready" && latest && (
          <>
            <div className="card hero">
              {type === "bp" && <div className="route-status"><div className="label"><span>Последнее измерение</span></div></div>}
              <div className="big-nums">
                <span className="n">{bigValue}</span>
                {type === "weight" && <span className="of">кг</span>}
                {type === "sugar" && <span className="of">ммоль/л</span>}
              </div>
              <div className="muted" style={{ fontSize: 13.5, fontWeight: 600, marginTop: -4 }}>
                {type === "bp" && latest.pulse !== null && `пульс ${latest.pulse} уд/мин · `}
                {type === "sugar" && latest.meal_tag ? `${latest.meal_tag} · ` : ""}
                {fmtWhen(latest.at)}
              </div>
            </div>

            {type !== "mood" && (
              <div className="card">
                <div className="section-h" style={{ marginBottom: 8 }}><b>Динамика</b></div>
                <div className="pick-chips" style={{ marginBottom: 10 }}>
                  {PERIODS.map((p) => (
                    <button key={p.key} className={`pick${period === p.key ? " on" : ""}`} onClick={() => setPeriod(p.key)}>
                      {p.label}
                    </button>
                  ))}
                </div>
                {period === "custom" && (
                  <div className="own-row" style={{ marginBottom: 10 }}>
                    <input className="date" type="date" aria-label="С даты" value={from} onChange={(e) => setFrom(e.target.value)} />
                    <input className="date" type="date" aria-label="По дату" value={to} onChange={(e) => setTo(e.target.value)} />
                  </div>
                )}
                {type === "bp" && (
                  <div className="pick-chips" style={{ marginBottom: 10 }}>
                    {BP_SERIES.map((s) => (
                      <button
                        key={s.key}
                        className={`pick${hidden[s.key] ? "" : " on"}`}
                        onClick={() => setHidden((h) => ({ ...h, [s.key]: !h[s.key] }))}
                      >
                        <i className="chip-dot" style={{ background: s.color }} />
                        {s.label}
                      </button>
                    ))}
                  </div>
                )}
                {chartData && activeSeries.length > 0 && chartData.labels.length >= 2 ? (
                  <div style={{ height: 180 }}>
                    <Line
                      data={{
                        labels: chartData.labels,
                        datasets: activeSeries.map((s) => ({
                          label: s.label,
                          data: chartData.series[s.key] as (number | null)[],
                          borderColor: s.color,
                          backgroundColor: s.color,
                          borderWidth: 2.5,
                          pointRadius: 0,
                          pointHoverRadius: 4,
                          tension: 0.35,
                          spanGaps: true,
                        })),
                      }}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: { mode: "nearest", intersect: false },
                        plugins: {
                          legend: { display: false },
                          tooltip: {
                            backgroundColor: "#1B2433",
                            padding: 10,
                            titleFont: { family: "Figtree, sans-serif", size: 11 },
                            bodyFont: { family: "Figtree, sans-serif", size: 11 },
                            callbacks: {
                              title: (items) => chartData.tooltips[items[0].dataIndex] ?? "",
                              label: (item) => {
                                const raw = item.raw;
                                const v = typeof raw === "number" ? raw.toLocaleString("ru-RU", { maximumFractionDigits: 1 }) : "—";
                                return `${item.dataset.label}: ${v}${unit ? ` ${unit}` : ""}`;
                              },
                            },
                          },
                        },
                        scales: {
                          x: {
                            grid: { color: "#E5E9F2" },
                            border: { color: "#E5E9F2" },
                            ticks: {
                              color: "#7A8699",
                              font: { family: "Figtree, sans-serif", size: 10 },
                              maxTicksLimit: 8,
                              maxRotation: 0,
                              autoSkip: true,
                            },
                          },
                          y: {
                            grid: { color: "#E5E9F2" },
                            border: { display: false },
                            ticks: { color: "#7A8699", font: { family: "Figtree, sans-serif", size: 10 } },
                            title: { display: !!unit, text: unit, color: "#7A8699", font: { family: "Figtree, sans-serif", size: 10 } },
                          },
                        },
                      }}
                    />
                  </div>
                ) : (
                  <div className="muted" style={{ padding: "10px 0 6px" }}>
                    {chartData && activeSeries.length === 0
                      ? "Включите хотя бы одну линию"
                      : period === "custom" && !range
                        ? "Проверьте выбранный диапазон дат"
                        : "Мало данных за выбранный период"}
                  </div>
                )}
              </div>
            )}

            <div className="section-h"><b>История</b></div>
            <div className="card" style={{ padding: "8px 16px" }}>
              {records.slice(0, 20).map((r) => {
                const ln = historyLine(r);
                return (
                  <div className="rem-item" key={r.id}>
                    <div className="what"><b>{ln.b}</b><small>{ln.s}</small></div>
                    <button className="rem-del" onClick={() => setDelRec(r)} aria-label="Удалить запись">
                      <I.trash size={15} />
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {status === "ready" && (
        <div className="foot"><Button onClick={() => { setAttempted(false); setSheet(true); }}>Новая запись</Button></div>
      )}

      <Sheet open={sheet} onClose={() => setSheet(false)}>
        <h3>Новая запись</h3>
        <div className="sub">Только факт и контекст — приложение не оценивает показатели</div>

        {type === "bp" && (
          <div className="own-row" style={{ marginBottom: 10 }}>
            <input inputMode="numeric" placeholder="Верхнее" value={sys} className={attempted && !sys ? "invalid" : undefined} onChange={(e) => setSys(e.target.value)} />
            <input inputMode="numeric" placeholder="Нижнее" value={dia} className={attempted && !dia ? "invalid" : undefined} onChange={(e) => setDia(e.target.value)} />
            <input inputMode="numeric" placeholder="Пульс" value={pulse} onChange={(e) => setPulse(e.target.value)} />
          </div>
        )}
        {type === "weight" && (
          <div className="own-row" style={{ marginBottom: 10 }}>
            <input inputMode="decimal" placeholder="Вес, кг" value={weight} className={attempted && !weight ? "invalid" : undefined} onChange={(e) => setWeight(e.target.value)} />
          </div>
        )}
        {type === "sugar" && (
          <div className="pick-chips">
            {["до еды", "после еды"].map((m) => (
              <button key={m} className={`pick${mealTag === m ? " on" : ""}`} onClick={() => setMealTag(m)}>{m}</button>
            ))}
          </div>
        )}
        {type === "sugar" && (
          <div className="own-row" style={{ marginBottom: 10 }}>
            <input inputMode="decimal" placeholder="ммоль/л" value={sugar} className={attempted && !sugar ? "invalid" : undefined} onChange={(e) => setSugar(e.target.value)} />
          </div>
        )}
        {type === "mood" && (
          <>
            <div className="pick-chips">
              {["Хорошо", "Нормально", "Плохо"].map((m) => (
                <button key={m} className={`pick${mood === m ? " on" : ""}`} onClick={() => setMood(m)}>{m}</button>
              ))}
            </div>
            <div className="mini-btns" style={{ marginBottom: 10 }}>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                <button key={n} className={`pick${pain === n ? " on" : ""}`} onClick={() => setPain(n)}>{n}</button>
              ))}
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>Боль или дискомфорт, 1–10</div>
          </>
        )}

        {type !== "mood" && (
          <div className="pick-chips">
            {["утром", "вечером"].map((m) => (
              <button key={m} className={`pick${tag === m ? " on" : ""}`} onClick={() => setTag(m)}>{m}</button>
            ))}
          </div>
        )}
        <input className="field" placeholder="Заметка (необязательно)" value={note} onChange={(e) => setNote(e.target.value)} />

        <Button
          style={{ marginTop: 14 }}
          disabled={busy}
          onClick={() => {
            setAttempted(true);
            const missing = (type === "bp" && (!sys || !dia)) || (type === "weight" && !weight) || (type === "sugar" && !sugar);
            if (missing) {
              showToast("Заполните обязательные поля — они подсвечены красным");
              return;
            }
            submit();
          }}
        >
          {busy ? "Сохраняем…" : "Сохранить запись"}
        </Button>
      </Sheet>

      <Sheet open={!!delRec} onClose={() => setDelRec(null)}>
        <h3>Удалить запись?</h3>
        <div className="sub">
          {delRec ? `${historyLine(delRec).b}, ${fmtWhen(delRec.at)}` : ""} — это нельзя отменить.
        </div>
        <div className="btn-row">
          <Button variant="secondary" onClick={() => setDelRec(null)}>Отмена</Button>
          <Button disabled={busy} onClick={confirmDelRec}>Удалить</Button>
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
