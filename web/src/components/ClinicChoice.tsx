import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { useApp } from "../App";
import type { ClinicChangePayload, Organization, UserDto } from "../types";
import { Button, Sheet } from "./ui";

export const CLINIC_NOTICE = "Настройка в МедМаршруте. Не оформляет официальное прикрепление";

export function canChooseClinic(org: Organization, user: UserDto, changeMode: boolean) {
  return org.org_type === "Поликлиники" && Boolean(user.region) && org.region === user.region
    && org.id !== user.attached_clinic_id && (changeMode || user.attached_clinic_id === null);
}

type Selection = { clinic: Organization; previous: Organization | null; payload: ClinicChangePayload };

export function useClinicChoice(changeMode: boolean, showToast: (message: string) => void) {
  const { user, updateUser } = useApp();
  const [previous, setPrevious] = useState<Organization | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [busy, setBusy] = useState(false);
  const [conflicted, setConflicted] = useState(false);
  const locked = useRef(false);
  useEffect(() => {
    let active = true;
    setPrevious(null);
    if (user.attached_clinic_id !== null) {
      api.get<Organization>(`/api/v1/orgs/${user.attached_clinic_id}`)
        .then((org) => { if (active) setPrevious(org); }).catch(() => undefined);
    }
    return () => { active = false; };
  }, [user.attached_clinic_id]);

  const choose = (clinic: Organization) => {
    if (locked.current || conflicted || !canChooseClinic(clinic, user, changeMode)) return;
    if (user.attached_clinic_id !== null && previous?.id !== user.attached_clinic_id) {
      showToast("Не удалось загрузить текущую поликлинику. Обновите страницу");
      return;
    }
    setSelection({ clinic, previous, payload: {
      attached_clinic_id: clinic.id, expected_clinic_id: user.attached_clinic_id, expected_region: user.region,
    } });
  };
  const refresh = async () => {
    const current = await api.get<UserDto>("/api/v1/me");
    updateUser(current);
    setConflicted(false);
  };
  const confirm = async () => {
    if (locked.current || !selection || conflicted) return;
    locked.current = true;
    setBusy(true);
    try {
      const updated = await api.post<UserDto>("/api/v1/me/clinic", selection.payload);
      updateUser(updated);
      setSelection(null);
      showToast("Поликлиника сохранена");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setSelection(null);
        setConflicted(true);
        try { await refresh(); } catch { /* Explicit refresh remains available. */ }
        showToast("Профиль изменился. Проверьте данные и подтвердите выбор заново");
      } else {
        showToast("Не удалось сохранить поликлинику. Ваш выбор сохранён для повторной попытки");
      }
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  return { choose, confirm, selection, busy, conflicted, refresh, cancel: () => {
    if (!locked.current) setSelection(null);
  } };
}

export function ClinicConfirmation({ choice }: { choice: ReturnType<typeof useClinicChoice> }) {
  const { selection, busy, confirm, cancel } = choice;
  return <Sheet open={selection !== null} onClose={cancel}>
    <h3>{selection?.previous ? "Сменить поликлинику?" : "Выбрать поликлинику?"}</h3>
    <p>Сейчас: {selection?.previous ? `${selection.previous.title} · ${selection.previous.address}` : "Поликлиника не выбрана"}</p>
    <p>Новый выбор: {selection?.clinic.title} · {selection?.clinic.address}</p>
    <p className="muted">{CLINIC_NOTICE}</p>
    <Button disabled={busy} onClick={confirm}>{busy ? "Сохраняем…" : "Подтвердить выбор"}</Button>
    <Button variant="secondary" disabled={busy} onClick={cancel}>Отмена</Button>
  </Sheet>;
}
