import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ReactElement } from "react";
import { CellHeader, CellList, CellSimple } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtWhen } from "../format";
import type { HealthRecord, HealthSetting, HealthType, MedsOut } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, Switch, useToast } from "../components/ui";
import { I } from "../icons";

const DIARY_META: Record<HealthType, { title: string; hint: string; icon: (p: { size?: number }) => ReactElement; cls: string }> = {
  bp: { title: "Давление и пульс", hint: "нужен тонометр", icon: I.pulse, cls: "" },
  weight: { title: "Вес", hint: "нужны напольные весы", icon: I.scale, cls: "g" },
  sugar: { title: "Сахар крови", hint: "нужен глюкометр", icon: I.shield, cls: "r" },
  mood: { title: "Самочувствие", hint: "без приборов", icon: I.smile, cls: "b" },
};

function lastValueSummary(type: HealthType, r: HealthRecord | undefined): string {
  if (!r) return "нет записей";
  if (type === "bp") return `${r.systolic}/${r.diastolic} · ${fmtWhen(r.at)}`;
  if (type === "weight") return `${String(r.weight_kg).replace(".", ",")} кг · ${fmtWhen(r.at)}`;
  if (type === "sugar") return `${String(r.sugar_mmol).replace(".", ",")} ммоль/л · ${r.meal_tag ?? fmtWhen(r.at)}`;
  return `${r.mood}${r.pain ? ` · боль ${r.pain}/10` : ""} · ${fmtWhen(r.at)}`;
}

export default function HealthHub() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [settings, setSettings] = useState<HealthSetting[]>([]);
  const [lasts, setLasts] = useState<Partial<Record<HealthType, HealthRecord>>>({});
  const [meds, setMeds] = useState<MedsOut | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sheet, setSheet] = useState(false);
  const [draft, setDraft] = useState<Record<HealthType, boolean>>({ bp: true, weight: true, sugar: false, mood: true });

  const load = useCallback(() => {
    setStatus("loading");
    Promise.allSettled([
      api.get<{ diaries: HealthSetting[] }>("/api/v1/health/settings"),
      api.get<HealthRecord[]>("/api/v1/health/bp/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/weight/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/sugar/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/mood/records?limit=1"),
      api.get<MedsOut>("/api/v1/meds"),
    ])
      .then(([s, bp, w, sg, m, md]) => {
        if (s.status === "fulfilled") {
          setSettings(s.value.diaries);
          setDraft(Object.fromEntries(s.value.diaries.map((d) => [d.diary, d.enabled])) as Record<HealthType, boolean>);
        }
        setLasts({
          bp: bp.status === "fulfilled" && bp.value.length ? bp.value[0] : undefined,
          weight: w.status === "fulfilled" && w.value.length ? w.value[0] : undefined,
          sugar: sg.status === "fulfilled" && sg.value.length ? sg.value[0] : undefined,
          mood: m.status === "fulfilled" && m.value.length ? m.value[0] : undefined,
        });
        setMeds(md.status === "fulfilled" ? md.value : null);
        setStatus("ready");
      });
  }, []);

  useEffect(load, []);

  const saveSettings = async () => {
    try {
      const res = await api.put<{ diaries: HealthSetting[] }>("/api/v1/health/settings", {
        diaries: (Object.keys(draft) as HealthType[]).map((d) => ({ diary: d, enabled: draft[d] })),
      });
      setSettings(res.diaries);
      setSheet(false);
    } catch {
      showToast("Не удалось сохранить настройки");
    }
  };

  if (status === "error") {
    return (
      <div className="app">
        <Header title="Здоровье" back="/" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  const enabled = (t: HealthType) => settings.find((s) => s.diary === t)?.enabled ?? false;
  const anyEnabled = settings.some((s) => s.enabled);
  const nextMed = meds?.today.find((x) => !x.taken) ?? null;

  return (
    <div className="app">
      <Header title="Здоровье" subtitle="Дневники самонаблюдения" back="/" />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "ready" && (
          <>
            <CellHeader
              titleStyle="normal"
              after={<button className="cell-h-btn" onClick={() => setSheet(true)}>Настроить</button>}
            >
              Мои дневники
            </CellHeader>
            {(Object.keys(DIARY_META) as HealthType[]).filter(enabled).map((t) => {
              const meta = DIARY_META[t];
              const Icon = meta.icon;
              return (
                <CellList mode="island" key={t}>
                  <CellSimple
                    className="press"
                    before={<div className={`ic ${meta.cls}`}><Icon size={18} /></div>}
                    title={meta.title}
                    after={<span className="cell-note">{lastValueSummary(t, lasts[t])}</span>}
                    showChevron
                    onClick={() => nav(`/health/${t}`)}
                  />
                </CellList>
              );
            })}
            {!anyEnabled && (
              <div className="card empty-card">
                <b style={{ fontSize: 14.5 }}>Дневники не выбраны</b>
                <div className="muted">Нажмите «Настроить» — включите то, что нужно именно вам.</div>
              </div>
            )}
            <button className="add-dash" onClick={() => setSheet(true)}>
              <I.plus size={18} /> Добавить дневник
            </button>

            <CellList mode="island" style={{ marginTop: 12 }}>
              <CellSimple
                className="press"
                before={<div className="ic"><I.pill size={18} /></div>}
                title="Приём лекарств"
                after={<span className="cell-note">
                  {nextMed ? `${meds!.courses.length} ${meds!.courses.length === 1 ? "курс" : meds!.courses.length < 5 ? "курса" : "курсов"} · в ${nextMed.at_time}` : "добавить курс"}
                </span>}
                showChevron
                onClick={() => nav("/meds")}
              />
            </CellList>

            <CellHeader titleStyle="normal" style={{ marginTop: 12 }}>Отчёты</CellHeader>
            <div className="card tinted press" onClick={() => nav("/health/report")}>
              <b style={{ color: "var(--blue)" }}>Сводка для врача</b>
              <div className="muted" style={{ marginTop: 5 }}>
                Давление, вес, приёмы лекарств за 30 дней — покажите на приёме вместо слов.
              </div>
            </div>
          </>
        )}
      </div>

      <Sheet open={sheet} onClose={() => setSheet(false)}>
        <h3>Какие дневники вести?</h3>
        <div className="sub">Включайте то, что нужно именно вам — под ваши приборы и назначения врача</div>
        <div className="card" style={{ padding: "8px 16px", boxShadow: "none", background: "var(--bg)" }}>
          {(Object.keys(DIARY_META) as HealthType[]).map((t) => (
            <div className="rem-item" key={t}>
              <div className="what"><b>{DIARY_META[t].title}</b><small>{DIARY_META[t].hint}</small></div>
              <Switch on={draft[t]} onChange={(v) => setDraft((prev) => ({ ...prev, [t]: v }))} label={DIARY_META[t].title} />
            </div>
          ))}
        </div>
        <Button style={{ marginTop: 14 }} onClick={saveSettings}>Готово</Button>
      </Sheet>
      {toast}
    </div>
  );
}
