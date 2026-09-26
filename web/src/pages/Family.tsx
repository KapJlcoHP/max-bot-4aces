import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { initials } from "../format";
import { useApp } from "../App";
import type { FamilyMember } from "../types";
import { Button, Avatar, BrandMark, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";

export default function Family() {
  const { user } = useApp();
  const [toast, showToast] = useToast();
  const [rows, setRows] = useState<FamilyMember[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<FamilyMember[]>("/api/v1/family")
      .then((r) => { setRows(r); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const add = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const row = await api.post<FamilyMember>("/api/v1/family", { name: name.trim(), role: role.trim() || "Родственник" });
      setRows((r) => [...(r ?? []), row]);
      setName("");
      setRole("");
      setShowForm(false);
      showToast("Участник добавлен");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось добавить участника");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app narrow">
      <Header title="Семейный доступ" subtitle="Управление доступом к маршрутам" back="/profile" right={<BrandMark />} />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "ready" && rows !== null && (
          <>
            <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <Avatar text={initials(`${user.first_name} ${user.last_name}`)} size={52} />
              <div className="row-body">
                <h3 style={{ fontSize: 16, fontWeight: 700 }}>{`${user.first_name} ${user.last_name}`.trim()}</h3>
                <p>Владелец аккаунта · демонстрационный список</p>
              </div>
            </div>
            <div className="section-h"><b>Участники семьи</b></div>
            {rows.length === 0 && <div className="card muted">Пока никого не добавлено.</div>}
            {rows.map((m) => (
              <div key={m.id} className="row-item" style={{ cursor: "default" }}>
                <Avatar text={initials(m.name)} color={m.color === "pink" ? "red" : "blue"} />
                <div className="row-body">
                  <h3>{m.name}</h3>
                  <p>{m.role}</p>
                </div>
              </div>
            ))}
            <div className="card">
              <h3 className="h3">Управление правами</h3>
              <p className="muted" style={{ marginTop: 8 }}>
                Здесь можно составить список участников семьи. Совместный доступ к маршрутам
                и общим напоминаниям пока не подключён.
              </p>
              {showForm && <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                <div className="field"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя и фамилия" /></div>
                <div className="field"><input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Кем приходится (например: Отец)" /></div>
              </div>}
            </div>
          </>
        )}
      </div>
      <div className="foot">
        <Button onClick={showForm ? add : () => setShowForm(true)} disabled={busy || (showForm && !name.trim())}>
          {busy ? "Добавляем…" : showForm ? "Сохранить участника" : "Добавить участника"}
        </Button>
      </div>
      {toast}
    </div>
  );
}
