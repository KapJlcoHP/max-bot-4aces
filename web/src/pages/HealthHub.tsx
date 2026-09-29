import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ReactElement } from "react";
import { CellHeader, CellList, CellSimple } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtWhen } from "../format";
import type { HealthRecord, HealthSetting, HealthType, MedsOut } from "../types";
import { Button, ErrorView, Header, InlineError, LoadingView, Sheet, Switch, useToast } from "../components/ui";
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
  const [settingsError, setSettingsError] = useState(false);
  const [recordErrors, setRecordErrors] = useState<Partial<Record<HealthType, boolean>>>({});
  const [medsError, setMedsError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState<Partial<Record<HealthType | "meds", boolean>>>({});
  const loadId = useRef(0);
  const [sheet, setSheet] = useState(false);
  const [draft, setDraft] = useState<Record<HealthType, boolean>>({ bp: true, weight: true, sugar: false, mood: true });
  // время пуша: всегда валидное, пока дневник включён — иначе сохранился бы null при «не трогал поле»
  const [draftTimes, setDraftTimes] = useState<Record<HealthType, string>>({ bp: "09:00", weight: "09:00", sugar: "09:00", mood: "09:00" });

  const load = useCallback(() => {
    const requestId = ++loadId.current;
    setRefreshing(true);
    setStatus((previous) => previous === "ready" ? "ready" : "loading");
    Promise.allSettled([
      api.get<{ diaries: HealthSetting[] }>("/api/v1/health/settings"),
      api.get<HealthRecord[]>("/api/v1/health/bp/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/weight/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/sugar/records?limit=1"),
      api.get<HealthRecord[]>("/api/v1/health/mood/records?limit=1"),
      api.get<MedsOut>("/api/v1/meds"),
    ])
      .then(([s, bp, w, sg, m, md]) => {
        if (requestId !== loadId.current) return;
        if (s.status === "fulfilled") {
          setSettings(s.value.diaries);
          setDraft(Object.fromEntries(s.value.diaries.map((d) => [d.diary, d.enabled])) as Record<HealthType, boolean>);
          setDraftTimes(
            Object.fromEntries(
              s.value.diaries.map((d) => [d.diary, d.push_time || "09:00"]),
            ) as Record<HealthType, string>,
          );
        }
        setLasts((previous) => ({
          ...previous,
          ...(bp.status === "fulfilled" ? { bp: bp.value[0] } : {}),
          ...(w.status === "fulfilled" ? { weight: w.value[0] } : {}),
          ...(sg.status === "fulfilled" ? { sugar: sg.value[0] } : {}),
          ...(m.status === "fulfilled" ? { mood: m.value[0] } : {}),
        }));
        if (md.status === "fulfilled") setMeds(md.value);
        setSettingsError(s.status === "rejected");
        setRecordErrors({
          bp: bp.status === "rejected",
          weight: w.status === "rejected",
          sugar: sg.status === "rejected",
          mood: m.status === "rejected",
        });
        setMedsError(md.status === "rejected");
        setStatus((previous) => s.status === "fulfilled" || previous === "ready" ? "ready" : "error");
        setRefreshing(false);
      });
  }, []);

  useEffect(() => {
    load();
    return () => { loadId.current += 1; };
  }, [load]);

  const retryRecord = async (type: HealthType) => {
    setRetrying((previous) => ({ ...previous, [type]: true }));
    try {
      const records = await api.get<HealthRecord[]>(`/api/v1/health/${type}/records?limit=1`);
      setLasts((previous) => ({ ...previous, [type]: records[0] }));
      setRecordErrors((previous) => ({ ...previous, [type]: false }));
    } catch {
      setRecordErrors((previous) => ({ ...previous, [type]: true }));
    } finally {
      setRetrying((previous) => ({ ...previous, [type]: false }));
    }
  };

  const retryMeds = async () => {
    setRetrying((previous) => ({ ...previous, meds: true }));
    try {
      setMeds(await api.get<MedsOut>("/api/v1/meds"));
      setMedsError(false);
    } catch {
      setMedsError(true);
    } finally {
      setRetrying((previous) => ({ ...previous, meds: false }));
    }
  };

  const saveSettings = async () => {
    try {
      const res = await api.put<{ diaries: HealthSetting[] }>("/api/v1/health/settings", {
        diaries: (Object.keys(draft) as HealthType[]).map((d) => ({
          diary: d,
          enabled: draft[d],
          push_time: draft[d] ? draftTimes[d] : null,
        })),
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
        {status === "ready" && settingsError && (
          <InlineError message="Не удалось обновить настройки дневников. Показаны последние данные." onRetry={load} retrying={refreshing} />
        )}
        {status === "ready" && (
          <div className="split">
            <div className="col">
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
                  <Fragment key={t}>
                    <CellList mode="island">
                      <CellSimple
                        className="press"
                        before={<div className={`ic ${meta.cls}`}><Icon size={18} /></div>}
                        title={meta.title}
                        after={<span className="cell-note">{recordErrors[t] && !lasts[t] ? "данные недоступны" : lastValueSummary(t, lasts[t])}</span>}
                        showChevron
                        onClick={() => nav(`/health/${t}`)}
                      />
                    </CellList>
                    {recordErrors[t] && (
                      <InlineError message={`Не удалось загрузить дневник «${meta.title}».`} onRetry={() => retryRecord(t)} retrying={retrying[t]} />
                    )}
                  </Fragment>
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
            </div>

            <div className="col">
              <CellList mode="island">
                <CellSimple
                  className="press"
                  before={<div className="ic"><I.pill size={18} /></div>}
                  title="Приём лекарств"
                  after={<span className="cell-note">
                    {medsError && !meds ? "данные недоступны" : nextMed ? `${meds!.courses.length} ${meds!.courses.length === 1 ? "курс" : meds!.courses.length < 5 ? "курса" : "курсов"} · в ${nextMed.at_time}` : "добавить курс"}
                  </span>}
                  showChevron
                  onClick={() => nav("/meds")}
                />
              </CellList>
              {medsError && <InlineError message="Не удалось загрузить лекарства." onRetry={retryMeds} retrying={retrying.meds} />}

              <CellHeader titleStyle="normal">Отчёты</CellHeader>
              <div className="card tinted press" onClick={() => nav("/health/report")}>
                <b style={{ color: "var(--blue)" }}>Сводка для врача</b>
                <div className="muted" style={{ marginTop: 5 }}>
                  Давление, вес, приёмы лекарств за 30 дней — покажите на приёме вместо слов.
                </div>
              </div>
            </div>
          </div>
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
              {draft[t] && (
                <label className="push-time">
                  <small>Бот напомнит в</small>
                  <input
                    type="time"
                    value={draftTimes[t]}
                    onChange={(e) => setDraftTimes((prev) => ({ ...prev, [t]: e.target.value }))}
                  />
                </label>
              )}
            </div>
          ))}
        </div>
        <div className="sub" style={{ marginTop: 8 }}>
          В назначенное время бот напишет в чат — записать показатели можно прямо там, без открытия приложения
        </div>
        <Button style={{ marginTop: 14 }} onClick={saveSettings}>Готово</Button>
      </Sheet>
      {toast}
    </div>
  );
}
