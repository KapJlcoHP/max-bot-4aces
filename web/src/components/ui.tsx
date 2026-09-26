import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { Avatar as MaxAvatar, Spinner, Switch as MaxSwitch } from "@maxhub/max-ui";
import { I, Logo } from "../icons";
import { initials } from "../format";

export function Badge({ color = "blue", children }: { color?: "blue" | "green" | "red" | "gray"; children: ReactNode }) {
  return <span className={`badge badge-${color}`}>{children}</span>;
}

export function BrandMark() {
  return <div className="brand"><Logo size={30} /><strong>МедМаршрут</strong></div>;
}

export function Button({
  className = "", variant = "primary", children, ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  return (
    <button className={`btn ${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}

/** Переключатель из MAX-UI. Обёртка гасит клик, чтобы не срабатывала строка-родитель. */
export function Switch({ on, onChange, label }: { on: boolean; onChange?: (v: boolean) => void; label?: string }) {
  return (
    <span className="switch-wrap" onClick={(e) => e.stopPropagation()}>
      <MaxSwitch
        checked={on}
        aria-label={label ?? "Переключить"}
        onChange={(e) => onChange?.(e.target.checked)}
      />
    </span>
  );
}

export function Header({ title, subtitle, back, right }: { title: string; subtitle?: string; back?: string; right?: ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="header">
      <div className="h-row">
        {back && (
          <button className="hdr-back" onClick={() => navigate(back)} aria-label="Назад">
            <I.back size={22} />
          </button>
        )}
        <div className="hdr-title">
          <h1>{title}</h1>
          {subtitle && <small>{subtitle}</small>}
        </div>
        {right}
      </div>
    </div>
  );
}

/** Шапка корневых экранов: бренд слева, аватар-профиль справа. */
export function RootHeader({ name, onProfile }: { name: string; onProfile: () => void }) {
  return (
    <div className="header">
      <div className="h-row">
        <BrandMark />
        <MaxAvatar.Container
          size={36}
          onClick={onProfile}
          style={{ cursor: "pointer", flex: "0 0 auto", width: 36, height: 36, background: "var(--red-tint)" }}
          aria-label="Профиль"
        >
          <MaxAvatar.Text style={{ background: "none", color: "var(--red)", fontWeight: 700, fontSize: 13 }}>
            {initials(name.trim() || "Я")}
          </MaxAvatar.Text>
        </MaxAvatar.Container>
      </div>
    </div>
  );
}

const TABS = [
  { to: "/", label: "Главная", icon: I.home },
  { to: "/route", label: "Маршрут", icon: I.route },
  { to: "/profile", label: "Профиль", icon: I.person },
];

/** Нижняя панель: ровно 3 вкладки на корневых экранах. */
export function TabBar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <nav className="tabbar">
      {TABS.map((t) => {
        const active = t.to === "/" ? pathname === "/" : pathname.startsWith(t.to);
        const Icon = t.icon;
        return (
          <button key={t.to} className={`tab${active ? " active" : ""}`} onClick={() => navigate(t.to)} aria-label={t.label}>
            <Icon size={22} />
            <span>{t.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

/** Нижний лист (bottom sheet) с затемнением. */
export function Sheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  if (!open) return null;
  return (
    <>
      <div className="sheet-backdrop open" onClick={onClose} />
      <div className="sheet open">
        <div className="grab" />
        {children}
      </div>
    </>
  );
}

export function StateView({ icon, title, text, button, onButton }: {
  icon?: ReactNode; title: string; text: string; button?: string; onButton?: () => void;
}) {
  return (
    <div className="state-wrap">
      {icon}
      <h2>{title}</h2>
      <p>{text}</p>
      {button && <Button onClick={onButton}>{button}</Button>}
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

export function Avatar({ text, size = 38, color = "blue" }: { text: string; size?: number; color?: "blue" | "red" }) {
  return (
    <MaxAvatar.Container
      size={size}
      style={{
        flex: "0 0 auto",
        width: size,
        height: size,
        background: color === "red" ? "var(--red-tint)" : "var(--blue-tint)",
      }}
      aria-label="Профиль"
    >
      <MaxAvatar.Text style={{ background: "none", color: color === "red" ? "var(--red)" : "var(--blue)", fontWeight: 700, fontSize: size / 2.7 }}>
        {text}
      </MaxAvatar.Text>
    </MaxAvatar.Container>
  );
}

/** Состояние загрузки на спиннере MAX-UI. */
export function LoadingView() {
  return (
    <div className="loading-wrap">
      <Spinner size={28} />
    </div>
  );
}
