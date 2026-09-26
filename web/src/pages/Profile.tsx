import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CellList, CellSimple } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import { useApp } from "../App";
import { Avatar, Header, Switch, useToast } from "../components/ui";
import { I } from "../icons";

export default function Profile() {
  const nav = useNavigate();
  const { user, refreshUser } = useApp();
  const [toast, showToast] = useToast();
  const [notif, setNotif] = useState(user.notifications_on);

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

  const consentDate = fmtDayMonth(user.consent_at);

  return (
    <div className="app">
      <Header title="Профиль" />
      <div className="screen-body">
        <div className="profile-head">
          <Avatar text={`${user.first_name[0] ?? ""}${user.last_name[0] ?? ""}`.toUpperCase() || "Я"} size={64} color="red" />
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
      {toast}
    </div>
  );
}
