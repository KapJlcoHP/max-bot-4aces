import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CellList, CellSimple, Radio } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import { useApp } from "../App";
import type { Organization, Region, UserDto } from "../types";
import { Button, Header, Sheet, Switch, UserAvatar, useToast } from "../components/ui";
import { I } from "../icons";

const STEP_REMINDER_OPTIONS = [
  { key: "day", field: "notify_day_before", label: "За день до срока" },
  { key: "hour", field: "notify_hour_before", label: "За час до срока" },
  { key: "now", field: "notify_at_deadline", label: "В день / момент срока" },
] as const;

type StepReminderKey = (typeof STEP_REMINDER_OPTIONS)[number]["key"];
type StepReminderState = Record<StepReminderKey, boolean>;

export default function Profile() {
  const nav = useNavigate();
  const { user, refreshUser, updateUser } = useApp();
  const [toast, showToast] = useToast();
  const [notif, setNotif] = useState(user.notifications_on);
  const [regionSheet, setRegionSheet] = useState(false);
  const [stepReminderSheet, setStepReminderSheet] = useState(false);
  const [stepReminders, setStepReminders] = useState<StepReminderState>({
    day: user.notify_day_before ?? true,
    hour: user.notify_hour_before ?? true,
    now: user.notify_at_deadline ?? true,
  });
  const [stepDayBeforeTime, setStepDayBeforeTime] = useState(user.step_day_before_time ?? "09:00");
  const [regions, setRegions] = useState<Region[]>([]);
  const [clinic, setClinic] = useState<Organization | null>(null);
  const [busy, setBusy] = useState(false);
  const regionLock = useRef(false);
  const [regionChange, setRegionChange] = useState<{ title: string; city: string | null; expected_region: string; expected_clinic_id: number | null; clinicLabel: string } | null>(null);
  const [stepReminderBusy, setStepReminderBusy] = useState<StepReminderKey | null>(null);
  const [stepDayBeforeTimeBusy, setStepDayBeforeTimeBusy] = useState(false);

  useEffect(() => {
    if (user.attached_clinic_id === null) {
      setClinic(null);
      return;
    }
    let active = true;
    api.get<Organization>(`/api/v1/orgs/${user.attached_clinic_id}`)
      .then((item) => { if (active) setClinic(item); })
      .catch(() => { if (active) setClinic(null); });
    return () => { active = false; };
  }, [user.attached_clinic_id]);

  useEffect(() => {
    if (!regionSheet || regions.length > 0) return;
    api.get<Region[]>("/api/v1/regions").then(setRegions).catch(() => setRegions([]));
  }, [regionSheet, regions.length]);

  const toggleNotif = async (on: boolean) => {
    setNotif(on);
    try {
      await api.patch("/api/v1/me/settings", { notifications_on: on });
      refreshUser();
    } catch {
      setNotif(!on);
      showToast("Не удалось изменить настройку");
    }
  };

  const toggleStepReminder = async (key: StepReminderKey, field: string, on: boolean) => {
    if (stepReminderBusy) return;
    setStepReminderBusy(key);
    setStepReminders((current) => ({ ...current, [key]: on }));
    try {
      const updated = await api.patch<UserDto>("/api/v1/me/settings", { [field]: on });
      updateUser(updated);
      showToast("Настройка сохранена");
    } catch {
      setStepReminders((current) => ({ ...current, [key]: !on }));
      showToast("Не удалось изменить настройку");
    } finally {
      setStepReminderBusy(null);
    }
  };

  const saveStepDayBeforeTime = async (value: string) => {
    if (stepDayBeforeTimeBusy || !value || value === (user.step_day_before_time ?? "09:00")) return;
    setStepDayBeforeTimeBusy(true);
    try {
      const updated = await api.patch<UserDto>("/api/v1/me/settings", { step_day_before_time: value });
      updateUser(updated);
      showToast("Время напоминаний сохранено");
    } catch {
      setStepDayBeforeTime(user.step_day_before_time ?? "09:00");
      showToast("Не удалось сохранить время");
    } finally {
      setStepDayBeforeTimeBusy(false);
    }
  };

  const openStepReminderSheet = () => {
    setStepDayBeforeTime(user.step_day_before_time ?? "09:00");
    setStepReminderSheet(true);
  };

  const saveRegion = async (change: NonNullable<typeof regionChange>) => {
    if (regionLock.current) return;
    regionLock.current = true;
    setBusy(true);
    try {
      const updated = await api.patch<UserDto>("/api/v1/me/settings", {
        region: change.title, ...(change.city !== null ? { city: change.city } : {}), expected_region: change.expected_region,
        expected_clinic_id: change.expected_clinic_id, confirm_clinic_reset: change.expected_clinic_id !== null,
      });
      updateUser(updated);
      setRegionChange(null);
      setRegionSheet(false);
      showToast("Регион сохранён");
    } catch (error) {
      if (error && typeof error === "object" && "status" in error && error.status === 409) {
        setRegionChange(null);
        setRegionSheet(false);
        try { updateUser(await api.get<UserDto>("/api/v1/me")); } catch { /* Old profile remains visible. */ }
        showToast("Профиль изменился. Проверьте данные и выберите регион заново");
      } else showToast("Не удалось сохранить регион");
    } finally {
      regionLock.current = false;
      setBusy(false);
    }
  };

  const pickRegion = (title: string) => {
    if (regionLock.current) return;
    if (title === user.region) {
      setRegionSheet(false);
      return;
    }
    const change = { title, city: title === user.region ? user.city : null, expected_region: user.region, expected_clinic_id: user.attached_clinic_id,
      clinicLabel: clinic ? `${clinic.title} · ${clinic.address}` : "Текущая поликлиника" };
    if (user.attached_clinic_id !== null) {
      setRegionSheet(false);
      setRegionChange(change);
    } else void saveRegion(change);
  };

  const consentDate = fmtDayMonth(user.consent_at);
  const enabledStepReminders = STEP_REMINDER_OPTIONS
    .filter(({ key }) => stepReminders[key])
    .map(({ label }) => label.toLowerCase())
    .join(", ");

  return (
    <div className="app narrow">
      <Header title="Профиль" />
      <div className="screen-body">
        <div className="profile-head">
          <UserAvatar name={`${user.first_name} ${user.last_name}`.trim()} url={user.avatar_url} size={64} />
          <b>{user.first_name} {user.last_name}</b>
          <small>Профиль MAX</small>
        </div>

        <CellList mode="island">
            <CellSimple
              before={<div className="ic"><I.bell size={18} /></div>}
              title="Уведомления"
              subtitle="Напоминания приходят в чат MAX"
              after={<Switch on={notif} onChange={toggleNotif} label="Уведомления" />}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.clock size={18} /></div>}
              title="Напоминания о шагах"
              subtitle={enabledStepReminders || "Напоминания о сроках отключены"}
              after={<span className="cell-note">Настроить</span>}
              showChevron
              onClick={openStepReminderSheet}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openStepReminderSheet(); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.users size={18} /></div>}
              title="Семейный доступ"
              after={<span className="cell-note">Управление</span>}
              showChevron
              onClick={() => nav("/family")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/family"); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.pin size={18} /></div>}
              title="Прикрепленная поликлиника"
              subtitle={clinic ? `${clinic.title} · ${clinic.address}` : user.attached_clinic_id !== null ? "Поликлиника выбрана · данные недоступны" : "Не выбрана"}
              after={<span className="cell-note">{user.attached_clinic_id !== null ? "Сменить" : "Выбрать"}</span>}
              showChevron
              onClick={() => nav("/orgs?mode=change")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/orgs?mode=change"); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic g"><I.pulse size={18} /></div>}
              title="Здоровье"
              subtitle="Давление · вес · сахар · самочувствие"
              showChevron
              onClick={() => nav("/health")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/health"); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.pin size={18} /></div>}
              title="Город и регион"
              subtitle={user.region ? `${user.city ? `${user.city} · ` : ""}${user.region}` : "Не выбран"}
              after={<span className="cell-note">Изменить</span>}
              showChevron
              onClick={() => setRegionSheet(true)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setRegionSheet(true); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic r"><I.pill size={18} /></div>}
              title="Приём лекарств"
              subtitle="Курсы и напоминания"
              showChevron
              onClick={() => nav("/meds")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/meds"); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.doc size={18} /></div>}
              title="Частые вопросы"
              subtitle="Ответы о возможностях приложения"
              showChevron
              onClick={() => nav("/faq")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/faq"); }
              }}
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.info size={18} /></div>}
              title="О приложении"
              subtitle={`Данные и удаление профиля${consentDate ? ` · согласие от ${consentDate}` : ""}`}
              showChevron
              onClick={() => nav("/about")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav("/about"); }
              }}
            />
          </CellList>
      </div>

      <Sheet open={regionSheet} onClose={() => setRegionSheet(false)}>
        <h3>Ваш регион</h3>
        <div className="sub">Пока организуются приёмы в выбранном регионе</div>
        <div style={{ display: "grid", gap: 4, margin: "10px 0 14px" }}>
          {regions.map((r) => (
            <button
              type="button"
              key={r.key}
              className="rem-item press"
              style={{ textAlign: "left", border: "none", background: "none", cursor: "pointer" }}
              onClick={() => pickRegion(r.title)}
            >
              <div className="what"><b>{r.title}</b>{r.pilot && <small>регион пилота</small>}</div>
              <Radio checked={user.region === r.title} readOnly aria-label={r.title} />
            </button>
          ))}
          {regions.length === 0 && <div className="muted" style={{ padding: "8px 0" }}>Список регионов недоступен</div>}
          {user.region && regions.find((item) => item.title === user.region)?.cities?.length ? <>
            <div className="sub" style={{ marginTop: 10 }}>Город</div>
            {regions.find((item) => item.title === user.region)!.cities!.map((item) => (
              <button type="button" key={item.key} className="rem-item press" style={{ textAlign: "left", border: "none", background: "none", cursor: "pointer" }}
                onClick={() => void saveRegion({ title: user.region, city: item.title, expected_region: user.region, expected_clinic_id: user.attached_clinic_id, clinicLabel: clinic ? `${clinic.title} · ${clinic.address}` : "Текущая поликлиника" })}>
                <div className="what"><b>{item.title}</b></div><Radio checked={user.city === item.title} readOnly aria-label={item.title} />
              </button>
            ))}
          </> : null}
        </div>
        <Button variant="secondary" onClick={() => setRegionSheet(false)}>Закрыть</Button>
      </Sheet>
      <Sheet open={regionChange !== null} onClose={() => { if (!regionLock.current) setRegionChange(null); }}>
        <h3>Изменить регион?</h3>
        <p>Новый регион: {regionChange?.title}</p>
        <p>{regionChange?.clinicLabel} будет убрана из профиля. Выберите поликлинику нового региона после сохранения. История и медицинские записи сохранятся.</p>
        <Button disabled={busy} onClick={() => { if (regionChange) void saveRegion(regionChange); }}>{busy ? "Сохраняем…" : "Изменить регион и сбросить поликлинику"}</Button>
        <Button variant="secondary" disabled={busy} onClick={() => setRegionChange(null)}>Отмена</Button>
      </Sheet>
      <Sheet open={stepReminderSheet} onClose={() => setStepReminderSheet(false)}>
        <h3>Напоминания о шагах</h3>
        <div className="sub">Напоминания получает только текущий шаг. «За час» работает, если у события указано точное время.</div>
        <div style={{ display: "grid", gap: 4, margin: "10px 0 14px" }}>
          {STEP_REMINDER_OPTIONS.map(({ key, field, label }) => (
            <div className="rem-item" key={key}>
              <div className="what"><b>{label}</b></div>
              <Switch
                on={stepReminders[key]}
                onChange={(on) => toggleStepReminder(key, field, on)}
                label={label}
              />
              {key === "day" && (
                <label className="push-time">
                  <small>Время напоминаний по дате</small>
                  <input
                    type="time"
                    value={stepDayBeforeTime}
                    disabled={(!stepReminders.day && !stepReminders.now) || stepDayBeforeTimeBusy}
                    onChange={(e) => setStepDayBeforeTime(e.target.value)}
                    onBlur={(e) => saveStepDayBeforeTime(e.target.value)}
                    aria-label="Время напоминаний по дате"
                  />
                </label>
              )}
            </div>
          ))}
        </div>
        <p className="muted">Если у шага есть дата без времени, напомним накануне и в день срока в выбранный час — при включённых вариантах. Это время уведомления, а не время приёма.</p>
        <Button variant="secondary" onClick={() => setStepReminderSheet(false)}>Закрыть</Button>
      </Sheet>
      {toast}
    </div>
  );
}
