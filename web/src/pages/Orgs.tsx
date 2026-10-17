import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { openExternalLink } from "../bridge";
import { useApp } from "../App";
import type { Organization, Region } from "../types";
import { Input } from "@maxhub/max-ui";
import { Button, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";
import OrganizationMap from "../components/OrganizationMap";
import { canChooseClinic, ClinicConfirmation, CLINIC_NOTICE, useClinicChoice } from "../components/ClinicChoice";

const CHIPS = ["Все", "Больницы", "Поликлиники", "Диспансеры", "Центры"];

export default function Orgs() {
  const nav = useNavigate();
  const { user } = useApp();
  const changeMode = new URLSearchParams(useLocation().search).get("mode") === "change";
  const [toast, showToast] = useToast();
  const [q, setQ] = useState("");
  const [type, setType] = useState(changeMode ? "Поликлиники" : "Все");
  const [region, setRegion] = useState(user.region || "Все");
  const [regions, setRegions] = useState<Region[]>([]);
  const [orgs, setOrgs] = useState<Organization[] | null>(null);
  const [error, setError] = useState(false);
  const choice = useClinicChoice(changeMode, showToast);
  const detailPath = (id: number) => `/orgs/${id}${changeMode ? "?mode=change" : ""}`;
  const requestId = useRef(0);

  const load = useCallback(() => {
    const id = ++requestId.current;
    setError(false);
    setOrgs(null);
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (changeMode || type !== "Все") params.set("org_type", changeMode ? "Поликлиники" : type);
    if (changeMode || region !== "Все") params.set("region", changeMode ? user.region : region);
    api.get<Organization[]>(`/api/v1/orgs?${params}`)
      .then((results) => { if (id === requestId.current) setOrgs(results); })
      .catch(() => { if (id === requestId.current) setError(true); });
  }, [q, type, region, changeMode, user.region]);

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
        <Header title={changeMode ? "Выбор поликлиники" : "Организации"} subtitle={`Регион: ${changeMode ? user.region : region}`} back={changeMode ? "/profile" : "/"} />
        {changeMode && <div className="card" role="status"><b>Выберите поликлинику вашего региона</b><p>Текущий выбор сохранится до подтверждения нового.</p><p className="muted">{CLINIC_NOTICE}</p><Button variant="secondary" onClick={() => nav("/profile")}>Отмена</Button></div>}
        {choice.conflicted && <div role="alert">Обновите профиль перед новым выбором.<Button onClick={() => choice.refresh().catch(() => showToast("Не удалось обновить профиль"))}>Обновить профиль</Button></div>}
        <div className="org-search">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Поиск поликлиники, больницы…" iconBefore={<I.search size={18} />} aria-label="Поиск организаций" />
          <div className="chips" style={{ marginTop: 12 }}>
            {CHIPS.map((c) => (
               <button key={c} disabled={changeMode} className={`chip${type === c ? " on" : ""}`} onClick={() => setType(c)}>{c}</button>
            ))}
          </div>
          <select className="tz-select" disabled={changeMode} value={changeMode ? user.region : region} onChange={(e) => setRegion(e.target.value)} aria-label="Регион">
            <option value="Все">Все регионы</option>
            {regions.map((item) => <option key={item.key} value={item.title}>{item.title}</option>)}
          </select>
        </div>
      </div>
      <div className="screen-body cards-2">
        {orgs !== null && orgs.length > 0 && !error && (
          <OrganizationMap
            organizations={orgs}
            onSelect={(id) => nav(detailPath(id))}
          />
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
              <Button style={{ marginTop: 14 }} onClick={() => { setQ(""); setType(changeMode ? "Поликлиники" : "Все"); setRegion(changeMode ? user.region : "Все"); }}>
              Сбросить фильтры
            </Button>
          </div>
        )}
        {orgs?.map((o) => (
          <div
            key={o.id}
            className={`card press${user.attached_clinic_id === o.id ? " selected-clinic" : ""}`}
            role="button"
            tabIndex={0}
            aria-label={`Открыть организацию ${o.title}`}
            onClick={() => nav(detailPath(o.id))}
            onKeyDown={(e) => {
              if (e.target !== e.currentTarget) return;
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                nav(detailPath(o.id));
              }
            }}
          >
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
                  openExternalLink(`https://yandex.ru/maps/?text=${encodeURIComponent(o.address)}`);
                }}
              >
                Показать путь
              </Button>
            </div>
            {user.attached_clinic_id === o.id && <p role="status">Текущая поликлиника</p>}
            {canChooseClinic(o, user, changeMode) && (
              <Button
                variant="secondary"
                style={{ height: 42, fontSize: 14, marginTop: 10 }}
                disabled={choice.busy || choice.conflicted}
                onClick={(e) => { e.stopPropagation(); choice.choose(o); }}
              >
                Выбрать поликлинику
              </Button>
            )}
          </div>
        ))}
      </div>
      {toast}
      <ClinicConfirmation choice={choice} />
    </div>
  );
}
