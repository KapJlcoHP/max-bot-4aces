import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CellSimple, Input } from "@maxhub/max-ui";
import { api } from "../api";
import type { Situation } from "../types";
import { Button, ErrorView, Header, useToast } from "../components/ui";
import { SituationIcon } from "../icons";

export default function Catalog() {
  const nav = useNavigate();
  const [items, setItems] = useState<Situation[] | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const [toast, showToast] = useToast();

  const load = useCallback(() => {
    setError(false);
    setItems(null);
    api.get<Situation[]>("/api/v1/catalog").then(setItems).catch(() => setError(true));
  }, []);

  useEffect(load, [load]);

  const choose = async (key: string) => {
    if (busy) return;
    setBusy(key);
    try {
      await api.post("/api/v1/route/start", { situation_key: key });
      nav("/route");
    } catch {
      showToast("Не удалось создать маршрут. Попробуйте ещё раз.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Header title="Что вам сейчас нужно?" back="/" />
      <div className="screen-body catalog-body">
        {error && <ErrorView onRetry={load} />}
        {searching && <Input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Опишите ситуацию или найдите услугу" aria-label="Поиск ситуации" />}
        {items === null && !error && <div className="skel blk" />}
        {items?.filter((s) => `${s.title} ${s.description}`.toLowerCase().includes(query.trim().toLowerCase())).map((s) => (
          <CellSimple key={s.key} as="button" surface="island" className="catalog-cell" onClick={() => choose(s.key)} disabled={busy !== null}
            innerClassNames={{ title: "catalog-title", subtitle: "catalog-subtitle" }}
            before={<span className="row-ico"><SituationIcon name={s.icon} /></span>}
            title={s.title} subtitle={s.description} after={busy === s.key ? "Создаём…" : <SituationIcon name="chev" size={20} />}
          />
        ))}
      </div>
      {!error && <div className="foot catalog-foot"><Button className="btn btn-primary" onClick={() => setSearching(true)}>Свяжите ситуацию</Button></div>}
      {toast}
    </>
  );
}
