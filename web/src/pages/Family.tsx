import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useApp } from "../App";
import type { FamilyAccess, FamilyInvite } from "../types";
import { Badge, BrandMark, Button, ErrorView, Header, LoadingView, useToast } from "../components/ui";
import { fmtDateNumeric } from "../format";
import { I } from "../icons";

function accessLabel(access: FamilyAccess): string {
  if (access.status === "active") return "Активен";
  if (access.status === "pending") return "Ожидает принятия";
  if (access.status === "expired") return "Истёк";
  return "Отозван";
}

export default function Family() {
  const { user } = useApp();
  const navigate = useNavigate();
  const [toast, showToast] = useToast();
  const [owned, setOwned] = useState<FamilyAccess[] | null>(null);
  const [observed, setObserved] = useState<FamilyAccess[] | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [inviteLabel, setInviteLabel] = useState("");
  const [invite, setInvite] = useState<FamilyInvite | null>(null);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [acceptCode, setAcceptCode] = useState("");
  const [acceptBusy, setAcceptBusy] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [ownerRows, viewerRows] = await Promise.all([
        api.get<FamilyAccess[]>("/api/v1/family/access"),
        api.get<FamilyAccess[]>("/api/v1/family/observed"),
      ]);
      setOwned(ownerRows);
      setObserved(viewerRows);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const createInvite = async () => {
    if (inviteBusy) return;
    setInviteBusy(true);
    try {
      const result = await api.post<FamilyInvite>("/api/v1/family/access/invite", {
        label: inviteLabel.trim() || "Помощник",
        expires_days: 7,
      });
      setInvite(result);
      setInviteLabel("");
      setOwned((rows) => rows ? [result.access, ...rows] : rows);
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось создать приглашение");
    } finally {
      setInviteBusy(false);
    }
  };

  const copyInvite = async () => {
    if (!invite) return;
    try {
      await navigator.clipboard?.writeText(invite.code);
      showToast("Код скопирован");
    } catch {
      showToast("Передайте этот код родственнику вручную");
    }
  };

  const accept = async () => {
    if (!acceptCode.trim() || acceptBusy) return;
    setAcceptBusy(true);
    try {
      const access = await api.post<FamilyAccess>("/api/v1/family/access/accept", { code: acceptCode.trim() });
      setObserved((rows) => [access, ...(rows ?? []).filter((row) => row.id !== access.id)]);
      setAcceptCode("");
      showToast("Доступ принят");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось принять приглашение");
    } finally {
      setAcceptBusy(false);
    }
  };

  const revoke = async (accessId: number) => {
    if (revokeBusy !== null) return;
    setRevokeBusy(accessId);
    try {
      const updated = await api.del<FamilyAccess>(`/api/v1/family/access/${accessId}`);
      setOwned((rows) => rows?.map((row) => row.id === updated.id ? updated : row) ?? rows);
      showToast("Доступ отозван");
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : "Не удалось отозвать доступ");
    } finally {
      setRevokeBusy(null);
    }
  };

  return (
    <div className="app narrow">
      <Header title="Семейный доступ" subtitle="Помощник видит данные только для чтения" back="/profile" right={<BrandMark />} />
      <div className="screen-body">
        {status === "loading" && <LoadingView />}
        {status === "error" && <ErrorView onRetry={() => void load()} />}
        {status === "ready" && (
          <>
            <div className="card family-info-card">
              <div className="family-info-icon"><I.users size={24} /></div>
              <div>
                <h3 className="h3">Помощь близкому</h3>
                <p className="muted">Родственник сможет посмотреть маршрут, визиты и общие статусы. Изменять данные и видеть сырые измерения он не сможет.</p>
              </div>
            </div>

            <div className="section-h"><b>Мои помощники</b></div>
            <div className="card">
              <div className="field"><input value={inviteLabel} onChange={(e) => setInviteLabel(e.target.value)} placeholder="Имя помощника, например Иван" aria-label="Имя помощника" /></div>
              <Button onClick={createInvite} disabled={inviteBusy}>{inviteBusy ? "Создаём…" : "Создать одноразовый код"}</Button>
              {invite && (
                <div className="family-invite-code" role="status">
                  <span>Передайте родственнику этот код. Он действует 7 дней и используется один раз.</span>
                  <strong>{invite.code}</strong>
                  <Button variant="secondary" onClick={copyInvite}>Скопировать код</Button>
                </div>
              )}
            </div>

            {owned && owned.length > 0 && <div className="family-access-list">
              {owned.map((access) => (
                <div className="card family-access-card" key={access.id}>
                  <div className="family-access-top">
                    <div>
                      <h3 className="h3">{access.viewer_name || access.label}</h3>
                      <p className="muted">{access.status === "active" ? "Помощник по маршруту" : "Приглашение для помощника"}</p>
                    </div>
                    <Badge color={access.status === "active" ? "green" : access.status === "pending" ? "blue" : "gray"}>{accessLabel(access)}</Badge>
                  </div>
                  <p className="muted">Видит: маршрут, визиты, статусы дневников и лекарств</p>
                  <p className="cell-note">{access.status === "active" ? `До ${fmtDateNumeric(access.expires_at)}` : `Действует до ${fmtDateNumeric(access.expires_at)}`}</p>
                  {(access.status === "active" || access.status === "pending") && <Button variant="secondary" onClick={() => void revoke(access.id)} disabled={revokeBusy === access.id}>{revokeBusy === access.id ? "Отзываем…" : "Отозвать доступ"}</Button>}
                </div>
              ))}
            </div>}

            <div className="section-h"><b>Я помогаю другим</b></div>
            <div className="card">
              <p className="muted">Введите одноразовый код, который передал владелец маршрута.</p>
              <div className="field"><input value={acceptCode} onChange={(e) => setAcceptCode(e.target.value)} placeholder="XXXX-XXXX-XXXX" aria-label="Код приглашения" autoCapitalize="characters" /></div>
              <Button variant="secondary" onClick={accept} disabled={acceptBusy || !acceptCode.trim()}>{acceptBusy ? "Проверяем…" : "Принять приглашение"}</Button>
            </div>

            {observed && observed.length > 0 && <div className="family-access-list">
              {observed.map((access) => (
                <button type="button" className="card family-observed-card" key={access.id} onClick={() => navigate(`/family/view/${access.id}`)}>
                  <div className="family-access-top">
                    <div><h3 className="h3">Маршрут {access.owner_name}</h3><p className="muted">Только просмотр</p></div>
                    <I.chev size={18} />
                  </div>
                  <p className="muted">Маршрут, визиты и агрегированные статусы здоровья</p>
                </button>
              ))}
            </div>}
          </>
        )}
      </div>
      {toast}
    </div>
  );
}
