import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { ConsentPayload, HealthSetting, HealthType, Organization, Region, UserDto } from "../types";
import { Button, Switch } from "../components/ui";
import { I } from "../icons";
import { Input } from "@maxhub/max-ui";
import OrganizationMap from "../components/OrganizationMap";

const DIARY_META: { key: HealthType; title: string; hint: string; on: boolean }[] = [
  { key: "bp", title: "Давление и пульс", hint: "нужен тонометр", on: true },
  { key: "weight", title: "Вес", hint: "нужны напольные весы", on: true },
  { key: "sugar", title: "Сахар крови", hint: "нужен глюкометр", on: false },
  { key: "mood", title: "Самочувствие", hint: "без приборов", on: true },
];

export default function Onboarding() {
  const { user, updateUser } = useApp();
  const [step, setStep] = useState(0);
  const [agreed, setAgreed] = useState(false);
  const [diaries, setDiaries] = useState(DIARY_META);
  const [busy, setBusy] = useState(false);
  const [regions, setRegions] = useState<Region[]>([]);
  const [regionsLoading, setRegionsLoading] = useState(true);
  const [regionsError, setRegionsError] = useState(false);
  const [region, setRegion] = useState(user.region || "");
  const [city, setCity] = useState(user.city || "");
  const [clinics, setClinics] = useState<Organization[] | null>(null);
  const [clinicsLoading, setClinicsLoading] = useState(false);
  const [clinicsError, setClinicsError] = useState(false);
  const [clinicRetry, setClinicRetry] = useState(0);
  const [attachedClinicId, setAttachedClinicId] = useState<number | null>(null);
  const [clinicQuery, setClinicQuery] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const clinicsRequestId = useRef(0);
  const submitting = useRef(false);

  const availableRegions = regions.filter((item) => item.pilot || regions.every((candidate) => candidate.pilot === undefined));

  const loadRegions = () => {
    setRegionsLoading(true);
    setRegionsError(false);
    api.get<Region[]>("/api/v1/regions")
      .then((items) => {
        setRegions(items);
        if (region && !items.some((item) => item.title === region)) { setRegion(""); setCity(""); }
        const selected = items.find((item) => item.title === region);
        if (city && selected?.cities?.length && !selected.cities.some((item) => item.title === city)) setCity("");
      })
      .catch(() => setRegionsError(true))
      .finally(() => setRegionsLoading(false));
  };

  useEffect(loadRegions, []);

  useEffect(() => {
    const requestId = ++clinicsRequestId.current;
    setAttachedClinicId(null);
    setClinicQuery("");
    setClinics(null);
    setClinicsError(false);
    if (!region) {
      setClinicsLoading(false);
      return;
    }
    setClinicsLoading(true);
    const params = new URLSearchParams({ org_type: "Поликлиники", region });
    api.get<Organization[]>(`/api/v1/orgs?${params}`)
      .then((items) => {
        if (requestId === clinicsRequestId.current) setClinics(items);
      })
      .catch(() => {
        if (requestId === clinicsRequestId.current) setClinicsError(true);
      })
      .finally(() => {
        if (requestId === clinicsRequestId.current) setClinicsLoading(false);
      });
  }, [region, clinicRetry]);

  const toggleDiary = (key: HealthType, on: boolean) =>
    setDiaries((prev) => prev.map((d) => (d.key === key ? { ...d, on } : d)));

  const validateSelection = () => {
    const selectedRegion = availableRegions.find((item) => item.title === region);
    const validRegion = Boolean(selectedRegion);
    const validCity = !selectedRegion?.cities?.length || selectedRegion.cities.some((item) => item.title === city);
    const validClinic = attachedClinicId === null || clinics?.some((item) => item.id === attachedClinicId) === true;
    if (regionsLoading || regionsError || !validRegion) {
      setFormError("Выберите регион из списка");
      return false;
    }
    if (!validCity) {
      setFormError("Выберите город из списка");
      return false;
    }
    if (!validClinic) {
      setFormError("Выбранная поликлиника больше недоступна. Выберите другую или продолжите без неё.");
      return false;
    }
    setFormError(null);
    return true;
  };

  const continueToDiaries = () => {
    if (validateSelection()) setStep(3);
  };

  const finish = async () => {
    if (submitting.current) return;
    if (!validateSelection()) {
      setStep(2);
      return;
    }
    submitting.current = true;
    setBusy(true);
    try {
      const enabled = diaries.filter((d) => d.on).map((d) => d.key);
      // push_time не передаём (null): онбординг не должен сбрасывать настроенное время пуша
      const payload: HealthSetting[] = DIARY_META.map((d) => ({ diary: d.key, enabled: enabled.includes(d.key), push_time: null }));
      const consent: ConsentPayload = { city: city || null, region, attached_clinic_id: attachedClinicId, diaries: payload };
      const saved = await api.post<UserDto>("/api/v1/me/consent", consent);
      updateUser(saved);
    } catch {
      setFormError("Не удалось сохранить настройки. Проверьте соединение и попробуйте ещё раз.");
      submitting.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="app white">
      {step === 0 && (
        <>
          <div className="screen-body ob">
            <img className="logo-mid" src="/medroute-logo.svg" alt="Логотип МедМаршрут" />
            <div className="greeting">
              <h2>Здравствуйте!</h2>
              <p>Я — МедМаршрут. Помогу пройти медицинский путь спокойно и по порядку.</p>
            </div>
            <div className="card ob-item">
              <div className="ic b"><I.route size={20} /></div>
              <div>
                <b>Маршрут из ситуации</b>
                <span>Выбираете жизненную ситуацию — получаете пошаговый план: что сделать, что спросить у врача, что взять с собой.</span>
              </div>
            </div>
            <div className="card ob-item">
              <div className="ic r"><I.bell size={20} /></div>
              <div>
                <b>Напоминания от бота</b>
                <span>К визитам, анализам и таблеткам — придут в чат MAX, ничего терять не нужно.</span>
              </div>
            </div>
            <div className="card ob-item">
              <div className="ic g"><I.pulse size={20} /></div>
              <div>
                <b>Дневники здоровья</b>
                <span>Давление, вес, самочувствие — только те, что нужны именно вам. Сводку можно показать врачу.</span>
              </div>
            </div>
          </div>
          <div className="steps"><i className="on" /><i /><i /><i /></div>
          <div className="foot"><Button onClick={() => setStep(1)}>Дальше</Button></div>
        </>
      )}

      {step === 1 && (
        <>
          <div className="header">
            <div className="hdr-title" style={{ paddingLeft: 16 }}><h1>Ваши данные</h1></div>
          </div>
          <div className="screen-body ob">
            <aside className="card tinted" role="note" aria-label="Данные для демонстрации">
              <p><strong>Не вводите реальные ФИО, документы и диагнозы — данные модельные.</strong></p>
            </aside>
            <div className="card" style={{ padding: "8px 16px" }}>
              <div style={{ padding: "10px 0" }}>
                <b style={{ fontSize: 15 }}>Что мы обрабатываем</b>
              </div>
              <div className="rem-item"><div className="what"><b>Профиль из MAX</b><small>Имя и аватар приходят подписанными из приложения — пароли мы не видим</small></div></div>
              <div className="rem-item"><div className="what"><b>Шаги маршрута и заметки</b><small>Ситуации, назначения врача, ваши пункты</small></div></div>
              <div className="rem-item"><div className="what"><b>Записи дневников здоровья</b><small>То, что введёте вы сами: давление, вес и другое</small></div></div>
              <div className="rem-item"><div className="what"><b>Где хранится</b><small>На нашем сервере по защищённому соединению; доступ — только из вашего приложения</small></div></div>
              <div className="rem-item"><div className="what"><b>Чистый старт</b><small>Аккаунт начинается с нуля — маршрут и дневники вы заведёте сами, ничего чужого не появится</small></div></div>
            </div>
            <label className="consent">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span className="box"><I.check size={14} strokeWidth={3} /></span>
              <span>
                <b>Я согласен на обработку моих данных</b>
                <small>Без согласия приложение работать не будет — честно и без мелкого шрифта</small>
              </span>
            </label>
            <div className="muted" style={{ fontSize: 12.5, textAlign: "center" }}>
              Подробнее — в разделе «О приложении» вашего профиля
            </div>
          </div>
          <div className="steps"><i /><i className="on" /><i /><i /></div>
          <div className="foot">
            <Button disabled={!agreed} onClick={() => setStep(2)}>Продолжить</Button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <div className="header">
            <div className="hdr-title" style={{ paddingLeft: 16 }}><h1>Ваш регион и прикрепленная поликлиника</h1></div>
          </div>
          <div className="screen-body ob">
            <div className="greeting">
              <h2 style={{ fontSize: 21 }}>Выберите город</h2>
              <p>Сейчас доступны областные центры пилотных регионов. По городу мы автоматически настроим время уведомлений.</p>
            </div>
            {regionsError && <div className="card" role="alert">Не удалось загрузить регионы. <button type="button" className="cell-h-btn" onClick={loadRegions}>Повторить</button></div>}
            {!regionsError && <select className="tz-select" value={region} disabled={regionsLoading} onChange={(e) => { setRegion(e.target.value); setCity(""); setFormError(null); }} aria-label="Регион">
              <option value="">{regionsLoading ? "Загрузка регионов…" : "Выберите регион"}</option>
              {availableRegions.map((item) => <option key={item.key} value={item.title}>{item.title}</option>)}
            </select>}
            {region && (() => {
              const selectedRegion = availableRegions.find((item) => item.title === region);
              const cityOptions = selectedRegion?.cities ?? [];
              return cityOptions.length > 0 ? <select className="tz-select" value={city} disabled={regionsLoading} onChange={(e) => { setCity(e.target.value); setFormError(null); }} aria-label="Город">
                <option value="">Выберите город</option>
                {cityOptions.map((item) => <option key={item.key} value={item.title}>{item.title}</option>)}
              </select> : null;
            })()}
            {region && clinicsError && <div className="card" role="alert">Не удалось загрузить поликлиники. <button type="button" className="cell-h-btn" onClick={() => setClinicRetry((value) => value + 1)}>Повторить</button></div>}
            {region && !clinicsError && clinicsLoading && <div className="muted">Загружаем поликлиники…</div>}
            {region && !clinicsLoading && !clinicsError && clinics && clinics.length === 0 && <div className="card" role="status">В выбранном регионе пока нет поликлиник.</div>}
            {clinics && clinics.length > 0 && (() => {
              const normalizedQuery = clinicQuery.trim().toLocaleLowerCase();
              const visibleClinics = normalizedQuery
                ? clinics.filter((clinic) => clinic.id === attachedClinicId || `${clinic.title} ${clinic.address}`.toLocaleLowerCase().includes(normalizedQuery))
                : clinics;
              return <>
                <Input
                  value={clinicQuery}
                  onChange={(e) => setClinicQuery(e.target.value)}
                  placeholder="Поиск по названию или адресу"
                  aria-label="Поиск поликлиники"
                />
                <select className="tz-select" value={attachedClinicId ?? ""} onChange={(e) => { setAttachedClinicId(e.target.value ? Number(e.target.value) : null); setFormError(null); }} aria-label="Поликлиника">
                  <option value="">Поликлиника не выбрана</option>
                  {visibleClinics.map((clinic) => <option key={clinic.id} value={clinic.id}>{clinic.title} — {clinic.address}</option>)}
                </select>
                {visibleClinics.length > 0
                  ? <OrganizationMap organizations={visibleClinics} selectedId={attachedClinicId} onSelect={(id) => { setAttachedClinicId(id); setFormError(null); }} />
                  : <div className="card" role="status">По вашему запросу поликлиники не найдены.</div>}
              </>;
            })()}
            {region && <div className="card tinted" role="note">
              <b>Моей поликлиники нет в списке?</b>
              <div className="muted" style={{ marginTop: 4 }}>Продолжите без выбора и добавьте её позже в профиле.</div>
            </div>}
            <div className="muted" style={{ fontSize: 12.5 }}>
              Мы сохраним выбранную поликлинику в профиле. Это не оформляет официальное прикрепление.
            </div>
            {formError && <div className="card" role="alert" style={{ color: "var(--red)" }}>{formError}</div>}
          </div>
          <div className="steps"><i /><i /><i className="on" /><i /></div>
          <div className="foot">
            {attachedClinicId === null && <Button type="button" variant="secondary" disabled={regionsLoading} onClick={continueToDiaries}>Выбрать поликлинику позже</Button>}
            {attachedClinicId !== null && <Button type="button" disabled={regionsLoading || clinicsLoading} onClick={continueToDiaries}>Продолжить</Button>}
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <div className="header">
            <div className="hdr-title" style={{ paddingLeft: 16 }}><h1>Дневники под себя</h1></div>
          </div>
          <div className="screen-body ob">
            <div className="greeting">
              <h2 style={{ fontSize: 21 }}>Что будем отслеживать?</h2>
              <p>Включите то, что нужно именно вам — под ваши приборы и назначения врача. Потом можно изменить в разделе «Здоровье».</p>
            </div>
            <div className="card" style={{ padding: "8px 16px" }}>
              {diaries.map((d) => (
                <div className="rem-item" key={d.key}>
                  <div className="what"><b>{d.title}</b><small>{d.hint}</small></div>
                  <Switch on={d.on} onChange={(v) => toggleDiary(d.key, v)} label={d.title} />
                </div>
              ))}
            </div>
            {formError && <div className="card" role="alert" style={{ color: "var(--red)" }}>{formError}</div>}
          </div>
          <div className="steps"><i /><i /><i /><i className="on" /></div>
          <div className="foot"><Button disabled={busy} onClick={finish}>{busy ? "Настраиваем…" : "Начать"}</Button></div>
        </>
      )}
    </div>
  );
}
