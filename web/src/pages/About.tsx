import { useState } from "react";
import { CellList, CellSimple } from "@maxhub/max-ui";
import { api } from "../api";
import { fmtDayMonth } from "../format";
import { useApp } from "../App";
import { Button, Header, Sheet, useToast } from "../components/ui";
import { I } from "../icons";

export default function About() {
  const { user } = useApp();
  const [toast, showToast] = useToast();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  const deleteData = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.del("/api/v1/me/data");
      setConfirm(false);
      showToast("Профиль и все данные удалены");
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
          <CellSimple title="Где хранится" subtitle="На нашем сервере по защищённому соединению; доступ — только из вашего приложения" separator />
          <CellSimple title="Согласие" subtitle={user.consent_at ? `Оформлено ${fmtDayMonth(user.consent_at)}` : "Не оформлено"} separator />
          <CellSimple title="Право на удаление" subtitle="Можно удалить профиль МедМаршрута и все связанные с ним данные в разделе ниже" separator />
          <CellSimple title="Демо-данные" subtitle="Показанные примеры синтетические, персональные данные не собираются" separator />
        </CellList>

        <section className="card danger-zone" aria-labelledby="danger-zone-title" aria-describedby="danger-zone-warning">
          <h2 id="danger-zone-title"><I.alert size={20} />Опасная зона</h2>
          <p>Удаление профиля МедМаршрута сотрёт маршруты и шаги, дневники и заметки, лекарства и отметки приёма, напоминания, список семьи и настройки.</p>
          <p id="danger-zone-warning"><strong>Это действие необратимо. Восстановить данные не получится.</strong></p>
          <Button variant="danger" disabled={busy} onClick={() => setConfirm(true)}>
            <I.trash size={18} /><span>Удалить профиль и все данные</span>
          </Button>
        </section>

        <div className="muted" style={{ fontSize: 12.5, textAlign: "center" }}>
          Хакатон MAX · кейс «Забота о людях» · команда 4Aces
        </div>
      </div>

      <Sheet open={confirm} onClose={() => { if (!busy) setConfirm(false); }}>
        <h3>Удалить профиль и все данные?</h3>
        <div className="sub">Профиль МедМаршрута и все связанные с ним данные будут удалены навсегда. Отменить удаление или восстановить данные не получится.</div>
        <div className="btn-row" style={{ marginTop: 6 }}>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirm(false)}>Отмена</Button>
          <Button variant="danger" disabled={busy} onClick={deleteData}>{busy ? "Удаляем…" : "Удалить навсегда"}</Button>
        </div>
      </Sheet>
      {toast}
    </div>
  );
}
