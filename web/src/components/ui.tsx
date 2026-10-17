import { Children, cloneElement, isValidElement, useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { ReactElement, ReactNode } from "react";
import { Spinner, Switch as MaxSwitch } from "@maxhub/max-ui";import { I, Logo } from "../icons";
import { initials } from "../format";

export function Badge({ color = "blue", children }: { color?: "blue" | "green" | "red" | "gray"; children: ReactNode }) {
  return <span className={`badge badge-${color}`}>{children}</span>;
}

export function BrandMark() {
  return <div className="brand"><Logo size={30} /><strong>МедМаршрут</strong></div>;
}

export function Button({
  className = "", variant = "primary", children, ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
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
export function RootHeader({ name, url, onProfile }: { name: string; url?: string | null; onProfile: () => void }) {
  return (
    <div className="header">
      <div className="h-row">
        <BrandMark />
        <UserAvatar name={name} url={url} size={36} onClick={onProfile} />
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
  const sheetRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const titleId = `sheet-title-${useId().replace(/:/g, "")}`;
  const labelledChildren = Children.toArray(children);
  const headingIndex = labelledChildren.findIndex(
    (child) => isValidElement(child) && typeof child.type === "string" && /^h[1-6]$/.test(child.type),
  );
  const heading = headingIndex >= 0 ? labelledChildren[headingIndex] as ReactElement<{ id?: string }> : null;
  const labelledBy = heading?.props.id || titleId;

  if (heading) {
    labelledChildren[headingIndex] = cloneElement(heading, { id: labelledBy });
  } else {
    labelledChildren.unshift(<h2 key={titleId} id={titleId} className="sr-only">Диалог</h2>);
  }

  const restoreFocus = () => {
    const element = previouslyFocusedRef.current;
    previouslyFocusedRef.current = null;
    if (element?.isConnected) element.focus();
  };

  useEffect(() => {
    if (!open) {
      restoreFocus();
      return;
    }

    if (!previouslyFocusedRef.current && document.activeElement instanceof HTMLElement) {
      previouslyFocusedRef.current = document.activeElement;
    }

    const sheet = sheetRef.current;
    const firstFocusable = sheet?.querySelector<HTMLElement>(
      'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
    );
    (firstFocusable || sheet)?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(sheet?.querySelectorAll<HTMLElement>(
        'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
      ) ?? []);
      if (focusable.length === 0) {
        event.preventDefault();
        sheet?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  useEffect(() => {
    return () => restoreFocus();
  }, []);

  if (!open) return null;
  return (
    <>
      <div className="sheet-backdrop open" aria-hidden="true" onClick={onClose} />
      <div
        ref={sheetRef}
        className="sheet open"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
      >
        <div className="grab" />
        {labelledChildren}
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
  return <div className="toast" role="status" aria-live="polite" aria-atomic="true">{text}</div>;
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

/** Аватар пользователя: фото из MAX (если платформа его отдала), иначе инициалы на фирменном фоне. */
export function UserAvatar({
  name, url, size = 36, color = "red", onClick,
}: { name: string; url?: string | null; size?: number; color?: "blue" | "red"; onClick?: () => void }) {
  const box = { width: size, height: size, cursor: onClick ? ("pointer" as const) : undefined };
  if (url) {
    return <img className="uavatar" src={url} alt={name || "Аватар"} style={box} onClick={onClick} />;
  }
  return (
    <span
      className="uavatar"
      style={{
        ...box,
        background: color === "red" ? "var(--red-tint)" : "var(--blue-tint)",
        color: color === "red" ? "var(--red)" : "var(--blue)",
        fontSize: Math.round(size / 2.7),
      }}
      onClick={onClick}
    >
      {initials(name.trim() || "Я")}
    </span>
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
