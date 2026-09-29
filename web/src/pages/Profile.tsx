import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CellList, CellSimple, Radio } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import { useApp } from "../App";
import type { Region } from "../types";
import { Button, Header, Sheet, Switch, UserAvatar, useToast } from "../components/ui";
import { I } from "../icons";

export default function Profile() {
  const nav = useNavigate();
  const { user, refreshUser } = useApp();
  const [toast, showToast] = useToast();
  const [notif, setNotif] = useState(user.notifications_on);
  const [regionSheet, setRegionSheet] = useState(false);
  const [regions, setRegions] = useState<Region[]>([]);
  const [busy, setBusy] = useState(false);

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

  const consentDate = fmtDayMonth(user.consent_at);

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
              before={<div className="ic"><I.users size={18} /></div>}
              title="Семейный доступ"
              after={<span className="cell-note">Управление</span>}
              showChevron
              onClick={() => nav("/family")}
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
            />
          </CellList>
          <CellList mode="island">
            <CellSimple
              className="press"
              before={<div className="ic"><I.info size={18} /></div>}
              title="О приложении"
              subtitle={`Данные и приватность${consentDate ? ` · согласие от ${consentDate}` : ""}`}
              showChevron
              onClick={() => nav("/about")}
            />
          </CellList>
      </div>

      <Sheet open={regionSheet} onClose={() => setRegionSheet(false)}>
        <h3>Ваш регион</h3>
        <div className="sub">Пока организуются приёмы в выбранном регионе</div>
        <div style={{ display: "grid", gap: 4, margin: "10px 0 14px" }}>
          {regions.map((r) => (
            <button
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
      {toast}
    </div>
  );
}
