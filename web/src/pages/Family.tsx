import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { initials } from "../format";
import type { FamilyMember } from "../types";
import { Avatar, Header, useToast } from "../components/ui";
import { I } from "../icons";

export default function Family() {
  const [toast, showToast] = useToast();
  const [rows, setRows] = useState<FamilyMember[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);

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
      showToast("Участник добавлен");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось добавить участника");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title="Семейный доступ" subtitle="Управление доступом к маршрутам" back="/profile" />
      <div className="screen-body">
        {status === "loading" && (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        )}
        {status === "ready" && rows !== null && (
          <>
            <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <Avatar text="Ан" size={52} fontSize={17} />
              <div className="row-body">
                <h3 style={{ fontSize: 16, fontWeight: 700 }}>Вы — владелец аккаунта</h3>
                <p>Ваши маршруты видны участникам ниже</p>
              </div>
            </div>
            <div className="section-label">Участники семьи</div>
            {rows.length === 0 && <div className="card muted">Пока никого не добавлено.</div>}
            {rows.map((m) => (
              <div key={m.id} className="row-item" style={{ cursor: "default" }}>
                <Avatar text={initials(m.name)} color={m.color} />
                <div className="row-body">
                  <h3>{m.name}</h3>
                  <p>{m.role}</p>
                </div>
              </div>
            ))}
            <div className="card">
              <h3 className="h3">Управление правами</h3>
              <p className="muted" style={{ marginTop: 8 }}>
                Добавленные участники смогут просматривать ваши медицинские маршруты,
                делиться своими и получать общие напоминания о визитах к врачу.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                <div className="field"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя и фамилия" /></div>
                <div className="field"><input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Кем приходится (например: Отец)" /></div>
              </div>
            </div>
          </>
        )}
      </div>
      <div className="foot">
        <button className="btn btn-primary" onClick={add} disabled={busy || !name.trim()}>
          {busy ? "Добавляем…" : "Добавить участника"}
        </button>
      </div>
      {toast}
    </div>
  );
}
