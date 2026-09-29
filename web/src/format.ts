const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(iso);
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

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Числовая дата «день.месяц.год»: 27.09.2026 */
export function fmtDateNumeric(iso: string | Date | null | undefined): string {
  const d = iso instanceof Date ? iso : parseDate(iso);
  return d ? `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}` : "";
}

/** «08:30» */
export function fmtHhmm(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("");
}
