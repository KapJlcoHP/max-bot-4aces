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

/** Календарные дни до срока в часовом поясе пользователя, независимо от пояса устройства. */
export function deadlineCountdown(
  iso: string | null | undefined,
  time: string | null | undefined,
  tz: string,
  now = new Date(),
): { text: string; overdue: boolean } {
  const missing = { text: "Срок не указан", overdue: false };
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!match) return missing;
  const [, year, month, day] = match.map(Number);
  const due = new Date(Date.UTC(year, month - 1, day));
  if (due.getUTCFullYear() !== year || due.getUTCMonth() !== month - 1 || due.getUTCDate() !== day) return missing;
  const options: Intl.DateTimeFormatOptions = {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  };
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat("en-GB", options);
  } catch {
    formatter = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: "Europe/Moscow" });
  }
  const parts = Object.fromEntries(formatter.formatToParts(now).map((part) => [part.type, part.value]));
  const today = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
  const days = Math.round((due.getTime() - today) / 86400000);
  const count = Math.abs(days);
  const noun = count % 10 === 1 && count % 100 !== 11 ? "день"
    : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14) ? "дня" : "дней";
  if (days < 0) return { text: `Просрочено на ${count} ${noun}`, overdue: true };
  if (days > 0) return { text: `${noun === "день" ? "Остался" : "Осталось"} ${days} ${noun}`, overdue: false };
  const clock = /^(\d{2}):(\d{2})$/.exec(time ?? "");
  if (clock && Number(clock[1]) < 24 && Number(clock[2]) < 60) {
    const dueMinute = Number(clock[1]) * 60 + Number(clock[2]);
    const currentMinute = Number(parts.hour) * 60 + Number(parts.minute);
    if (currentMinute > dueMinute) return { text: "Срок прошёл сегодня", overdue: true };
    if (currentMinute === dueMinute) return { text: "Срок наступил", overdue: false };
  }
  return { text: "Сегодня", overdue: false };
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
