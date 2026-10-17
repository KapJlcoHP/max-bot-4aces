import { useEffect, useState } from "react";
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
  { key: "now", field: "notify_at_deadline", label: "В момент срока" },
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
  const [regions, setRegions] = useState<Region[]>([]);
  const [clinic, setClinic] = useState<Organization | null>(null);
  const [busy, setBusy] = useState(false);
  const [stepReminderBusy, setStepReminderBusy] = useState<StepReminderKey | null>(null);

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

  const pickRegion = async (title: string) => {
    if (busy || title === user.region) {
      setRegionSheet(false);
      return;
    }
    setBusy(true);
    try {
      await api.patch("/api/v1/me/settings", { region: title });
      refreshUser();
      setRegionSheet(false);
      showToast("Регион сохранён");
    } catch {
      showToast("Не удалось сохранить регион");
    } finally {
      setBusy(false);
    }
  };

  const clearClinic = async () => {
    if (busy || user.attached_clinic_id === null) return;
    setBusy(true);
    try {
      await api.patch("/api/v1/me/settings", { attached_clinic_id: null });
      setClinic(null);
      refreshUser();
      showToast("Поликлиника откреплена");
    } catch {
      showToast("Не удалось открепить поликлинику");
    } finally {
      setBusy(false);
    }
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
              onClick={() => setStepReminderSheet(true)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setStepReminderSheet(true); }
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
              subtitle={clinic ? `${clinic.title} · ${clinic.address}` : "Не выбрана"}
              after={<span className="cell-note">{clinic ? "Сменить" : "Выбрать"}</span>}
              showChevron
              onClick={() => nav(clinic ? `/orgs/${clinic.id}` : "/orgs")}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav(clinic ? `/orgs/${clinic.id}` : "/orgs"); }
              }}
            />
          </CellList>
          {clinic && <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic r"><I.trash size={18} /></div>}
              title="Открепить поликлинику"
              subtitle="История маршрута и медицинские записи сохранятся"
              after={<span className="cell-note">Удалить</span>}
              onClick={clearClinic}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); clearClinic(); }
              }}
            />
          </CellList>}
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
              title="Регион"
              subtitle={user.region || "Не выбран"}
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
        </div>
        <Button variant="secondary" onClick={() => setRegionSheet(false)}>Закрыть</Button>
      </Sheet>
      <Sheet open={stepReminderSheet} onClose={() => setStepReminderSheet(false)}>
        <h3>Напоминания о шагах</h3>
        <div className="sub">Выберите, когда получать напоминание о сроке текущего шага</div>
        <div style={{ display: "grid", gap: 4, margin: "10px 0 14px" }}>
          {STEP_REMINDER_OPTIONS.map(({ key, field, label }) => (
            <div className="rem-item" key={key}>
              <div className="what"><b>{label}</b></div>
              <Switch
                on={stepReminders[key]}
                onChange={(on) => toggleStepReminder(key, field, on)}
                label={label}
              />
            </div>
          ))}
        </div>
        <Button variant="secondary" onClick={() => setStepReminderSheet(false)}>Закрыть</Button>
      </Sheet>
      {toast}
    </div>
  );
}
