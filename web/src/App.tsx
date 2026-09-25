import { createContext, useContext, useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { isInsideMax, startParam } from "./bridge";
import type { UserDto } from "./types";
import { BottomNav, DesktopNav, ErrorView, StateView } from "./components/ui";
import { I, Logo } from "./icons";

interface AppCtx {
  user: UserDto;
  refreshUser: () => void;
}
const Ctx = createContext<AppCtx | null>(null);
export const useApp = () => useContext(Ctx)!;

const TAB_PATHS = ["/", "/checklist", "/orgs", "/reminders", "/profile"];
const DEEP_LINK_PATHS = new Set(["route", "catalog", "checklist", "orgs", "reminders", "profile", "prep", "health", "family"]);

export default function App() {
  const [user, setUser] = useState<UserDto | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "auth-error" | "error">("loading");
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

  // Диплинк ?startapp=route|checklist|... → сразу открываем нужный экран
  useEffect(() => {
    const p = startParam();
    if (p && DEEP_LINK_PATHS.has(p)) navigate(`/${p}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "loading") {
    return (
      <div className="app splash-screen">
        <div className="splash-center"><Logo size={144} /><h1>МедМаршрут</h1><p>Ваш помощник в медицинских маршрутах</p></div>
        <div className="splash-bottom"><div className="splash-dots"><i /><i /><i /></div><span>Загрузка…</span></div>
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

  const showNav = TAB_PATHS.includes(location.pathname);

  return (
    <Ctx.Provider value={{ user, refreshUser: load }}>
      <div className="app-layout">
        <DesktopNav name={`${user.first_name} ${user.last_name}`.trim()} />
        <div className="app">
          {!isInsideMax() && (
            <div className="demo-banner">
              Демо-режим (вне MAX): данные синтетические, вход по dev-доступу
            </div>
          )}
          <Outlet />
          {showNav && <BottomNav />}
        </div>
      </div>
    </Ctx.Provider>
  );
}
