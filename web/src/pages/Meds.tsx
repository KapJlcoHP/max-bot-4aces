import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import type { MedsOut } from "../types";
import { Button, ErrorView, Header, LoadingView, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

export default function Meds() {
  const [toast, showToast] = useToast();
  const [meds, setMeds] = useState<MedsOut | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sheet, setSheet] = useState(false);
  const [name, setName] = useState("");
  const [time, setTime] = useState("");
  const [times, setTimes] = useState<string[]>([]);
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<MedsOut>("/api/v1/meds")
      .then((m) => { setMeds(m); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const toggleIntake = async (courseId: number, atTime: string) => {
    if (!meds) return;
    try {
      const slot = await api.post<MedsOut["today"][number]>(`/api/v1/meds/${courseId}/intake-toggle`, { at_time: atTime });
      setMeds({
        ...meds,
        today: meds.today.map((s) =>
          s.course_id === slot.course_id && s.at_time === slot.at_time ? slot : s,
        ),
      });
    } catch {
      showToast("Не удалось отметить приём");
    }
  };

  const addTimeChip = () => {
    const t = time.trim();
    if (!t) return;
    if (times.includes(t)) {
      showToast("Это время уже добавлено");
      return;
    }
    setTimes((prev) => [...prev, t].sort());
    setTime("");
  };

  const removeTimeChip = (t: string) => setTimes((prev) => prev.filter((x) => x !== t));

  const addCourse = async () => {
    const nameOk = !!name.trim();
    const timesOk = times.length > 0;
    setAttempted(true);
    if (!nameOk || !timesOk || busy) {
      showToast("Заполните название и хотя бы одно время приёма");
      return;
    }
    setBusy(true);
    try {
      const m = await api.post<MedsOut>("/api/v1/meds", {
        name: name.trim(),
        times,
        until: until || null,
      });
      setMeds(m);
      setSheet(false);
      setName("");
      setTimes([]);
      setTime("");
      setUntil("");
      setAttempted(false);
      showToast("Курс добавлен — бот напомнит о приёме");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось добавить курс");
    } finally {
      setBusy(false);
    }
  };

  const disable = async (courseId: number) => {
    if (!meds) return;
    try {
      setMeds(await api.post<MedsOut>(`/api/v1/meds/${courseId}/disable`));
      showToast("Курс завершён");
    } catch {
      showToast("Не удалось завершить курс");
    }
  };

  const takenCount = meds?.today.filter((s) => s.taken).length ?? 0;

  if (status === "error") {
    return (
      <div className="app">
        <Header title="Приём лекарств" back="/health" />
        <ErrorView onRetry={load} />
      </div>
    );
  }

  return (
    <div className="app">
      <Header title="Приём лекарств" subtitle={meds && meds.today.length ? `Сегодня принято ${takenCount} из ${meds.today.length}` : "Напоминания включены"} back="/health" />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "ready" && meds && (
          <div className="split">
            <div className="col">
              <div className="section-h"><b>Сегодня</b></div>
              {meds.today.length === 0 ? (
                <div className="card empty-card">
                  <div className="empty-ico"><I.pill size={20} /></div>
                  <b style={{ fontSize: 14.5 }}>Приёмов на сегодня нет</b>
                  <div className="muted">Добавьте курс — расписание появится здесь, бот напомнит вовремя.</div>
                </div>
              ) : (
                <div className="card" style={{ padding: "8px 16px" }}>
                  {meds.today.map((s) => (
                    <div className="rem-item" key={`${s.course_id}-${s.at_time}`}>
                      <div className={`when${s.taken ? " done-pill" : ""}`}>{s.at_time}</div>
                      <div className="what">
                        <b>{s.name}</b>
                        <small>
                          {s.taken && s.taken_at
                            ? `Принято в ${s.taken_at.slice(11, 16)}`
                            : "Предстоит · бот напомнит"}
                        </small>
                      </div>
                      <button
                        className={`pick${s.taken ? " on" : ""}`}
                        style={{ height: 32, padding: "0 12px" }}
                        onClick={() => toggleIntake(s.course_id, s.at_time)}
                      >
                        {s.taken ? "✓" : "Принять"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="col">
              <div className="section-h"><b>Мои курсы</b></div>
              {meds.courses.length === 0 ? (
                <div className="card muted" style={{ textAlign: "center", padding: 18 }}>Курсов пока нет</div>
              ) : (
                <div className="card docs-card">
                  {meds.courses.map((c) => (
                    <div className="doc" key={c.id}>
                      <span className="ck pill-ck"><I.pill size={12} /></span>
                      {c.name}
                      <small>
                        {c.times.length === 1 ? "1 р/день" : `${c.times.length} р/день`}
                        {c.until ? ` · до ${fmtDayMonth(c.until)}` : ""}
                      </small>
                      <button className="link-red" onClick={() => disable(c.id)}>завершить</button>
                    </div>
                  ))}
                </div>
              )}

              <button className="card press" style={{ width: "100%", textAlign: "left" }} onClick={() => setSheet(true)}>
                <div className="kv" style={{ alignItems: "center", color: "var(--blue)", fontWeight: 800 }}>
                  <I.plus size={20} />
                  Добавить лекарство или витамины
                </div>
                <div className="muted" style={{ marginTop: 8 }}>
                  Название, время приёма и длительность курса — бот напомнит вовремя.
                </div>
              </button>
            </div>
          </div>
        )}
      </div>

      <Sheet open={sheet} onClose={() => setSheet(false)}>
        <h3>Новый курс</h3>
        <div className="sub">Название и время приёма (можно несколько) — бот напомнит о каждом приёме</div>
        <div className="own-row" style={{ marginBottom: 10 }}>
          <input
            placeholder="Например, Магний B6"
            value={name}
            className={attempted && !name.trim() ? "invalid" : undefined}
            onChange={(e) => setName(e.target.value)}
            aria-label="Название"
          />
        </div>
        {times.length > 0 && (
          <div className="chip-times" style={{ marginBottom: 10 }}>
            {times.map((t) => (
              <span className="chip-time" key={t}>
                {t}
                <button onClick={() => removeTimeChip(t)} aria-label={`Убр��ть ${t}`}>✕</button>
              </span>
            ))}
          </div>
        )}
        <div className="own-row">
          <input
            className="date"
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            aria-label="Время приёма"
          />
          <button className="add" onClick={addTimeChip} disabled={!time} aria-label="Добавить время приёма">+</button>
          <input
            className="date"
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            aria-label="До какой даты (необязательно)"
          />
        </div>
        <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
          {attempted && times.length === 0
            ? "Выберите время приёма и нажмите «+» — можно добавить несколько"
            : "Время приёма + «+» — так добавляется несколько приёмов в день"}
        </div>
        <Button style={{ marginTop: 14 }} disabled={busy} onClick={addCourse}>
          Добавить курс
        </Button>
      </Sheet>
      {toast}
    </div>
  );
}
