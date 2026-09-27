import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Radio } from "@maxhub/max-ui";
import { api } from "../api";
import type { CustomStepIn, RouteDto, Situation } from "../types";
import { Button, ErrorView, Header, LoadingView, Switch, useToast } from "../components/ui";
import { I, SituationIcon } from "../icons";

interface TemplateStep {
  position: number;
  title: string;
  has_checklist: boolean;
}

export default function Builder() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [situations, setSituations] = useState<Situation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [templateSteps, setTemplateSteps] = useState<TemplateStep[]>([]);
  const [off, setOff] = useState<Set<number>>(new Set());
  const [custom, setCustom] = useState<CustomStepIn[]>([]);
  const [ownName, setOwnName] = useState("");
  const [ownDate, setOwnDate] = useState("");
  const [ownAttempted, setOwnAttempted] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<Situation[]>("/api/v1/catalog")
      .then((s) => { setSituations(s); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const pick = async (key: string) => {
    setSelected(key);
    setOff(new Set());
    if (key === "custom") {
      setTemplateSteps([]);
      return;
    }
    try {
      setTemplateSteps(await api.get<TemplateStep[]>(`/api/v1/catalog/${key}/steps`));
    } catch {
      setTemplateSteps([]);
    }
  };

  const addOwn = () => {
    const name = ownName.trim();
    if (!name) {
      setOwnAttempted(true);
      showToast("Напишите название шага — оно подсвечено красным");
      return;
    }
    setCustom((prev) => [...prev, { title: name, deadline: ownDate || null }]);
    setOwnName("");
    setOwnDate("");
    setOwnAttempted(false);
  };

  const create = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.post<RouteDto>("/api/v1/route/start", {
        situation_key: selected,
        exclude_positions: [...off],
        custom_steps: custom,
      });
      showToast("Маршрут создан");
      nav("/route");
    } catch {
      showToast("Не удалось создать маршрут");
    } finally {
      setBusy(false);
    }
  };

  const total = selected ? templateSteps.length - off.size + custom.length : 0;

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
              <div className="section-h"><b>Основа</b></div>
              <div className="card" style={{ padding: "8px 16px" }}>
                {situations.map((s) => (
                  <div
                    className="rem-item press"
                    key={s.key}
                    style={selected === s.key ? { outline: "2px solid var(--blue)", outlineOffset: -2, borderRadius: 10, padding: "11px 8px" } : undefined}
                    onClick={() => pick(s.key)}
                  >
                    <div className="what">
                      <b>{s.title}</b>
                      <small>{s.description}</small>
                    </div>
                    <Radio checked={selected === s.key} readOnly aria-label={s.title} />
                  </div>
                ))}
                <div
                  className="rem-item press"
                  style={selected === "custom" ? { outline: "2px solid var(--blue)", outlineOffset: -2, borderRadius: 10, padding: "11px 8px" } : undefined}
                  onClick={() => pick("custom")}
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
                      <div className="rem-item" key={s.position}>
                        <div className="what"><b>{s.title}</b><small>из шаблона</small></div>
                        <Switch
                          on={!off.has(s.position)}
                          onChange={(v) => setOff((prev) => {
                            const next = new Set(prev);
                            if (v) next.delete(s.position);
                            else next.add(s.position);
                            return next;
                          })}
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
                      <div className="rem-item" key={`${c.title}-${i}`}>
                        <div className="what"><b>{c.title}</b><small>мой шаг</small></div>
                        <button className="picked-item-x" aria-label="Убрать" onClick={() => setCustom((prev) => prev.filter((_, j) => j !== i))}>✕</button>
                      </div>
                    ))}
                    {custom.length === 0 && (
                      <div className="rem-item"><div className="what"><b className="muted" style={{ fontWeight: 500 }}>Пока пусто</b><small>например, «Договориться о замене справки»</small></div></div>
                    )}
                  </div>
                  <div className="card">
                    <div className="own-row">
                      <input
                        placeholder="Свой шаг"
                        aria-label="Название шага"
                        value={ownName}
                        className={ownAttempted && !ownName.trim() ? "invalid" : undefined}
                        onChange={(e) => setOwnName(e.target.value)}
                      />
                      <input className="date" type="date" aria-label="Срок" value={ownDate} onChange={(e) => setOwnDate(e.target.value)} />
                      <button className="add" onClick={addOwn} aria-label="Добавить">+</button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="foot">
        <Button disabled={!selected || busy || total === 0} onClick={create}>
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
