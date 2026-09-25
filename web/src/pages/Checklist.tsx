import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Checklist } from "../types";
import { Button, StateView, TabHeader, useToast } from "../components/ui";
import { I } from "../icons";

function CheckRow({ title, collected, onToggle }: { title: string; collected: boolean; onToggle: () => void }) {
  return (
    <button className={`check-row${collected ? " checked" : ""}`} onClick={onToggle}>
      <span className="cbx"><I.check size={15} /></span>
      <span className="lbl">{title}</span>
    </button>
  );
}

export default function Checklist() {
  const [toast, showToast] = useToast();
  const [data, setData] = useState<Checklist | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    api.get<Checklist>("/api/v1/checklist")
      .then((d) => { setData(d); setStatus("ready"); })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(load, []);

  const toggle = async (id: number) => {
    try {
      const item = await api.post<import("../types").ChecklistItem>(`/api/v1/checklist/${id}/toggle`);
      setData((d) => {
        if (!d) return d;
        const items = d.items.map((i) => (i.id === id ? item : i));
        return { ...d, items, collected: items.filter((i) => i.collected).length };
      });
    } catch {
      showToast("Не удалось обновить пункт");
    }
  };

  const add = async () => {
    const title = newTitle.trim();
    if (!title || busy) return;
    setBusy(true);
    try {
      const item = await api.post<import("../types").ChecklistItem>("/api/v1/checklist", { title });
      setData((d) => (d ? { ...d, items: [...d.items, item], total: d.total + 1 } : d));
      setNewTitle("");
      setAdding(false);
      showToast("Документ добавлен");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось добавить");
    } finally {
      setBusy(false);
    }
  };

  if (status === "error") {
    return (
      <div className="app" style={{ display: "flex", flexDirection: "column" }}>
        <TabHeader action={<I.plus size={22} />} actionLabel="Добавить документ" onAction={() => setAdding(true)} />
        <StateView
          icon={<div className="alert-circle"><I.alert size={30} /></div>}
          title="Ошибка загрузки списка"
          text="Попробуйте обновить позже"
          button="Обновить"
          onButton={load}
        />
      </div>
    );
  }

  const need = data?.items.filter((i) => !i.collected) ?? [];
  const collected = data?.items.filter((i) => i.collected) ?? [];

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <TabHeader action={<I.plus size={22} />} actionLabel="Добавить документ" onAction={() => setAdding(true)} />
      <div className="screen-body">
        {status === "loading" && (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        )}
        {status === "ready" && data && data.total === 0 && (
          <StateView
            icon={<I.doc size={64} />}
            title="Документы не добавлены"
            text="Начните собирать документы для вашего активного маршрута"
            button="Добавить документ"
            onButton={() => setAdding(true)}
          />
        )}
        {status === "ready" && data && data.total > 0 && (
          <>
            {need.length > 0 && <div className="section-label">Нужно собрать</div>}
            {need.map((i) => <CheckRow key={i.id} title={i.title} collected={false} onToggle={() => toggle(i.id)} />)}
            {collected.length > 0 && <div className="section-label">Собрано</div>}
            {collected.map((i) => <CheckRow key={i.id} title={i.title} collected onToggle={() => toggle(i.id)} />)}
          </>
        )}
      </div>
      {adding && <div className="foot">
        <div className="btn-row">
          <div className="field" style={{ flex: 1, height: 48 }}>
            <input
              autoFocus
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Название документа…"
              onKeyDown={(e) => e.key === "Enter" && add()}
            />
          </div>
          <Button className="btn btn-primary" style={{ width: 56, flex: "0 0 56px" }} onClick={add} disabled={busy} aria-label="Добавить документ">
            <I.plus size={20} />
          </Button>
        </div>
      </div>}
      {toast}
    </div>
  );
}
