import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { openExternalLink } from "../bridge";
import { useApp } from "../App";
import type { Organization, Region } from "../types";
import { Input } from "@maxhub/max-ui";
import { Button, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";
import OrganizationMap from "../components/OrganizationMap";
import { canChooseClinic, ClinicConfirmation, CLINIC_NOTICE, useClinicChoice } from "../components/ClinicChoice";

const CHIPS = ["Все", "Больницы", "Поликлиники", "Диспансеры", "Центры"];
const EMPTY_ORGS: Organization[] = [];
type LinkState = { key: string; status: "ready" | "invalid" | "missing" | "error" | "unavailable"; org?: Organization };
type Results = { key: string; items: Organization[]; error: boolean };

function hasCoordinates(org: Organization) {
  return typeof org.lat === "number" && typeof org.lon === "number"
    && Number.isFinite(org.lat) && Number.isFinite(org.lon)
    && org.lat >= -90 && org.lat <= 90 && org.lon >= -180 && org.lon <= 180;
}

// The public Organization DTO has no verification flag; these two entries are
// explicitly identified as synthetic in content/SOURCES.md.
function isDemo(org: Organization) {
  return org.title === "Городская поликлиника №12" || org.title === "ГКБ им. С.П. Боткина №3";
}

function focusTarget(id: string) {
  const target = document.getElementById(id);
  target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  target?.focus({ preventScroll: true });
}

export default function Orgs() {
  const nav = useNavigate();
  const { orgId } = useParams();
  const { user } = useApp();
  const changeMode = new URLSearchParams(useLocation().search).get("mode") === "change";
  const [toast, showToast] = useToast();
  const [q, setQ] = useState("");
  const [type, setType] = useState(changeMode ? "Поликлиники" : "Все");
  const [region, setRegion] = useState(user.region || "Все");
  const [regions, setRegions] = useState<Region[]>([]);
  const [results, setResults] = useState<Results | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [link, setLink] = useState<LinkState | null>(null);
  const [linkAttempt, setLinkAttempt] = useState(0);
  const choice = useClinicChoice(changeMode, showToast);
  const requestId = useRef(0);
  const pendingFocusId = useRef<number | null>(null);
  const effectiveRegion = changeMode ? user.region : region;
  const effectiveType = changeMode ? "Поликлиники" : type;
  const linkKey = `${orgId ?? ""}:${changeMode}:${user.region}`;
  const currentLink = orgId && link?.key === linkKey ? link : null;
  const linkLoading = Boolean(orgId && !currentLink);
  const linkBlocked = Boolean(orgId && (!currentLink || !["ready", "unavailable"].includes(currentLink.status)));
  const filterKey = JSON.stringify([q.trim(), effectiveType, effectiveRegion, linkKey, linkAttempt]);

  // Also called synchronously by filter handlers: a pending response becomes
  // obsolete before the debounce timer (or the next effect) can run.
  const invalidate = () => { ++requestId.current; setResults(null); };

  useEffect(() => {
    let active = true;
    api.get<Region[]>("/api/v1/regions").then((items) => { if (active) setRegions(items); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    ++requestId.current;
    setResults(null);
    setSelectedId(null);
    if (!orgId) { setLink(null); return; }
    setLink(null);
    if (!/^[1-9]\d*$/.test(orgId) || !Number.isSafeInteger(Number(orgId))) {
      setLink({ key: linkKey, status: "invalid" });
      return;
    }
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then((org) => {
      if (!active) return;
      if (!org) { setLink({ key: linkKey, status: "missing" }); return; }
      if (changeMode && (org.org_type !== "Поликлиники" || !user.region || org.region !== user.region)) {
        setLink({ key: linkKey, status: "unavailable" });
        return;
      }
      if (!changeMode) { setRegion(org.region || "Все"); setType(org.org_type); }
      setQ("");
      setSelectedId(org.id);
      setLink({ key: linkKey, status: "ready", org });
    }).catch((error: unknown) => {
      if (active) setLink({ key: linkKey, status: error instanceof ApiError && error.status === 404 ? "missing" : "error" });
    });
    return () => { active = false; };
  }, [orgId, linkKey, linkAttempt, changeMode, user.region]);

  const load = useCallback(() => {
    const id = ++requestId.current;
    setResults(null);
    if (linkBlocked) return;
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (effectiveType !== "Все") params.set("org_type", effectiveType);
    // Explicit empty region means all regions; omission means profile region.
    params.set("region", effectiveRegion === "Все" ? "" : effectiveRegion);
    api.get<Organization[]>(`/api/v1/orgs?${params}`)
      .then((items) => { if (id === requestId.current) setResults({ key: filterKey, items, error: false }); })
      .catch(() => { if (id === requestId.current) setResults({ key: filterKey, items: [], error: true }); });
  }, [q, effectiveType, effectiveRegion, filterKey, linkBlocked]);

  useEffect(() => {
    ++requestId.current;
    setResults(null);
    const timer = window.setTimeout(load, q.trim() ? 250 : 0);
    return () => { window.clearTimeout(timer); ++requestId.current; };
  }, [load, q]);

  const currentResults = results?.key === filterKey && !linkBlocked ? results : null;
  const error = Boolean(currentResults?.error);
  // Both views receive this exact array, including the defensive mode lock.
  const orgs = useMemo(() => {
    if (!currentResults || currentResults.error) return EMPTY_ORGS;
    const items = [...currentResults.items];
    const linkedOrg = currentLink?.org;
    if (linkedOrg && !items.some((org) => org.id === linkedOrg.id)) items.push(linkedOrg);
    const query = q.trim().toLocaleLowerCase("ru");
    return items.filter((org) => (!effectiveRegion || effectiveRegion === "Все" || org.region === effectiveRegion)
      && (!changeMode || Boolean(user.region))
      && (effectiveType === "Все" || org.org_type === effectiveType)
      && (!query || `${org.title} ${org.address}`.toLocaleLowerCase("ru").includes(query)));
  }, [currentResults, currentLink, q, effectiveRegion, effectiveType, changeMode, user.region]);
  const selected = orgs.find((org) => org.id === selectedId);

  useEffect(() => {
    if (currentResults && !currentResults.error && selectedId !== null && !orgs.some((org) => org.id === selectedId)) setSelectedId(null);
  }, [currentResults, orgs, selectedId]);

  const select = (id: number) => {
    if (!orgs.some((org) => org.id === id)) return;
    pendingFocusId.current = id;
    setSelectedId(id);
  };
  useEffect(() => {
    const id = pendingFocusId.current;
    if (id === null || selectedId !== id) return;
    pendingFocusId.current = null;
    focusTarget(`org-card-${id}`);
  }, [selectedId]);
  const reset = () => {
    if (!q && effectiveType === (changeMode ? "Поликлиники" : "Все") && effectiveRegion === (changeMode ? user.region : "Все")) return;
    invalidate(); setQ(""); setType(changeMode ? "Поликлиники" : "Все"); setRegion(changeMode ? user.region : "Все");
  };
  const back = orgId ? `/orgs${changeMode ? "?mode=change" : ""}` : changeMode ? "/profile" : "/";

  return (
    <div className="app">
      <Header title={changeMode ? "Выбор поликлиники" : "Организации"} subtitle={`Регион: ${effectiveRegion || "Все"}`} back={back} />
      {changeMode && <div className="card" role="status"><b>Выберите поликлинику вашего региона</b><p>Текущий выбор сохранится до подтверждения нового.</p><p className="muted">{CLINIC_NOTICE}</p><Button variant="secondary" onClick={() => nav("/profile")}>Отмена</Button></div>}
      {choice.conflicted && <div role="alert">Обновите профиль перед новым выбором.<Button onClick={() => choice.refresh().catch(() => showToast("Не удалось обновить профиль"))}>Обновить профиль</Button></div>}
      <div className="org-search">
        <Input value={q} onChange={(e) => { if (q !== e.target.value) { invalidate(); setQ(e.target.value); } }} placeholder="Поиск поликлиники, больницы…" iconBefore={<I.search size={18} />} aria-label="Поиск организаций" />
        <div className="chips" style={{ marginTop: 12 }}>
          {CHIPS.map((chip) => <button key={chip} disabled={changeMode} className={`chip${effectiveType === chip ? " on" : ""}`} aria-pressed={effectiveType === chip} onClick={() => { if (!changeMode && type !== chip) { invalidate(); setType(chip); } }}>{chip}</button>)}
        </div>
        <select className="tz-select" disabled={changeMode} value={effectiveRegion} onChange={(e) => { if (!changeMode && region !== e.target.value) { invalidate(); setRegion(e.target.value); } }} aria-label="Регион">
          <option value="Все">Все регионы</option>
          {effectiveRegion && effectiveRegion !== "Все" && !regions.some((item) => item.title === effectiveRegion) && <option value={effectiveRegion}>{effectiveRegion}</option>}
          {regions.map((item) => <option key={item.key} value={item.title}>{item.title}</option>)}
        </select>
      </div>
      <div className="screen-body org-screen">
        {linkLoading && <div role="status"><LoadingView /><p>Загружаем организацию по ссылке…</p></div>}
        {currentLink?.status === "invalid" && <div role="alert"><h2>Некорректная ссылка на организацию</h2><p>Идентификатор должен быть целым положительным числом.</p></div>}
        {currentLink?.status === "missing" && <div role="alert"><h2>Организация не найдена</h2><p>Возможно, запись была удалена. Откройте список организаций.</p></div>}
        {currentLink?.status === "error" && <div role="alert"><h2>Не удалось загрузить организацию</h2><p>Проверьте соединение и повторите попытку.</p><Button onClick={() => { invalidate(); setLink(null); setLinkAttempt((attempt) => attempt + 1); }}>Повторить загрузку организации</Button></div>}
        {currentLink?.status === "unavailable" && <div role="alert"><h2>Организация недоступна для выбора</h2><p>В этом режиме доступны только поликлиники региона профиля: {user.region || "регион не задан"}. Ниже показан доступный список.</p></div>}
        {orgId && currentLink && currentLink.status !== "ready" && <Button variant="secondary" onClick={() => nav(`/orgs${changeMode ? "?mode=change" : ""}`)}>К списку организаций</Button>}
        <section id="org-map" tabIndex={-1} aria-label="Карта организаций">
          <OrganizationMap organizations={orgs} selectedId={selected?.id ?? null} onSelect={select} />
        </section>
        <section id="org-list" tabIndex={-1} aria-label="Список организаций" aria-busy={!currentResults && !linkBlocked}>
          {error && <div className="state-wrap" role="alert"><div className="alert-circle"><I.alert size={30} /></div><h2>Не удалось загрузить организации</h2><Button onClick={load}>Повторить</Button></div>}
          {!currentResults && !linkBlocked && <LoadingView />}
          {currentResults && !error && orgs.length === 0 && <div className="state-wrap"><I.building size={64} /><h2>Организации не найдены</h2><p>Попробуйте изменить запрос или фильтр</p><Button onClick={reset}>Сбросить фильтры</Button></div>}
          <div className="org-cards">
            {orgs.map((org) => {
              const expanded = selected?.id === org.id;
              const mapped = hasCoordinates(org);
              const demo = isDemo(org);
              const phone = org.phone.replace(/[^+\d]/g, "");
              const callable = !demo && /^\+?\d{5,15}$/.test(phone);
              const attached = user.attached_clinic_id === org.id;
              return <article key={org.id} id={`org-card-${org.id}`} tabIndex={-1} className={`card org-card${expanded ? " org-card-selected" : ""}${attached ? " selected-clinic" : ""}`}>
                <button type="button" className="org-card-select" aria-expanded={expanded} aria-controls={`org-details-${org.id}`} onClick={() => select(org.id)}>
                  <span className="org-card-heading">
                    <h3>{org.title}</h3>
                    {attached && <span className="attached-clinic-badge" aria-label="Прикреплённая поликлиника" title="Прикреплённая поликлиника"><I.pin size={15} /><span className="sr-only">Прикреплённая поликлиника</span></span>}
                  </span>
                  <p className="muted">{org.org_type} · {org.region}</p><p className="kv"><I.pin size={16} />{org.address || "Адрес не указан"}</p><span className="org-card-hint">{expanded ? "Подробности открыты" : "Показать подробности"}</span>
                </button>
                {expanded && <div id={`org-details-${org.id}`} className="org-details">
                  {demo && <p role="note">Модельная организация. Телефон и другие данные демонстрационные, не для обращения за медицинской помощью.</p>}
                  <h4>Контакты и режим работы</h4>
                  <p className="kv"><I.phone size={17} />{callable ? <a href={`tel:${phone}`}>{org.phone}</a> : <span>{org.phone || "Телефон не указан"}</span>}</p>
                  <p className="kv"><I.clock size={17} />{org.hours || "Режим работы не указан"}</p>
                  {!demo && <p className="muted">Телефон и часы работы справочные. Актуальность уточняйте на официальном сайте организации.</p>}
                  <h4>Доступные услуги</h4>
                  {org.services.length ? <ul className="bullet-list">{org.services.map((service) => <li key={service}>{service}</li>)}</ul> : <p>Услуги не указаны</p>}
                  {!mapped && <p role="status">Координаты не указаны или некорректны. Организация доступна в списке; точка на карте не показана.</p>}
                  <div className="org-jumps">
                    {mapped && <Button variant="secondary" onClick={() => focusTarget("org-map")}>К точке на карте</Button>}
                    <Button variant="secondary" onClick={() => openExternalLink(mapped ? `https://yandex.ru/maps/?rtext=~${org.lat},${org.lon}&rtt=auto` : `https://yandex.ru/maps/?text=${encodeURIComponent(org.address)}`)}>{mapped ? "Построить путь" : "Искать адрес в Яндексе"}</Button>
                  </div>
                  {org.org_type === "Поликлиники" && org.region !== user.region && <p className="muted">Для выбора доступны только поликлиники региона профиля.</p>}
                </div>}
                {canChooseClinic(org, user, changeMode) && <Button variant="secondary" disabled={choice.busy || choice.conflicted} onClick={() => choice.choose(org)}>Выбрать поликлинику</Button>}
              </article>;
            })}
          </div>
        </section>
      </div>
      {toast}
      <ClinicConfirmation choice={choice} />
    </div>
  );
}
