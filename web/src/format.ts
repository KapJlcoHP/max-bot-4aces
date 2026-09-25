const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

/** «до 20 сентября» / «24 сентября, 10:00» */
export function fmtDeadline(iso: string | null | undefined, time?: string | null): string {
  const d = parseDate(iso);
  if (!d) return "";
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return time ? `${base}, ${time}` : `до ${base}`;
}

/** «Сегодня, 08:30» / «Вчера, 20:15» / «14 сентября, 08:10» */
export function fmtWhen(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return "";
  const now = new Date();
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (diff === 0) return `Сегодня, ${hhmm}`;
  if (diff === 1) return `Вчера, ${hhmm}`;
  if (diff === -1) return `Завтра, ${hhmm}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hhmm}`;
}

export function fmtDayMonth(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]}` : "";
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("");
}
