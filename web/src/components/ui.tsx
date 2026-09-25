import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { Avatar as MaxAvatar, Button as MaxButton, IconButton, Switch } from "@maxhub/max-ui";
import type { ButtonProps } from "@maxhub/max-ui";
import { I, Logo } from "../icons";
import { initials } from "../format";

export function Badge({ color, children }: { color: "blue" | "yellow" | "green" | "gray"; children: ReactNode }) {
  return <span className={`badge badge-${color}`}>{children}</span>;
}

export function BrandMark() {
  return <div className="brand-mark"><Logo size={26} /><strong>МедМаршрут</strong></div>;
}

export function Button({ className = "", variant, children, ...props }: ButtonProps) {
  const resolvedVariant = variant ?? (className.includes("secondary") ? "secondary" : "primary");
  return <MaxButton size="large" stretched variant={resolvedVariant} className={className} {...props}>
    <span className="btn-content">{children}</span>
  </MaxButton>;
}

export function Toggle({ on, onChange }: { on: boolean; onChange?: () => void }) {
  return (
    <Switch type="checkbox" checked={on} aria-label="Переключить" onClick={(e) => e.stopPropagation()} onChange={onChange} />
  );
}

export function Header({ title, subtitle, back, right }: { title: string; subtitle?: string; back?: string; right?: ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="header">
      <div className="h-row">
        {back && (
          <IconButton className="back-btn" variant="ghost" onClick={() => navigate(back)} aria-label="Назад">
            <I.back />
          </IconButton>
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

export function HomeHeader({ onBell }: { onBell: () => void }) {
  return (
    <div className="header">
      <div className="h-row">
        <div className="brand">
          <div className="logo"><Logo /></div>
          <h1>МедМаршрут</h1>
        </div>
        <IconButton className="icon-btn" variant="secondary" onClick={onBell} aria-label="Уведомления">
          <I.bell size={22} />
        </IconButton>
      </div>
    </div>
  );
}

const TABS = [
  { to: "/", label: "Дашборд", shortLabel: "Дашборд", icon: I.home },
  { to: "/checklist", label: "Чек-лист", shortLabel: "Чек-лист", icon: I.list },
  { to: "/orgs", label: "Организации", shortLabel: "Организ.", icon: I.building },
  { to: "/reminders", label: "Напоминания", shortLabel: "Напомин.", icon: I.bell },
  { to: "/profile", label: "Профиль", shortLabel: "Профиль", icon: I.person },
];

export function BottomNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <nav className="tabbar">
      {TABS.map((t) => {
        const active = t.to === "/" ? pathname === "/" : pathname.startsWith(t.to);
        const Icon = t.icon;
        return (
          <button key={t.to} className={`tab${active ? " active" : ""}`} onClick={() => navigate(t.to)} aria-label={t.label}>
            <Icon size={23} />
            <span className="tab-label">{t.label}</span>
            <span className="tab-short-label" aria-hidden="true">{t.shortLabel}</span>
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
      {button && <Button className="btn btn-primary" onClick={onButton}>{button}</Button>}
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
    <MaxAvatar.Container size={size} form="circle" className={`avatar ${color}`}>
      <MaxAvatar.Text className="avatar-text" style={{ fontSize }}>{text}</MaxAvatar.Text>
    </MaxAvatar.Container>
  );
}

export function TabHeader({ action, actionLabel, onAction }: { action?: ReactNode; actionLabel?: string; onAction?: () => void }) {
  return (
    <div className="header tab-header">
      <div className="h-row">
        <div className="brand"><div className="logo"><Logo /></div><h1>МедМаршрут</h1></div>
        {onAction ? <IconButton className="icon-btn blue" variant="secondary" onClick={onAction} aria-label={actionLabel ?? "Действие"}>{action}</IconButton> : action}
      </div>
    </div>
  );
}

export function DesktopNav({ name }: { name: string }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <aside className="desktop-nav" aria-label="Основная навигация">
      <div className="brand desktop-brand"><div className="logo"><Logo /></div><h1>МедМаршрут</h1></div>
      <nav>
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = t.to === "/" ? pathname === "/" : pathname.startsWith(t.to);
          return <button key={t.to} className={`desktop-tab${active ? " active" : ""}`} onClick={() => navigate(t.to)}><Icon size={22} /><span>{t.label}</span></button>;
        })}
      </nav>
      <div className="desktop-account"><Avatar text={initials(name)} size={40} /><span><strong>{name}</strong><small>Пациент</small></span></div>
    </aside>
  );
}
