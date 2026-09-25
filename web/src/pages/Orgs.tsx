import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Organization } from "../types";
import { Badge } from "../components/ui";
import { I, SituationIcon } from "../icons";

const CHIPS = ["Все", "Поликлиники", "Диспансеры", "Центры"];

export default function Orgs() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [type, setType] = useState("Все");
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [error, setError] = useState(false);

  const load = () => {
    setError(false);
    setOrgs(null);
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (type !== "Все") params.set("org_type", type);
    api.get<Organization[]>(`/api/v1/orgs?${params}`)
      .then(setOrgs)
      .catch(() => setError(true));
  };

  useEffect(load, [q, type]);

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <div className="top">
        <div className="header" style={{ paddingBottom: 12 }}>
          <div className="h-row" style={{ justifyContent: "space-between" }}>
            <div className="h-title"><h1 style={{ fontSize: 24 }}>Организации</h1></div>
            <Badge color="blue">ДЕМО-ДАННЫЕ</Badge>
          </div>
          <div className="search" style={{ marginTop: 12 }}>
            <I.search size={18} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск поликлиники, больницы…" />
          </div>
          <div className="chips" style={{ marginTop: 12 }}>
            {CHIPS.map((c) => (
              <button key={c} className={`chip${type === c ? " active" : ""}`} onClick={() => setType(c)}>{c}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="screen-body">
        {error && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Не удалось загрузить организации</h2>
            <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={load}>Повторить</button>
          </div>
        )}
        {!error && orgs === null && (
          <>
            <div className="skel blk" />
            <div className="skel blk" />
          </>
        )}
        {orgs !== null && orgs.length === 0 && !error && (
          <div className="state-wrap">
            <I.building size={64} />
            <h2>Организации не найдены</h2>
            <p>Попробуйте изменить запрос или фильтр</p>
            <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={() => { setQ(""); setType("Все"); }}>
              Сбросить фильтры
            </button>
          </div>
        )}
        {orgs?.map((o) => (
          <div key={o.id} className="card press" onClick={() => nav(`/orgs/${o.id}`)}>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>{o.title}</h3>
            <p className="kv" style={{ marginTop: 8, color: "#8E8E93" }}>
              <I.pin size={16} />
              {o.address}
            </p>
            <div className="btn-row" style={{ marginTop: 12 }}>
              <a className="btn btn-secondary" style={{ height: 42, fontSize: 14, textDecoration: "none" }} href={`tel:${o.phone.replace(/[^+\d]/g, "")}`} onClick={(e) => e.stopPropagation()}>
                <I.phone size={16} />Позвонить
              </a>
              <button
                className="btn btn-primary"
                style={{ height: 42, fontSize: 14 }}
                onClick={(e) => {
                  e.stopPropagation();
                  window.open(`https://yandex.ru/maps/?text=${encodeURIComponent(o.address)}`, "_blank");
                }}
              >
                Показать путь
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
