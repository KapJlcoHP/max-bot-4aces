import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { openExternalLink } from "../bridge";
import type { Organization } from "../types";
import { useApp } from "../App";
import { Button, Header, LoadingView, useToast } from "../components/ui";
import { I } from "../icons";
import OrganizationMap from "../components/OrganizationMap";

export default function OrgDetail() {
  const { orgId } = useParams();
  const nav = useNavigate();
  const { user, updateUser } = useApp();
  const [org, setOrg] = useState<Organization | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, showToast] = useToast();
  const loadRequestId = useRef(0);

  useEffect(() => {
    const requestId = ++loadRequestId.current;
    setOrg(null);
    setError(false);
    api.get<Organization>(`/api/v1/orgs/${orgId}`)
      .then((result) => {
        if (requestId === loadRequestId.current) setOrg(result);
      })
      .catch(() => {
        if (requestId === loadRequestId.current) setError(true);
      });
  }, [orgId]);

  const isClinic = org?.org_type === "Поликлиники";
  const isAttached = Boolean(org && user.attached_clinic_id === org.id);

  const toggleClinic = async () => {
    if (!org || !isClinic || busy) return;
    if (isAttached) {
      nav("/orgs");
      return;
    }
    const requestId = loadRequestId.current;
    setBusy(true);
    try {
      const updated = await api.patch<typeof user>("/api/v1/me/settings", {
        attached_clinic_id: org.id,
      });
      if (requestId !== loadRequestId.current) return;
      updateUser(updated);
      showToast("Поликлиника прикреплена");
    } catch {
      if (requestId === loadRequestId.current) showToast("Не удалось выбрать поликлинику — попробуйте ещё раз");
    } finally {
      setBusy(false);
    }
  };

  const mapLink = org && org.lat !== null && org.lon !== null
    ? `https://yandex.ru/maps/?pt=${org.lon},${org.lat}&z=16&l=map`
    : org ? `https://yandex.ru/maps/?text=${encodeURIComponent(org.address)}` : "";

  return (
    <div className="app">
      <Header title={org?.title ?? "Организация"} subtitle="Подробная информация" back="/orgs" />
      <div className="screen-body">
        {error && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Организация не найдена</h2>
          </div>
        )}
        {!error && !org && <LoadingView />}
        {org && (
          <>
            <div className="card">
              <h3 className="h3" style={{ textTransform: "uppercase", fontSize: 12.5, letterSpacing: "0.05em", color: "var(--muted)" }}>
                Контакты и режим работы
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                <p className="kv"><I.pin size={17} />{org.address}</p>
                <a className="kv" href={`tel:${org.phone.replace(/[^+\d]/g, "")}`} style={{ color: "var(--blue)", fontWeight: 600 }}>
                  <I.phone size={17} />{org.phone}
                </a>
                <p className="kv"><I.clock size={17} />{org.hours}</p>
                {typeof org.lat === "number" && typeof org.lon === "number" && (
                  <p className="muted" style={{ marginLeft: 27 }}>Координаты: {org.lat}, {org.lon}</p>
                )}
              </div>
            </div>
            <div className="section-h">Расположение на карте</div>
            <OrganizationMap organizations={[org]} selectedId={org.id} onSelect={() => undefined} />
            <Button variant="secondary" onClick={() => openExternalLink(mapLink)}>Открыть карту в Яндексе</Button>
            {isClinic && (
              <>
                {isAttached && <p className="muted" role="status">Прикреплена к профилю</p>}
                <Button variant={isAttached ? "secondary" : "primary"} disabled={busy} onClick={toggleClinic}>
                  {busy ? "Сохраняем…" : isAttached ? "Сменить поликлинику" : "Прикрепить поликлинику"}
                </Button>
              </>
            )}
            <div className="card">
              <h3 className="h3" style={{ textTransform: "uppercase", fontSize: 12.5, letterSpacing: "0.05em", color: "var(--muted)" }}>
                Доступные услуги
              </h3>
              <ul className="bullet-list" style={{ marginTop: 12 }}>
                {org.services.map((s) => <li key={s}>{s}</li>)}
              </ul>
            </div>
          </>
        )}
      </div>
      {org && (
        <div className="foot">
          <div className="btn-row">
            <a className="btn secondary" href={`tel:${org.phone.replace(/[^+\d]/g, "")}`} style={{ textDecoration: "none" }}>
              Позвонить
            </a>
            <Button
              onClick={() => openExternalLink(mapLink)}
            >
              Показать маршрут
            </Button>
          </div>
        </div>
      )}
      {toast}
    </div>
  );
}
