import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { openExternalLink } from "../bridge";
import type { Organization } from "../types";
import { Button, Header } from "../components/ui";
import { I } from "../icons";

export default function OrgDetail() {
  const { orgId } = useParams();
  const [org, setOrg] = useState<Organization | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setOrg(null);
    setError(false);
    api.get<Organization>(`/api/v1/orgs/${orgId}`).then(setOrg).catch(() => setError(true));
  }, [orgId]);

  return (
    <div className="app" style={{ display: "flex", flexDirection: "column" }}>
      <Header title={org?.title ?? "Организация"} subtitle="Подробная информация" back="/orgs" />
      <div className="screen-body">
        {error && (
          <div className="state-wrap">
            <div className="alert-circle"><I.alert size={30} /></div>
            <h2>Организация не найдена</h2>
          </div>
        )}
        {!error && !org && <div className="skel blk" />}
        {org && (
          <>
            <div className="card">
              <h3 className="h3" style={{ textTransform: "uppercase", fontSize: 13, letterSpacing: "0.05em", color: "#8A8A8E" }}>
                Контакты и режим работы
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
                <p className="kv"><I.pin size={17} />{org.address}</p>
                <a className="kv" href={`tel:${org.phone.replace(/[^+\d]/g, "")}`} style={{ color: "#2563EB", fontWeight: 600 }}>
                  <I.phone size={17} />{org.phone}
                </a>
                <p className="kv"><I.clock size={17} />{org.hours}</p>
              </div>
            </div>
            <div className="section-label">Расположение на карте</div>
            <div
              className="map-ph"
              style={{ cursor: "pointer" }}
              onClick={() => openExternalLink(`https://yandex.ru/maps/?text=${encodeURIComponent(org.address)}`)}
            >
              <I.pin size={40} />
              <span>Открыть карту</span>
            </div>
            <div className="card">
              <h3 className="h3" style={{ textTransform: "uppercase", fontSize: 13, letterSpacing: "0.05em", color: "#8A8A8E" }}>
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
            <a className="btn btn-secondary" href={`tel:${org.phone.replace(/[^+\d]/g, "")}`} style={{ textDecoration: "none" }}>
              Позвонить
            </a>
            <Button
              className="btn btn-primary"
              onClick={() => openExternalLink(`https://yandex.ru/maps/?text=${encodeURIComponent(org.address)}`)}
            >
              Показать маршрут
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
