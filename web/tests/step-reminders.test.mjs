import assert from "node:assert/strict";
import test from "node:test";
import { reminderHarness } from "./step-reminders-harness.mjs";
import { reminderWallTime } from "../src/stepReminderTime.ts";

const user = { tz: "Asia/Tokyo", notifications_on: true, notify_day_before: true,
  notify_hour_before: true, notify_at_deadline: true, step_day_before_time: "09:15" };
const step = { id: 4, position: 1, title: "Приём", description: "", place: "", status: "current", source: "user", reason: "", source_info: null,
  deadline: "2030-01-03", deadline_time: "14:00", reminder_mode: "profile", reminder_at: null, activated_at: "2030-01-01T00:00:00Z" };
const custom = { ...step, reminder_mode: "custom", reminder_at: "2030-01-03T01:30:00Z" };
const route = { id: 2, title: "Маршрут", total_steps: 1, done_steps: 0, steps: [step] };
const clean = (value) => JSON.parse(JSON.stringify(value));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function editor(value = step, api = {}, overrides = {}) {
  return reminderHarness("components/StepScheduleEditor.tsx", { user, props: { step: value }, api, ...overrides });
}

test("reminder wall inputs use the profile zone independent of process/device timezone", () => {
  assert.equal(reminderWallTime("2030-01-02T20:30:00Z", "Asia/Tokyo"), "2030-01-03T05:30");
  assert.equal(reminderWallTime("2030-01-02T20:30:00Z", "America/Los_Angeles"), "2030-01-02T12:30");
  assert.equal(reminderWallTime("2030-11-03T05:30:00Z", "America/New_York"), "2030-11-03T01:30");
  assert.equal(reminderWallTime("2030-11-03T06:30:00Z", "America/New_York"), "2030-11-03T01:30");
});

test("event edits are staged and custom time requires review; unchanged instant survives confirmation", async () => {
  const page = editor(custom, { patch: async (_, body) => ({ ...custom, ...body }) });
  await page.flush();
  assert.equal(page.input("Дата и время напоминания").props.value, "2030-01-03T10:30");
  page.change("Срок шага", "2030-01-04");
  await page.flush();
  assert.equal(page.calls.length, 0);
  assert.equal(page.button("Сохранить срок и напоминание").props.disabled, true);
  await page.button("Сохранить срок и напоминание").props.onClick();
  await page.flush();
  assert.equal(page.calls.length, 0);
  assert.match(page.text(), /подтвердите время/);
  page.confirm();
  await page.flush();
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  const body = page.calls[0].payload;
  assert.equal(body.deadline, "2030-01-04");
  assert.equal(body.reminder_mode, "custom");
  assert.equal(body.reminder_at, custom.reminder_at);
  assert.equal(page.saved.length, 1);
});

test("exclusive reminder radio and new datetime submit a profile-wall value, not device UTC", async () => {
  const page = editor(step, { patch: async (_, body) => ({ ...step, ...body, reminder_at: "2030-01-02T23:45:00Z" }) });
  await page.flush();
  page.radio("За день");
  await page.flush();
  assert.equal(page.all().filter((n) => n.props?.type === "radio" && n.props.checked).length, 1);
  page.radio("В другое время…");
  await page.flush();
  page.change("Дата и время напоминания", "2030-01-03T08:45");
  await page.flush();
  assert.equal(page.calls.length, 0);
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  assert.equal(page.calls[0].payload.reminder_at, "2030-01-03T08:45");
  assert.equal(page.calls[0].payload.reminder_mode, "custom");
});

test("save awaits response and guards synchronous duplicate handlers", async () => {
  const pending = deferred();
  const page = editor(step, { patch: () => pending.promise });
  await page.flush();
  const button = page.button("Сохранить срок и напоминание");
  const first = button.props.onClick(), duplicate = button.props.onClick();
  await page.flush();
  assert.equal(page.calls.length, 1);
  assert.equal(page.saved.length, 0);
  assert.doesNotMatch(page.text(), /напоминание сохранены/);
  assert.equal(page.button("Сохраняем…").props.disabled, true);
  pending.resolve(step);
  await Promise.all([first, duplicate]);
  await page.flush();
  assert.equal(page.saved.length, 1);
  assert.match(page.text(), /напоминание сохранены/);
});

test("server failure retains changed event and notification fields for retry", async () => {
  let count = 0;
  const page = editor(custom, { patch: async (_, body) => {
    if (++count === 1) throw new Error("Время неоднозначно в часовом поясе профиля");
    return { ...custom, ...body, reminder_at: "2030-01-03T03:00:00Z" };
  } });
  await page.flush();
  page.change("Срок шага: время (необязательно)", "16:15");
  page.change("Дата и время напоминания", "2030-01-03T12:00");
  await page.flush();
  page.confirm();
  await page.flush();
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  assert.match(page.text(), /Время неоднозначно/);
  assert.equal(page.saved.length, 0);
  assert.equal(page.input("Срок шага: время (необязательно)").props.value, "16:15");
  assert.equal(page.input("Дата и время напоминания").props.value, "2030-01-03T12:00");
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  assert.deepEqual(clean(page.calls[0].payload), clean(page.calls[1].payload));
  assert.equal(page.saved.length, 1);
});

test("clearing event date clears dependent time and custom override, with an explicit warning", async () => {
  const page = editor(custom, { patch: async (_, body) => ({ ...custom, ...body }) });
  await page.flush();
  page.change("Срок шага", "");
  await page.flush();
  assert.match(page.text(), /также уберёт время события и отдельное напоминание/);
  assert.equal(page.input("Срок шага: время (необязательно)").props.value, "");
  assert.equal(page.input("Срок шага: время (необязательно)").props.disabled, true);
  assert.doesNotMatch(page.text(), /За час|За день|В другое время…/);
  assert.match(page.text(), /Сначала укажите дату события/);
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  assert.deepEqual(clean(page.calls[0].payload), { deadline: null, deadline_time: null, reminder_mode: "profile", reminder_at: null });
});

test("pending expired custom timer remains editable, explaining activation and global gate", async () => {
  const value = { ...custom, status: "pending", reminder_at: "2030-01-01T00:00:00Z", activated_at: "2030-01-02T00:00:00Z" };
  const page = editor(value, { patch: async (_, body) => ({ ...value, ...body }) }, { user: { ...user, notifications_on: false } });
  await page.flush();
  assert.match(page.text(), /Время напоминания прошло/);
  assert.match(page.text(), /пропущенное уведомление не отправится/);
  assert.match(page.text(), /Уведомления выключены в профиле/);
  page.radio("Как в профиле");
  await page.flush();
  await page.click("Сохранить срок и напоминание");
  await page.flush();
  assert.equal(page.saved[0].status, "pending");
  assert.equal(page.calls[0].payload.reminder_mode, "profile");
  assert.ok(page.calls.every((c) => c.method === "patch"));
});

for (const status of ["pending", "current"]) {
  test(`step card ${status}: pending complete is disabled and guarded; event editor replaces unrelated reminder`, async () => {
    const value = { ...step, status };
    const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "4" }, api: { get: async () => ({ ...route, steps: [value] }), post: async () => ({}) } });
    await page.flush();
    assert.equal(page.all().filter((n) => n.type === "StepScheduleEditor").length, 1);
    assert.equal(page.all().filter((n) => n.type === "Button" && n.props.children === "Напомнить").length, 0);
    assert.equal(page.button("Я это сделал").props.disabled, status === "pending");
    if (status === "pending") {
      await page.button("Я это сделал").props.onClick();
      await page.flush();
      assert.match(page.text(), /Сначала завершите текущий шаг/);
      assert.equal(page.calls.filter((c) => c.method === "post").length, 0);
    }
  });
}

test("route undated hint opens first unfinished undated step without activation", async () => {
  const steps = [{ ...step, id: 1, status: "done", deadline: null }, { ...step, id: 2, status: "current" }, { ...step, id: 3, status: "pending", deadline: null }];
  const page = reminderHarness("pages/RoutePage.tsx", { user, api: { get: async (path) => path.endsWith("checklist") ? { total: 0 } : { ...route, steps, total_steps: 3, done_steps: 1 } } });
  await page.flush();
  assert.match(page.text(), /У некоторых шагов не указана дата/);
  page.click("Указать дату");
  assert.deepEqual(page.navigation, ["/step/3"]);
  assert.ok(page.calls.every((c) => c.method === "get"));
});

for (const done of [false, true]) {
  test(`route hint hidden when ${done ? "done" : "all scheduled"}`, async () => {
    const page = reminderHarness("pages/RoutePage.tsx", { user, api: { get: async (path) => path.endsWith("checklist") ? { total: 0 } : { ...route, done_steps: done ? 1 : 0, steps: [{ ...step, status: done ? "done" : "current", deadline: done ? null : step.deadline }] } } });
    await page.flush();
    assert.doesNotMatch(page.text(), /У некоторых шагов не указана дата/);
  });
}

test("own route step preserves date/time after failure, retries once, and clears time with date", async () => {
  let attempts = 0;
  const pending = deferred();
  const page = reminderHarness("pages/RoutePage.tsx", { user, api: {
    get: async (path) => path.endsWith("checklist") ? { total: 0 } : route,
    post: async () => { if (++attempts === 1) throw new Error("offline"); return pending.promise; },
  } });
  await page.flush();
  page.click("Добавить шаг");
  await page.flush();
  page.change("Название шага", "Своя запись");
  page.change("Срок", "2030-01-04");
  await page.flush();
  page.change("Срок: время (необязательно)", "11:20");
  await page.flush();
  await page.click("Добавить в маршрут");
  await page.flush();
  assert.equal(page.input("Срок").props.value, "2030-01-04");
  assert.equal(page.input("Срок: время (необязательно)").props.value, "11:20");
  assert.equal(page.calls.find((c) => c.method === "post").payload.deadline_time, "11:20");
  const button = page.button("Добавить в маршрут");
  const one = button.props.onClick(), two = button.props.onClick();
  await page.flush();
  assert.equal(page.calls.filter((c) => c.method === "post").length, 2);
  assert.ok(!page.toasts.includes("Шаг добавлен в маршрут"));
  pending.resolve(route);
  await Promise.all([one, two]);
  await page.flush();
  assert.ok(page.toasts.includes("Шаг добавлен в маршрут"));
  page.click("Добавить шаг");
  await page.flush();
  page.change("Срок", "2030-01-04");
  await page.flush();
  page.change("Срок: время (необязательно)", "11:20");
  await page.flush();
  page.change("Срок", "");
  await page.flush();
  assert.equal(page.input("Срок: время (необязательно)").props.value, "");
  assert.equal(page.input("Срок: время (необязательно)").props.disabled, true);
});

test("builder sends optional event time and keeps saved draft steps on failure", async () => {
  const page = reminderHarness("pages/Builder.tsx", { user, api: { get: async () => [], post: async () => { throw new Error("offline"); } } });
  await page.flush();
  page.find((n) => n.props?.role === "button" && n.props?.["aria-pressed"] === false).props.onClick();
  await page.flush();
  page.change("Название шага", "Анализ");
  page.change("Срок", "2030-01-04");
  await page.flush();
  page.change("Срок: время (необязательно)", "07:45");
  await page.flush();
  page.input("Добавить").props.onClick();
  await page.flush();
  await page.click("Создать маршрут — 1 шагов");
  await page.flush();
  assert.equal(page.calls.find((c) => c.method === "post").payload.custom_steps[0].deadline_time, "07:45");
  assert.match(page.text(), /Анализ/);
  assert.match(page.text(), /07:45/);
  assert.deepEqual(page.navigation, []);
});

test("doctor assignment carries optional time and remains editable after submission failure", async () => {
  const value = { ...step, status: "done" };
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "4" }, api: {
    get: async () => ({ ...route, done_steps: 1, steps: [value] }),
    post: async () => { throw new Error("offline"); },
  } });
  await page.flush();
  page.click("Записать назначения врача");
  await page.flush();
  page.change("Название назначения", "МРТ");
  page.change("Срок", "2030-01-04");
  await page.flush();
  page.change("Срок: время (необязательно)", "17:30");
  await page.flush();
  page.input("Добавить назначение").props.onClick();
  await page.flush();
  await page.click("Готово — добавить 1");
  await page.flush();
  assert.equal(page.calls.find((c) => c.method === "post").payload.deadline_time, "17:30");
  assert.equal(page.input("Срок: МРТ: время (необязательно)").props.value, "17:30");
  assert.deepEqual(page.navigation, []);
});
