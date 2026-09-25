import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { initials } from "../format";
import type { RouteDto, UserDto } from "../types";
import { Button, Avatar, TabHeader, Toggle, useToast } from "../components/ui";
import { I } from "../icons";

const ABOUT_TEXT =
  "МедМаршрут — мини-ап для платформы MAX: помогает пройти медицинский маршрут — " +
  "от записи к врачу до получения результатов. Команда 4Aces, хакатон MAX. " +
  "Справочник организаций и стартовые записи содержат демонстрационные данные.";

export default function Profile() {
  const nav = useNavigate();
  const [toast, showToast] = useToast();
  const [user, setUser] = useState<UserDto | null>(null);
  const [routeTitle, setRouteTitle] = useState("Не выбрана");
  const [modal, setModal] = useState<"about" | "privacy" | "region" | null>(null);

  useEffect(() => {
    api.get<UserDto>("/api/v1/me").then(setUser).catch(() => setUser(null));
    api.get<RouteDto | null>("/api/v1/route").then((route) => setRouteTitle(route?.title ?? "Не выбрана")).catch(() => setRouteTitle("Не выбрана"));
  }, []);

  const toggleNotifications = async () => {
    if (!user) return;
    try {
      const updated = await api.patch<UserDto>("/api/v1/me/settings", { notifications_on: !user.notifications_on });
      setUser(updated);
      showToast(updated.notifications_on ? "Уведомления включены" : "Уведомления выключены");
    } catch {
      showToast("Не удалось изменить настройку");
    }
  };

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <TabHeader />
      <div className="screen-body nopad">
        <div className="profile-head">
          <Avatar text={user ? initials(`${user.first_name} ${user.last_name}`) : "…"} size={88} fontSize={30} />
          <h2>{user ? `${user.first_name} ${user.last_name}`.trim() : "Загрузка…"}</h2>
          <p>{user?.email.endsWith("@demo.local") ? "Профиль MAX" : user?.email}</p>
        </div>
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="set-row">
            <span className="lbl">Уведомления</span>
            <Toggle on={user?.notifications_on ?? false} onChange={toggleNotifications} />
          </div>
          <button className="set-row" onClick={() => nav("/family")}>
            <span className="lbl">Семейный доступ</span>
            <span className="val">Управление</span>
            <span className="row-chev"><I.chev size={20} /></span>
          </button>
          <button className="set-row" onClick={() => nav("/health")}>
            <span className="lbl">Дневник здоровья</span>
            <span className="val">Давление и пульс</span>
            <span className="row-chev"><I.chev size={20} /></span>
          </button>
          <button className="set-row" onClick={() => setModal("region")}>
            <span className="lbl">Регион</span><span className="val">Москва</span><span className="row-chev"><I.chev size={20} /></span>
          </button>
          <button className="set-row" onClick={() => nav("/catalog")}>
            <span className="lbl">Ситуация</span><span className="val">{routeTitle}</span><span className="row-chev"><I.chev size={20} /></span>
          </button>
          <button className="set-row" onClick={() => setModal("about")}>
            <span className="lbl">О приложении</span>
            <span className="row-chev"><I.chev size={20} /></span>
          </button>
          <button className="set-row" onClick={() => setModal("privacy")}>
            <span className="lbl">Политика конфиденциальности</span>
            <span className="row-chev"><I.chev size={20} /></span>
          </button>
        </div>
      </div>

      {modal && (
        <div className="sheet-overlay" onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}>
          <div className="sheet">
            <div className="grab" />
            <h2>{modal === "about" ? "О приложении" : modal === "region" ? "Регион поиска" : "Политика конфиденциальности"}</h2>
            <p className="sub" style={{ textAlign: "left" }}>
              {modal === "about" ? ABOUT_TEXT : modal === "region" ? "В демонстрационном справочнике сейчас доступны организации Москвы." : (
                "Приложение работает с минимально необходимыми данными: идентификатор и имя из MAX " +
                "используются для входа. Медицинские показатели дневника хранятся только в демо-базе " +
                "приложения. Данные не передаются третьим лицам, интеграции с внешними системами — " +
                "модельные. Полная версия политики будет опубликована перед продуктивным запуском."
              )}
            </p>
            <Button className="btn btn-primary" onClick={() => setModal(null)}>Понятно</Button>
          </div>
        </div>
      )}
      {toast}
    </div>
  );
}
