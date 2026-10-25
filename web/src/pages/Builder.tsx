import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Radio } from "@maxhub/max-ui";
import { api } from "../api";
import { useApp } from "../App";
import EventDateTimeInputs from "../components/EventDateTimeInputs";
import StepKindSelect from "../components/StepKindSelect";
import { canBeBookingTarget } from "../stepKinds";
import type { CustomStepIn, RouteDto, Situation, StepKind } from "../types";
import { Button, ErrorView, Header, LoadingView, Switch, useToast } from "../components/ui";
import { I, SituationIcon } from "../icons";

interface TemplateStep {
  key: string | null;
  kind: StepKind;
  booking_target_key: string | null;
  description: string;
  position: number;
  title: string;
  has_checklist: boolean;
}

const SHORT_KIND_LABELS: Record<StepKind, string> = {
  unknown: "Вид не уточнён", visit: "Приём", booking: "Запись",
  investigation: "Исследование", task: "Задача", process: "Этап процесса",
};

export default function Builder() {
  const { user } = useApp();
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [situations, setSituations] = useState<Situation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [templateSteps, setTemplateSteps] = useState<TemplateStep[]>([]);
  const [templateStatus, setTemplateStatus] = useState<"loading" | "ready" | "error">("ready");
  const [off, setOff] = useState<Set<number>>(new Set());
  const [custom, setCustom] = useState<CustomStepIn[]>([]);
  const [ownName, setOwnName] = useState("");
  const [ownDate, setOwnDate] = useState("");
  const [ownTime, setOwnTime] = useState("");
  const [ownKind, setOwnKind] = useState<StepKind>("task");
  const [ownBefore, setOwnBefore] = useState("");
  const [ownAttempted, setOwnAttempted] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);
  const catalogRequestId = useRef(0);
  const templateRequestId = useRef(0);
  const creating = useRef(false);

  const load = useCallback(() => {
    const requestId = ++catalogRequestId.current;
    setStatus("loading");
    api.get<Situation[]>("/api/v1/catalog")
      .then((s) => {
        if (requestId !== catalogRequestId.current) return;
        setSituations(s);
        setStatus("ready");
      })
      .catch(() => {
        if (requestId === catalogRequestId.current) setStatus("error");
      });
  }, []);

  useEffect(load, []);

  const pick = async (key: string, reset = true) => {
    const requestId = ++templateRequestId.current;
    setSelected(key);
    if (reset) {
      setOff(new Set());
      setOwnBefore("");
      setCustom((items) => items.map((item) => ({ ...item, before_position: null, booking_target_key: null })));
    }
    if (key === "custom") {
      setTemplateSteps([]);
      setTemplateStatus("ready");
      return;
    }
    setTemplateSteps([]);
    setTemplateStatus("loading");
    try {
      const steps = await api.get<TemplateStep[]>(`/api/v1/catalog/${key}/steps`);
      if (requestId === templateRequestId.current) { setTemplateSteps(steps); setTemplateStatus("ready"); }
    } catch {
      if (requestId === templateRequestId.current) { setTemplateSteps([]); setTemplateStatus("error"); }
    }
  };

  const addOwn = () => {
    const name = ownName.trim();
    if (!name) {
      setOwnAttempted(true);
      showToast("Напишите название шага — оно подсвечено красным");
      return;
    }
    setCustom((prev) => [...prev, { title: name, kind: ownKind, client_key: crypto.randomUUID(),
      before_position: ownBefore ? Number(ownBefore) : null,
      appointment_date: ownKind === "booking" ? ownDate || null : null,
      deadline: ownKind === "booking" ? null : ownDate || null,
      deadline_time: ownKind !== "booking" && ownDate && ownTime ? ownTime : null }]);
    setOwnName("");
    setOwnDate("");
    setOwnTime("");
    setOwnAttempted(false);
  };

  const toggleStep = (position: number, on: boolean) =>
    setOff((prev) => {
      const next = new Set(prev);
      if (on) next.delete(position);
      else next.add(position);
      return next;
    });

  const create = async () => {
    if (!selected || creating.current || templateStatus !== "ready") return;
    creating.current = true;
    setBusy(true);
    try {
      await api.post<RouteDto>("/api/v1/route/start", {
        situation_key: selected,
        exclude_positions: [...off],
        custom_steps: custom,
      });
      showToast("Маршрут создан");
      nav("/route");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Не удалось создать маршрут");
    } finally {
      creating.current = false;
      setBusy(false);
    }
  };

  const total = selected ? templateSteps.length - off.size + custom.length : 0;
  const effective = templateSteps.filter((s) => !off.has(s.position)).flatMap((s) => [
    ...custom.filter((c) => c.before_position === s.position).map((c) => ({ key: c.client_key, title: c.title, kind: c.kind })),
    { key: s.key, title: s.title, kind: s.kind },
  ]).concat(custom.filter((c) => !c.before_position).map((c) => ({ key: c.client_key, title: c.title, kind: c.kind })));
  const targetsFor = (key: string | undefined) => effective.slice(effective.findIndex((s) => s.key === key) + 1).filter((s) => canBeBookingTarget(s.kind) && s.key);
  const move = (index: number, delta: number) => setCustom((prev) => {
    const next = [...prev]; [next[index], next[index + delta]] = [next[index + delta], next[index]]; return next;
  });

  if (status === "error") {
    return (
      <div className="app">
        <Header title="Свой маршрут" back="/route" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  return (
    <div className="app">
      <Header title="Свой маршрут" subtitle="Шаблон можно изменить под себя" back="/" />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "ready" && (
          <div className="split">
            <div className="col">
              {selected && templateStatus === "loading" && <p role="status" className="muted">Загружаем шаги шаблона…</p>}
              {selected && templateStatus === "error" && <ErrorView onRetry={() => pick(selected, false)} />}
              <div className="section-h"><b>Основа</b></div>
              <div className="card" style={{ padding: "8px 16px" }}>
                {situations.map((s) => (
                  <div
                    className="rem-item press"
                    key={s.key}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected === s.key}
                    style={selected === s.key ? { outline: "2px solid var(--blue)", outlineOffset: -2, borderRadius: 10, padding: "11px 8px" } : undefined}
                    onClick={() => pick(s.key)}
                    onKeyDown={(e) => {
                      if (e.target !== e.currentTarget) return;
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        pick(s.key);
                      }
                    }}
                  >
                      <div className="what">
                        <b>{s.title}</b>
                        <small>Готовая основа</small>
                        {s.description && <details className="builder-details" onClick={(e) => e.stopPropagation()}>
                          <summary>О шаблоне</summary>
                          <small>{s.description}</small>
                        </details>}
                      </div>
                    <Radio checked={selected === s.key} readOnly aria-label={s.title} />
                  </div>
                ))}
                <div
                  className="rem-item press"
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected === "custom"}
                  style={selected === "custom" ? { outline: "2px solid var(--blue)", outlineOffset: -2, borderRadius: 10, padding: "11px 8px" } : undefined}
                  onClick={() => pick("custom")}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      pick("custom");
                    }
                  }}
                >
                  <div className="what"><b>С нуля</b><small>Без шаблона — только свои шаги</small></div>
                  <Radio checked={selected === "custom"} readOnly aria-label="С нуля" />
                </div>
              </div>
            </div>

            <div className="col">
              {!selected && (
                <div className="card empty-card" style={{ marginTop: 34 }}>
                  <div className="empty-ico"><I.route size={20} /></div>
                  <b style={{ fontSize: 14.5 }}>Шаги появятся здесь</b>
                  <div className="muted">Выберите шаблон слева — его шаги можно будет выключить, а свои добавить ниже.</div>
                </div>
              )}
              {selected && selected !== "custom" && templateSteps.length > 0 && (
                <>
                  <div className="section-h"><b>Шаги маршрута</b><span className="muted" style={{ fontSize: 13 }}>можно выключить</span></div>
                  <div className="card" style={{ padding: "8px 16px" }}>
                    {templateSteps.map((s) => (
                      <div
                        className="rem-item press"
                        key={s.position}
                        role="button"
                        tabIndex={0}
                        aria-pressed={!off.has(s.position)}
                        onClick={() => toggleStep(s.position, off.has(s.position))}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget) return;
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggleStep(s.position, off.has(s.position));
                          }
                        }}
                      >
                        <div className="what"><b>{s.title}</b><small>{SHORT_KIND_LABELS[s.kind ?? "unknown"]}</small>
                          <details className="builder-details" onClick={(e) => e.stopPropagation()}>
                            <summary>Подробнее</summary>
                            {s.description && <small>{s.description}</small>}
                            {s.kind === "booking" && <small>{s.booking_target_key && templateSteps.some((t) => t.key === s.booking_target_key && !off.has(t.position)) ? `Связано с: ${templateSteps.find((t) => t.key === s.booking_target_key)?.title}` : "Без связи: цель не задана или исключена. Дата не будет перенесена в другой шаг."}</small>}
                          </details>
                        </div>
                        <Switch
                          on={!off.has(s.position)}
                          onChange={(v) => toggleStep(s.position, v)}
                          label={s.title}
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}

              {selected && (
                <>
                  <div className="section-h"><b>Свои шаги</b></div>
                  <div className="card" style={{ padding: "8px 16px" }}>
                    {custom.map((c, i) => (
                      <div className="rem-item" key={c.client_key} style={{ flexWrap: "wrap" }}>
                        <div className="what"><b>{c.title}</b><small>{SHORT_KIND_LABELS[c.kind]}{c.deadline ? ` · ${c.deadline}${c.deadline_time ? ` в ${c.deadline_time}` : ""}` : " · без срока"}</small>
                          {c.kind === "booking" && <details className="builder-details" onClick={(e) => e.stopPropagation()}><summary>Дата и связь</summary><small>Полученная дата: {c.appointment_date ?? "неизвестна"}. {!targetsFor(c.client_key).some((s) => s.key === c.booking_target_key) && "Без связи с событием; напоминаний о нём из этой записи нет."}</small></details>}
                        </div>
                        {selected === "custom" && <>
                          <button type="button" aria-label={`Выше: ${c.title}`} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                          <button type="button" aria-label={`Ниже: ${c.title}`} disabled={i === custom.length - 1} onClick={() => move(i, 1)}>↓</button>
                        </>}
                        {selected !== "custom" && <label className="kind-select">Размещение
                          <select aria-label={`Размещение: ${c.title}`} value={c.before_position ?? ""} onChange={(e) => setCustom((items) => items.map((item, j) => j === i ? { ...item, before_position: e.target.value ? Number(e.target.value) : null } : item))}>
                            <option value="">В конец</option>
                             {templateSteps.map((s) => <option key={s.position} value={s.position} disabled={off.has(s.position)}>Перед: {s.title}{off.has(s.position) ? " (исключена — уточните размещение)" : ""}</option>)}
                          </select>
                        </label>}
                        {c.kind === "booking" && <label className="kind-select">Связанное событие
                          <select aria-label={`Цель записи: ${c.title}`} value={c.booking_target_key ?? ""} onChange={(e) => setCustom((items) => items.map((item, j) => j === i ? { ...item, booking_target_key: e.target.value || null } : item))}>
                            <option value="">Без связи</option>
                            {c.booking_target_key && !targetsFor(c.client_key).some((s) => s.key === c.booking_target_key) && <option value={c.booking_target_key} disabled>Цель исключена или больше не находится после записи — уберите связь</option>}
                             {targetsFor(c.client_key).map((s) => <option key={s.key} value={s.key!}>{s.title}</option>)}
                          </select>
                        </label>}
                        <button className="picked-item-x" aria-label="Убрать" onClick={() => setCustom((prev) => prev.filter((_, j) => j !== i))}>✕</button>
                      </div>
                    ))}
                    {custom.length === 0 && (
                      <div className="rem-item"><div className="what"><b className="muted" style={{ fontWeight: 500 }}>Пока пусто</b><small>например, «Договориться о замене справки»</small></div></div>
                    )}
                  </div>
                  <div className="card">
                    <div className="own-row" style={{ flexWrap: "wrap" }}>
                      <StepKindSelect value={ownKind} onChange={(kind) => { setOwnKind(kind); setOwnTime(""); }} />
                      {selected !== "custom" && <label className="kind-select">Размещение нового шага
                        <select aria-label="Размещение нового шага" value={ownBefore} onChange={(e) => setOwnBefore(e.target.value)}>
                          <option value="">В конец</option>
                           {templateSteps.filter((s) => !off.has(s.position)).map((s) => <option key={s.position} value={s.position}>Перед: {s.title}</option>)}
                        </select>
                      </label>}
                      <input
                        placeholder="Свой шаг"
                        aria-label="Название шага"
                        value={ownName}
                        className={ownAttempted && !ownName.trim() ? "invalid" : undefined}
                        onChange={(e) => setOwnName(e.target.value)}
                      />
                      {ownKind === "booking" ? <label className="date-only-field">На какую дату вы записались?<input type="date" aria-label="На какую дату вы записались?" value={ownDate} onChange={(e) => setOwnDate(e.target.value)} /></label> : <EventDateTimeInputs date={ownDate} time={ownTime} onChange={(d, t) => { setOwnDate(d); setOwnTime(t); }} />}
                      <button className="add" onClick={addOwn} aria-label="Добавить">+</button>
                    </div>
                     <p className="muted">Дата необязательна (в вашем местном времени). Для записи цель выбирается после добавления; её дата не меняет расписание до подтверждения в карточке.</p>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="foot">
        <Button disabled={!selected || busy || total === 0 || templateStatus !== "ready"} onClick={create}>
          {busy
            ? "Создаём…"
            : selected
              ? total > 0
                ? `Создать маршрут — ${total} шагов`
                : "Добавьте хотя бы один шаг"
              : "Выберите основу"}
        </Button>
      </div>
      {toast}
    </div>
  );
}
