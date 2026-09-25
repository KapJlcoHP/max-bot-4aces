/** Инлайн-SVG-иконки (stroke = currentColor, как в макете). */

import type { ReactElement, ReactNode } from "react";

type P = { size?: number };

const S = ({ size = 24, children }: P & { children: ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);

export const I = {
  back: (p: P = {}) => <S {...p}><path d="M15 18l-6-6 6-6" /></S>,
  chev: (p: P = {}) => <S {...p}><path d="M9 6l6 6-6 6" /></S>,
  bell: (p: P = {}) => <S {...p}><path d="M18 8a6 6 0 10-12 0c0 7-3 8-3 8h18s-3-1-3-8" /><path d="M13.7 21a2 2 0 01-3.4 0" /></S>,
  search: (p: P = {}) => <S {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></S>,
  plus: (p: P = {}) => <S {...p}><path d="M12 5v14M5 12h14" /></S>,
  phone: (p: P = {}) => <S {...p}><path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1 1 .4 2 .7 2.9a2 2 0 01-.5 2.1L8 10a16 16 0 006 6l1.3-1.3a2 2 0 012.1-.5c.9.3 1.9.6 2.9.7a2 2 0 011.7 2z" /></S>,
  pin: (p: P = {}) => <S {...p}><path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 1118 0z" /><circle cx="12" cy="10" r="3" /></S>,
  clock: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></S>,
  cal: (p: P = {}) => <S {...p}><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M8 2v4M16 2v4M3 9h18" /></S>,
  calCheck: (p: P = {}) => <S {...p}><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M8 2v4M16 2v4M3 9h18" /><path d="M9 15l2 2 4-4" /></S>,
  check: (p: P = {}) => <S {...p}><path d="M20 6L9 17l-5-5" /></S>,
  download: (p: P = {}) => <S {...p}><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></S>,
  alert: (p: P = {}) => <S {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" /></S>,
  route: (p: P = {}) => <S {...p}><circle cx="6" cy="19" r="2.4" /><circle cx="18" cy="5" r="2.4" /><path d="M8.4 19H15a3.5 3.5 0 000-7H9a3.5 3.5 0 010-7h6.6" /></S>,
  user: (p: P = {}) => <S {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></S>,
  users: (p: P = {}) => <S {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0113 0" /><path d="M16 4.6a3.5 3.5 0 010 6.8" /><path d="M17.5 14.4a6.5 6.5 0 014 5.6" /></S>,
  clipboard: (p: P = {}) => <S {...p}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 3h6v3H9z" /><path d="M9 11h6M9 15h4" /></S>,
  heart: (p: P = {}) => <S {...p}><path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.6l-1-1a5.5 5.5 0 10-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 000-7.8z" /></S>,
  pulse: (p: P = {}) => <S {...p}><path d="M3 12h4l2-7 4 14 2-7h6" /></S>,
  file: (p: P = {}) => <S {...p}><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h6" /></S>,
  doc: (p: P = {}) => <S {...p}><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></S>,
  building: (p: P = {}) => <S {...p}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01" /><path d="M10 21v-3h4v3" /></S>,
  home: (p: P = {}) => <S {...p}><path d="M3 11l9-8 9 8" /><path d="M5 9.8V20a1 1 0 001 1h12a1 1 0 001-1V9.8" /></S>,
  list: (p: P = {}) => <S {...p}><path d="M9 6h12M9 12h12M9 18h12" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></S>,
  person: (p: P = {}) => <S {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></S>,
};

export function Logo({ size = 38 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size}>
      <path d="M11 42 C11 27 24 17 39 21" stroke="#2563EB" strokeWidth="7" fill="none" strokeLinecap="round" />
      <path d="M34 10 L52 19 L37 31 Z" fill="#2563EB" />
      <rect x="25" y="22" width="13" height="34" rx="5.5" fill="#E53935" />
      <rect x="14.5" y="32.5" width="34" height="13" rx="5.5" fill="#E53935" />
    </svg>
  );
}

export function SituationIcon({ name, size = 24 }: { name: string; size?: number }) {
  const icon = (I as Record<string, (p: P) => ReactElement>)[name] ?? I.doc;
  return icon({ size });
}
