/** Format an instant for a datetime-local field in the PROFILE timezone. */
export function reminderWallTime(instant: string | null, tz: string): string {
  if (!instant) return "";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz || "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(instant));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}
