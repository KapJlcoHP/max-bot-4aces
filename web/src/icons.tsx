/** Инлайн-SVG-иконки (stroke = currentColor, как в макете). */

import type { ReactElement, ReactNode } from "react";

type P = { size?: number; strokeWidth?: number };

const S = ({ size = 24, strokeWidth = 1.8, children }: P & { children: ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);

export const I = {
  back: (p: P = {}) => <S {...p}><path d="M15 5l-7 7 7 7" /></S>,
  chev: (p: P = {}) => <S {...p}><path d="M9 5l7 7-7 7" /></S>,
  bell: (p: P = {}) => <S {...p}><path d="M18 8a6 6 0 10-12 0c0 7-3 8-3 8h18s-3-1-3-8" /><path d="M13.7 21a2 2 0 01-3.4 0" /></S>,
  search: (p: P = {}) => <S {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></S>,
  plus: (p: P = {}) => <S {...p}><path d="M12 5v14M5 12h14" /></S>,
  phone: (p: P = {}) => <S {...p}><path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1 1 .4 2 .7 2.9a2 2 0 01-.5 2.1L8 10a16 16 0 006 6l1.3-1.3a2 2 0 012.1-.5c.9.3 1.9.6 2.9.7a2 2 0 011.7 2z" /></S>,
  pin: (p: P = {}) => <S {...p}><path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 1118 0z" /><circle cx="12" cy="10" r="3" /></S>,
  clock: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></S>,
  cal: (p: P = {}) => <S {...p}><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M8 3v4M16 3v4M3 10h18" /></S>,
  calCheck: (p: P = {}) => <S {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18" /><path d="M9 15l2 2 4-4" /></S>,
  check: (p: P = {}) => <S {...p}><path d="M5 13l4 4 10-10" /></S>,
  alert: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></S>,
  route: (p: P = {}) => <S {...p}><path d="M4 6h16M4 12h10M4 18h7" /><circle cx="19" cy="16" r="3" /></S>,
  user: (p: P = {}) => <S {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></S>,
  users: (p: P = {}) => <S {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0113 0" /><path d="M16 4.6a3.5 3.5 0 010 6.8" /><path d="M17.5 14.4a6.5 6.5 0 014 5.6" /></S>,
  clipboard: (p: P = {}) => <S {...p}><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2" /><rect x="9" y="3" width="6" height="4" rx="1" /><path d="M9 12l2 2 4-4" /></S>,
  pulse: (p: P = {}) => <S {...p}><path d="M3 12h4l2-6 4 12 2-6h6" /></S>,
  doc: (p: P = {}) => <S {...p}><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></S>,
  building: (p: P = {}) => <S {...p}><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01" /></S>,
  home: (p: P = {}) => <S {...p}><path d="M3 10.5L12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></S>,
  list: (p: P = {}) => <S {...p}><path d="M4 6h16M4 12h10M4 18h7" /><circle cx="19" cy="16" r="3" /></S>,
  person: (p: P = {}) => <S {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></S>,
  pill: (p: P = {}) => <S {...p}><rect x="3.4" y="8.8" width="17.2" height="6.4" rx="3.2" transform="rotate(-45 12 12)" /><path d="M8.6 15.4l6.8-6.8" /></S>,
  shield: (p: P = {}) => <S {...p}><path d="M12 2l7 4v6c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z" /></S>,
  smile: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M8.5 14.5c.9 1.2 2.1 1.8 3.5 1.8s2.6-.6 3.5-1.8" /><path d="M9 9.5h.01M15 9.5h.01" /></S>,
  scale: (p: P = {}) => <S {...p}><path d="M12 3v8" /><path d="M6 21h12a2 2 0 002-2l-1.5-9a2 2 0 00-2-1.6h-11A2 2 0 003.5 10L2 19a2 2 0 002 2z" /></S>,
  globe: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18 14 14 0 010-18z" /></S>,
  info: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M12 11v5" /></S>,
  share: (p: P = {}) => <S {...p}><path d="M4 12v7a1 1 0 001 1h14a1 1 0 001-1v-7" /><path d="M16 6l-4-4-4 4M12 2v13" /></S>,
  trash: (p: P = {}) => <S {...p}><path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" /></S>,
};

export function Logo({ size = 38 }: { size?: number }) {
  return <img src="/medroute-logo.svg" width={size} height={size} alt="Логотип МедМаршрут" style={{ display: "block" }} />;
}

export function SituationIcon({ name, size = 24 }: { name: string; size?: number }) {
  const icon = (I as Record<string, (p: P) => ReactElement>)[name] ?? I.doc;
  return icon({ size });
}
