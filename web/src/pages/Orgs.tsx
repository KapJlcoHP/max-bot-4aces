import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { openExternalLink } from "../bridge";
import { useApp } from "../App";
import type { Organization, Region } from "../types";
import { Input } from "@maxhub/max-ui";
import { Button, Header, LoadingView } from "../components/ui";
import { I } from "../icons";
import OrganizationMap from "../components/OrganizationMap";

const CHIPS = ["Все", "Больницы", "Поликлиники", "Диспансеры", "Центры"];

export default function Orgs() {
  const nav = useNavigate();
  const { user } = useApp();
  const [q, setQ] = useState("");
  const [type, setType] = useState("Все");
  const [region, setRegion] = useState(user.region || "Все");
  const [regions, setRegions] = useState<Region[]>([]);
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(user.attached_clinic_id);
  const [mapAvailable, setMapAvailable] = useState<boolean | null>(null);
  const [error, setError] = useState(false);
  const requestId = useRef(0);

  const handleMapAvailability = useCallback((available: boolean) => {
    setMapAvailable(available);
  }, []);

  const focusOrganization = (organization: Organization) => {
    if (mapAvailable === true) {
      setSelectedId(organization.id);
      document.getElementById("organization-map-anchor")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    openExternalLink(`https://yandex.ru/maps/?text=${encodeURIComponent(organization.address)}`);
  };

  const load = useCallback(() => {
    const id = ++requestId.current;
    setError(false);
    setOrgs(null);
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (type !== "Все") params.set("org_type", type);
    if (region !== "Все") params.set("region", region);
    api.get<Organization[]>(`/api/v1/orgs?${params}`)
      .then((results) => { if (id === requestId.current) setOrgs(results); })
      .catch(() => { if (id === requestId.current) setError(true); });
  }, [q, type, region]);

  useEffect(() => {
    api.get<Region[]>("/api/v1/regions").then((items) => {
      setRegions(items);
      setRegion((current) => current !== "Все" && current && !items.some((item) => item.title === current) ? "Все" : current);
    }).catch(() => setRegions([]));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, q.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [load, q]);

  return (
    <div className="app">
      <div>
        <Header title="Организации" subtitle={region === "Все" ? "Все регионы" : `Регион: ${region}`} back="/" />
        <div className="org-search">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск поликлиники, больницы…" iconBefore={<I.search size={18} />} aria-label="Поиск организаций" />
          <div className="chips" style={{ marginTop: 12 }}>
            {CHIPS.map((c) => (
              <button key={c} className={`chip${type === c ? " on" : ""}`} onClick={() => setType(c)}>{c}</button>
            ))}
          </div>
          <select className="tz-select" value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Регион">
            <option value="Все">Все регионы</option>
            {regions.map((item) => <option key={item.key} value={item.title}>{item.title}</option>)}
          </select>
        </div>
      </div>
      <div className="screen-body cards-2">
        {orgs !== null && orgs.length > 0 && !error && (
          <div id="organization-map-anchor">
            <OrganizationMap
              organizations={orgs}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onAvailabilityChange={handleMapAvailability}
            />
          </div>
        )}
        {error && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Не удалось загрузить организации</h2>
            <Button style={{ marginTop: 14 }} onClick={load}>Повторить</Button>
          </div>
        )}
        {!error && orgs === null && (
          <LoadingView />
        )}
        {orgs !== null && orgs.length === 0 && !error && (
          <div className="state-wrap">
            <I.building size={64} />
            <h2>Организации не найдены</h2>
            <p>Попробуйте изменить запрос или фильтр</p>
              <Button style={{ marginTop: 14 }} onClick={() => { setQ(""); setType("Все"); setRegion("Все"); }}>
              Сбросить фильтры
            </Button>
          </div>
        )}
        {orgs?.map((o) => (
          <div key={o.id} className={`card press${user.attached_clinic_id === o.id ? " selected-clinic" : ""}`} onClick={() => nav(`/orgs/${o.id}`)}>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>
              {o.title}
              {!user.region && o.region && <span className="badge-mine" style={{ marginLeft: 8 }}>{o.region}</span>}
            </h3>
            <p className="kv" style={{ marginTop: 8, color: "#8E8E93" }}>
              <I.pin size={16} />
              {o.address}
            </p>
            <div className="btn-row" style={{ marginTop: 12 }}>
              <a className="btn secondary" style={{ height: 42, fontSize: 14, textDecoration: "none" }} href={`tel:${o.phone.replace(/[^+\d]/g, "")}`} onClick={(e) => e.stopPropagation()}>
                <I.phone size={16} />Позвонить
              </a>
              <Button
                variant="primary"
                style={{ height: 42, fontSize: 14 }}
                onClick={(e) => {
                  e.stopPropagation();
                  focusOrganization(o);
                }}
              >
                {mapAvailable === true ? "Показать на карте" : "Показать путь"}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
