import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { I, Logo } from "../icons";

export function Badge({ color, children }: { color: "blue" | "yellow" | "green" | "gray"; children: ReactNode }) {
  return <span className={`badge badge-${color}`}>{children}</span>;
}

export function Toggle({ on, onChange }: { on: boolean; onChange?: () => void }) {
  return (
    <button type="button" className={`toggle${on ? " on" : ""}`} onClick={(e) => { e.stopPropagation(); onChange?.(); }}>
      <i />
    </button>
  );
}

export function Header({ title, subtitle, back, right }: { title: string; subtitle?: string; back?: string; right?: ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="header">
      <div className="h-row">
        {back && (
          <button className="back-btn" onClick={() => navigate(back)} aria-label="Назад">
            <I.back />
          </button>
        )}
        <div className="h-title">
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {right}
      </div>
    </div>
  );
}

export function HomeHeader({ firstName, onBell }: { firstName: string; onBell: () => void }) {
  return (
    <div className="header">
      <div className="h-row">
        <div className="brand">
          <div className="logo"><Logo /></div>
          <h1>МедМаршрут</h1>
        </div>
        <button className="icon-btn" onClick={onBell} aria-label="Уведомления">
          <I.bell size={22} />
        </button>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, marginTop: 10 }}>
        Здравствуйте, {firstName}
      </div>
    </div>
  );
}

const TABS = [
  { to: "/", label: "Дашборд", icon: I.home },
  { to: "/checklist", label: "Чек-лист", icon: I.list },
  { to: "/orgs", label: "Организации", icon: I.building },
  { to: "/reminders", label: "Напоминания", icon: I.bell },
  { to: "/profile", label: "Профиль", icon: I.person },
];

export function BottomNav() {
  const navigate = useNavigate();
  const { pathname } = { pathname: window.location.pathname };
  return (
    <nav className="tabbar">
      {TABS.map((t) => {
        const active = t.to === "/" ? pathname === "/" : pathname.startsWith(t.to);
        const Icon = t.icon;
        return (
          <button key={t.to} className={`tab${active ? " active" : ""}`} onClick={() => navigate(t.to)}>
            <Icon size={23} />
            <span>{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

export function StateView({ icon, title, text, button, onButton }: {
  icon: ReactNode; title: string; text: string; button?: string; onButton?: () => void;
}) {
  return (
    <div className="state-wrap">
      {icon}
      <h2>{title}</h2>
      <p>{text}</p>
      {button && <button className="btn btn-primary" onClick={onButton}>{button}</button>}
    </div>
  );
}

export function ErrorView({ onRetry }: { onRetry: () => void }) {
  return (
    <StateView
      icon={<div className="alert-circle"><I.alert size={30} /></div>}
      title="Не удалось загрузить данные"
      text="Проверьте подключение и попробуйте ещё раз"
      button="Повторить"
      onButton={onRetry}
    />
  );
}

export function Toast({ text }: { text: string | null }) {
  if (!text) return null;
  return <div className="toast">{text}</div>;
}

/** Одноразовый тост: const [toastNode, showToast] = useToast() */
export function useToast(): [ReactNode, (msg: string) => void] {
  const [text, setText] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const show = (msg: string) => {
    setText(msg);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(null), 2400);
  };
  return [<Toast key="toast" text={text} />, show];
}

export function Avatar({ text, color = "blue", size = 44, fontSize = 15 }: { text: string; color?: string; size?: number; fontSize?: number }) {
  return (
    <div className={`avatar ${color}`} style={{ width: size, height: size, fontSize }}>
      {text}
    </div>
  );
}
