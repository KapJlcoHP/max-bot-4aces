import assert from "node:assert/strict";
import test from "node:test";
import { deadlineCountdown } from "../src/format.ts";

const now = new Date("2026-10-17T09:00:00Z");

test("countdown uses calendar days and Russian day forms", () => {
  for (const [deadline, text] of [
    ["2026-10-18", "Остался 1 день"],
    ["2026-10-20", "Осталось 3 дня"],
    ["2026-10-22", "Осталось 5 дней"],
    ["2026-10-28", "Осталось 11 дней"],
    ["2026-11-07", "Остался 21 день"],
  ]) {
    assert.deepEqual(deadlineCountdown(deadline, null, "Europe/Moscow", now), { text, overdue: false });
  }
});

test("today's timed deadline becomes overdue only after its time", () => {
  assert.deepEqual(deadlineCountdown("2026-10-17", null, "Europe/Moscow", now), { text: "Сегодня", overdue: false });
  assert.deepEqual(deadlineCountdown("2026-10-17", "13:00", "Europe/Moscow", now), { text: "Сегодня", overdue: false });
  assert.deepEqual(deadlineCountdown("2026-10-17", "12:00", "Europe/Moscow", now), { text: "Срок наступил", overdue: false });
  assert.deepEqual(deadlineCountdown("2026-10-17", "11:59", "Europe/Moscow", now), { text: "Срок прошёл сегодня", overdue: true });
  assert.deepEqual(deadlineCountdown("2026-10-14", null, "Europe/Moscow", now), { text: "Просрочено на 3 дня", overdue: true });
});

test("countdown follows the user's timezone across midnight and daylight saving", () => {
  const midnight = new Date("2026-10-17T21:30:00Z");
  assert.equal(deadlineCountdown("2026-10-20", null, "Europe/Moscow", midnight).text, "Осталось 2 дня");
  assert.equal(deadlineCountdown("2026-10-20", null, "America/New_York", midnight).text, "Осталось 3 дня");
  assert.equal(deadlineCountdown("2026-11-02", null, "America/New_York", new Date("2026-10-03T11:00:00Z")).text, "Осталось 30 дней");
});

test("missing or invalid dates do not produce fabricated countdowns", () => {
  for (const value of [null, undefined, "", "abc", "2026-02-31"]) {
    assert.deepEqual(deadlineCountdown(value, null, "Europe/Moscow", now), { text: "Срок не указан", overdue: false });
  }
  assert.deepEqual(deadlineCountdown("2026-10-20", null, "Invalid/Zone", now), { text: "Осталось 3 дня", overdue: false });
});
