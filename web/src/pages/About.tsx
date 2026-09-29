import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CellList, CellSimple } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import { useApp } from "../App";
import { Button, Header, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

export default function About() {
  const nav = useNavigate();
  const { user } = useApp();
  const [toast, showToast] = useToast();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  const deleteData = async () => {
    setBusy(true);
    try {
      await api.del("/api/v1/me/data");
      setConfirm(false);
      showToast("Данные удалены");
      setTimeout(() => window.location.reload(), 800);
    } catch {
      setBusy(false);
      showToast("Не удалось удалить данные");
    }
  };

  return (
    <div className="app narrow">
      <Header title="О приложении" back="/profile" />
      <div className="screen-body">
        <div className="card">
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <img src="/medroute-logo.svg" width={44} height={44} alt="Логотип МедМаршрут" />
            <div>
              <b style={{ fontSize: 16 }}>МедМаршрут</b>
              <div className="muted" style={{ fontSize: 13 }}>Помощник в медицинских маршрутах · мини-ап для MAX</div>
            </div>
          </div>
        </div>

        <div className="section-h"><b>Данные и приватность</b></div>
        <CellList mode="island">
          <CellSimple title="Что мы обрабатываем" subtitle="Профиль из MAX (имя, аватар), шаги маршрутов и заметки, записи дневников здоровья, курсы лекарств" separator />
          <CellSimple title="Где хранится" subtitle="На нашем сервере; приложение и бот используют записи для маршрута и напоминаний" separator />
          <CellSimple title="Согласие" subtitle={user.consent_at ? `Оформлено ${fmtDayMonth(user.consent_at)}` : "Не оформлено"} separator />
          <CellSimple title="Удаление данных" subtitle="Кнопка ниже удаляет ваш профиль, маршруты, дневники и курсы" separator />
          <CellSimple title="Демо-данные" subtitle="Примеры синтетические; после согласия профиль MAX и введённые вами записи сохраняются на сервере" separator />
        </CellList>

        <Button variant="secondary" onClick={() => setConfirm(true)}>
          <I.trash size={18} /> Удалить мои данные
        </Button>

        <div className="muted" style={{ fontSize: 12.5, textAlign: "center" }}>
          Хакатон MAX · кейс «Забота о людях» · команда 4Aces
        </div>
      </div>

      <Sheet open={confirm} onClose={() => setConfirm(false)}>
        <h3>Удалить все мои данные?</h3>
        <div className="sub">Маршруты, шаги, дневники, курсы лекарств и напоминания будут стёрты. Это нельзя отменить.</div>
        <div className="btn-row" style={{ marginTop: 6 }}>
          <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button disabled={busy} onClick={deleteData}>{busy ? "Удаляем…" : "Удалить"}</Button>
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
