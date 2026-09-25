import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Situation } from "../types";
import { Header } from "../components/ui";
import { SituationIcon } from "../icons";

export default function Catalog() {
  const nav = useNavigate();
  const [items, setItems] = useState<Situation[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.get<Situation[]>("/api/v1/catalog").then(setItems).catch(() => setItems([]));
  }, []);

  const choose = async (key: string) => {
    if (busy) return;
    setBusy(key);
    try {
      if (key === "family") {
        nav("/family");
        return;
      }
      await api.post("/api/v1/route/start", { situation_key: key });
      nav("/route");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Header title="Что вам сейчас нужно?" subtitle="Выберите медицинскую ситуацию" back="/" />
      <div className="screen-body">
        {items === null && <div className="skel blk" />}
        {items?.map((s) => (
          <button key={s.key} className="row-item" onClick={() => choose(s.key)} disabled={busy !== null}>
            <div className="row-ico">
              <SituationIcon name={s.icon} />
            </div>
            <div className="row-body">
              <h3>{s.title}</h3>
              <p>{s.description}</p>
            </div>
            {busy === s.key ? <span className="muted">Создаём…</span> : <span className="row-chev"><SituationIcon name="chev" size={20} /></span>}
          </button>
        ))}
      </div>
    </>
  );
}
