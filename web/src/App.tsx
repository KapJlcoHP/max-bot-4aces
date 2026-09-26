import { createContext, useContext, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { isInsideMax, startParamPath } from "./bridge";
import type { UserDto } from "./types";
import { ErrorView, StateView, TabBar } from "./components/ui";
import { I } from "./icons";

interface AppCtx {
  user: UserDto;
  refreshUser: () => void;
  updateUser: (user: UserDto) => void;
}
const Ctx = createContext<AppCtx | null>(null);
export const useApp = () => useContext(Ctx)!;

const TAB_PATHS = ["/", "/route", "/profile"];

export default function App() {
  const [user, setUser] = useState<UserDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "auth-error" | "error">("loading");
  const [splash, setSplash] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const load = () => {
    setStatus("loading");
    api
      .get<UserDto>("/api/v1/me")
      .then((u) => {
        setUser(u);
        setStatus("ready");
      })
      .catch((e) => setStatus(e?.status === 401 ? "auth-error" : "error"));
  };

  useEffect(load, []);

  // Белый сплэш с логотипом — короткая пауза, чтобы вход был не «рывком»
  useEffect(() => {
    const t = setTimeout(() => setSplash(false), 1200);
    return () => clearTimeout(t);
  }, []);

  // Диплинк ?startapp=<payload>: имена экранов (route|meds|health|…) и шаги step_<id>
  useEffect(() => {
    const path = startParamPath();
    if (path) navigate(path, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (splash || status === "loading") {
    return (
      <div className="app white splash-screen">
        <img className="logo-mid" src="/medroute-logo.svg" alt="Логотип МедМаршрут" />
        <h1>МедМаршрут</h1>
        <p>Ваш помощник в медицинских маршрутах</p>
        <div className="dots"><i /><i /><i /></div>
      </div>
    );
  }

  if (status === "auth-error") {
    return (
      <div className="app white">
        <StateView
          icon={<I.user size={64} />}
          title="Откройте приложение через бота"
          text={
            isInsideMax()
              ? "Не удалось подтвердить вход. Вернитесь в чат с ботом и откройте приложение заново."
              : "Мини-ап работает внутри MAX. Найдите бота @t24_hakaton_max_bot и нажмите кнопку приложения."
          }
        />
      </div>
    );
  }

  if (status === "error" || !user) {
    return (
      <div className="app white">
        <ErrorView onRetry={load} />
      </div>
    );
  }

  // Согласие на обработку данных (152-ФЗ) — блокирующий онбординг
  if (!user.consent_at) {
    const Onboarding = require_onboarding();
    return (
      <Ctx.Provider value={{ user, refreshUser: load, updateUser: setUser }}>
        <Onboarding />
      </Ctx.Provider>
    );
  }

  const showNav = TAB_PATHS.includes(location.pathname);

  return (
    <Ctx.Provider value={{ user, refreshUser: load, updateUser: setUser }}>
      <div className="app">
        {!isInsideMax() && (
          <div className="demo-banner">Демо-режим (вне MAX): данные синтетические, вход по dev-доступу</div>
        )}
        <Outlet />
        {showNav && <TabBar />}
      </div>
    </Ctx.Provider>
  );
}

// Отдельный импорт, чтобы гейт согласия не тянул страницы в критический путь
import Onboarding from "./pages/Onboarding";
function require_onboarding() {
  return Onboarding;
}
