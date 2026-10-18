import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, reminderHarness } from "./step-reminders-harness.mjs";
import { reminderWallTime } from "../src/stepReminderTime.ts";

const user = { tz: "Asia/Tokyo", notifications_on: true, notify_day_before: true,
  notify_hour_before: true, notify_at_deadline: true, step_day_before_time: "09:15" };
const step = { id: 4, kind: "visit", reminder_revision: 0, position: 1, title: "Приём", description: "", place: "", status: "current", source: "user", reason: "", source_info: null,
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

test("M4: schedule headings are contextual and never expose the technical timezone name", async () => {
  const labels = { visit: "Расписание визита", investigation: "Расписание исследования", task: "Расписание задачи", process: "Расписание процесса" };
  for (const [kind, label] of Object.entries(labels)) {
    const page = editor({ ...step, kind });
    await page.flush();
    assert.match(page.text(), new RegExp(label));
    assert.doesNotMatch(page.text(), /Asia\/Tokyo|Europe\/Moscow|\btz\b/);
  }
});

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

test("doctor assignment carries optional time and remains editable after HTTP validation rejection", async () => {
  const value = { ...step, status: "done" };
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "4" }, api: {
    get: async () => ({ ...route, done_steps: 1, steps: [value] }),
    post: async () => { throw new ApiError(422, "Проверьте назначение"); },
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
  assert.equal(page.calls.find((c) => c.method === "post").payload.assignments[0].deadline_time, "17:30");
  assert.equal(page.input("Срок: МРТ: время (необязательно)").props.value, "17:30");
  assert.equal(page.input("Срок: МРТ").props.disabled, false);
  assert.deepEqual(page.navigation, []);
});

function stepCard(value = step, api = {}) {
  return reminderHarness("pages/StepCard.tsx", { user, params: { stepId: String(value.id) }, api: {
    get: async () => ({ ...route, steps: [value] }),
    post: async () => ({ step: { ...value, status: "done" }, route, next_step: null, added_step_ids: [] }),
    ...api,
  } });
}
const posts = (page) => page.calls.filter((call) => call.method === "post");
async function addAssignment(page, title, date = "", time = "") {
  page.change("Название назначения", title);
  page.change("Срок", date);
  await page.flush();
  if (time) { page.change("Срок: время (необязательно)", time); await page.flush(); }
  page.input("Добавить назначение").props.onClick();
  await page.flush();
}

test("completion opens a staged sheet; cancel and backdrop close make no requests or navigation", async () => {
  const page = stepCard({ ...step, reason: "Исходное основание" });
  await page.flush();
  await page.click("Я это сделал");
  await page.flush();
  assert.match(page.text(), /только после подтверждения/);
  await addAssignment(page, "Черновик");
  page.click("Отмена");
  await page.flush();
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
  page.click("Я это сделал");
  await page.flush();
  assert.match(page.text(), /Черновик/);
  page.find((n) => n.type === "Sheet").props.onClose();
  await page.flush();
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
  assert.equal(posts(page).length, 0);
  assert.deepEqual(page.navigation, []);
  assert.doesNotMatch(page.text(), /Почему этот шаг появился|Исходное основание/);
  assert.match(page.text(), /Источник/);
});

test("atomic assignment submission preserves displayed order, duplicate titles and optional date/time", async () => {
  const pending = deferred();
  const page = stepCard(step, { post: () => pending.promise });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  page.click("Анализы");
  await page.flush();
  await addAssignment(page, "МРТ", "2030-01-04", "17:30");
  await addAssignment(page, "МРТ", "2030-01-05");
  const save = page.button("Готово — добавить 3").props.onClick;
  const noAssignments = page.button("Без назначений").props.onClick;
  const cancel = page.button("Отмена").props.onClick;
  const close = page.find((n) => n.type === "Sheet").props.onClose;
  const first = save(), duplicate = save(), other = noAssignments();
  cancel(); close();
  await page.flush();
  assert.equal(posts(page).length, 1);
  const { path, payload } = posts(page)[0];
  assert.equal(path, "/api/v1/route/steps/4/assignments");
  assert.match(payload.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.deepEqual(clean(payload), { request_id: payload.request_id, complete: true, assignments: [
    { title: "МРТ", kind: "task", deadline: "2030-01-05", deadline_time: null },
    { title: "МРТ", kind: "task", deadline: "2030-01-04", deadline_time: "17:30" },
    { title: "Анализы", kind: "investigation", deadline: null, deadline_time: null },
  ] });
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 1);
  assert.deepEqual(page.navigation, []);
  assert.deepEqual(page.toasts, []);
  assert.equal(page.button("Отправляем…").props.disabled, true);
  pending.resolve({ step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [12, 13, 14] });
  await Promise.all([first, duplicate, other]);
  await page.flush();
  assert.deepEqual(page.navigation, ["/route"]);
  assert.deepEqual(page.toasts, ["Добавлено шагов: 3"]);
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
});

test("explicit no-assignments atomically completes and synchronously guards double clicks", async () => {
  const pending = deferred();
  const page = stepCard(step, { post: () => pending.promise });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  await addAssignment(page, "Не добавлять");
  const handler = page.button("Без назначений").props.onClick;
  const first = handler(), second = handler();
  await page.flush();
  assert.equal(posts(page).length, 1);
  assert.deepEqual(clean(posts(page)[0].payload.assignments), []);
  assert.equal(posts(page)[0].payload.complete, true);
  assert.deepEqual(page.navigation, []);
  assert.deepEqual(page.toasts, []);
  pending.resolve({ step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [] });
  await Promise.all([first, second]);
  await page.flush();
  assert.deepEqual(page.toasts, ["Шаг выполнен"]);
  assert.deepEqual(page.navigation, ["/route"]);
});

test("lost response freezes draft and retries identical UUID/body; stale edit/save handlers cannot duplicate", async () => {
  let attempts = 0;
  const page = stepCard(step, { post: async () => {
    if (++attempts === 1) throw new Error("Response lost after commit");
    return { step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [7] };
  } });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  await addAssignment(page, "МРТ", "2030-01-04", "17:30");
  const oldSave = page.button("Готово — добавить 1").props.onClick;
  const oldNoAssignments = page.button("Без назначений").props.onClick;
  const oldAdd = page.input("Добавить назначение").props.onClick;
  const oldClose = page.find((n) => n.type === "Sheet").props.onClose;
  await oldSave();
  await page.flush();
  assert.match(page.text(), /могли сохраниться/);
  assert.match(page.text(), /повтор не создаст дубликаты/);
  assert.equal(page.input("Срок: МРТ").props.disabled, true);
  assert.equal(page.input("Название назначения").props.disabled, true);
  page.change("Название назначения", "Другое");
  page.change("Срок: МРТ", "2030-01-09");
  oldAdd(); oldClose();
  await oldSave(); await oldNoAssignments();
  await page.flush();
  assert.equal(posts(page).length, 1);
  assert.equal(page.input("Срок: МРТ").props.value, "2030-01-04");
  assert.equal(page.input("Название назначения").props.value, "");
  assert.deepEqual(page.navigation, []);
  await page.click("Повторить исходную отправку");
  await page.flush();
  assert.equal(posts(page).length, 2);
  assert.deepEqual(clean(posts(page)[0]), clean(posts(page)[1]));
  assert.deepEqual(page.navigation, ["/route"]);
});

test("completed anchor batches with complete=false and exits after confirmed success", async () => {
  const page = stepCard({ ...step, status: "done" }, { post: async () => ({
    step: { ...step, status: "done" }, route: { ...route, steps: [{ ...step, status: "done" }] }, next_step: null, added_step_ids: [6],
  }) });
  await page.flush();
  page.click("Записать назначения врача");
  await page.flush();
  await addAssignment(page, "УЗИ");
  await page.click("Готово — добавить 1");
  await page.flush();
  assert.equal(posts(page).length, 1);
  assert.equal(posts(page)[0].payload.complete, false);
  assert.equal(posts(page)[0].payload.assignments[0].title, "УЗИ");
  assert.deepEqual(page.navigation, ["/route"]);
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
  assert.equal(page.all().filter((n) => n.props?.className === "picked-item").length, 0);
});

test("authentication error after a lost response retains the original retry key", async () => {
  let attempts = 0;
  const page = stepCard(step, { post: async () => {
    if (++attempts === 1) throw new Error("Response lost");
    if (attempts === 2) throw new ApiError(401, "Войдите заново");
    return { step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [7] };
  } });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  await addAssignment(page, "УЗИ");
  await page.click("Готово — добавить 1");
  await page.flush();
  await page.click("Повторить исходную отправку");
  await page.flush();
  assert.equal(page.input("Название назначения").props.disabled, true);
  await page.click("Повторить исходную отправку");
  await page.flush();
  assert.equal(posts(page).length, 3);
  assert.deepEqual(clean(posts(page)[0]), clean(posts(page)[1]));
  assert.deepEqual(clean(posts(page)[0]), clean(posts(page)[2]));
  assert.deepEqual(page.navigation, ["/route"]);
});

test("definitive validation rejection preserves editable draft and allows corrected new request", async () => {
  let attempts = 0;
  const page = stepCard(step, { post: async () => {
    if (++attempts === 1) throw new ApiError(422, "Неверная дата");
    return { step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [6] };
  } });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  await addAssignment(page, "УЗИ", "2030-01-04");
  await page.click("Готово — добавить 1");
  await page.flush();
  assert.match(page.text(), /Неверная дата/);
  assert.equal(page.input("Срок: УЗИ").props.disabled, false);
  page.change("Срок: УЗИ", "2030-01-05");
  await page.flush();
  await page.click("Готово — добавить 1");
  await page.flush();
  assert.notEqual(posts(page)[0].payload.request_id, posts(page)[1].payload.request_id);
  assert.equal(posts(page)[1].payload.assignments[0].deadline, "2030-01-05");
});

test("state conflict can refresh the route instead of retrying forever", async () => {
  let loaded = 0;
  const page = stepCard(step, {
    get: async () => ({ ...route, steps: [{ ...step, status: ++loaded === 1 ? "current" : "done" }] }),
    post: async () => { throw new ApiError(409, "Состояние шага изменилось. Обновите маршрут"); },
  });
  await page.flush();
  page.click("Я это сделал");
  await page.flush();
  await page.click("Без назначений");
  await page.flush();
  assert.match(page.text(), /Состояние шага изменилось/);
  assert.doesNotMatch(page.text(), /могли сохраниться/);
  assert.equal(page.button("Отмена").props.disabled, false);
  page.click("Обновить маршрут");
  await page.flush();
  assert.equal(loaded, 2);
  assert.equal(posts(page).length, 1);
  assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
  assert.ok(page.button("Записать назначения врача"));
});

test("completed route retains timeline, step access and adding another step", async () => {
  const finishedRoute = { ...route, done_steps: 1, steps: [{ ...step, status: "done" }] };
  const page = reminderHarness("pages/RoutePage.tsx", { user, api: {
    get: async (path) => path.endsWith("checklist") ? { total: 0 } : finishedRoute,
    post: async () => route,
  } });
  await page.flush();
  assert.match(page.text(), /Маршрут завершён/);
  assert.doesNotMatch(page.text(), /Продолжить — шаг/);
  page.input("Открыть шаг Приём").props.onClick();
  assert.deepEqual(page.navigation, ["/step/4"]);
  page.click("Добавить шаг");
  await page.flush();
  page.change("Название шага", "Продолжение");
  await page.flush();
  await page.click("Добавить в маршрут");
  await page.flush();
  assert.equal(posts(page).length, 1);
  assert.equal(posts(page)[0].payload.title, "Продолжение");
});

for (const change of ["step", "session", "unmount"]) {
  test(`late batch response cannot navigate or toast after ${change} change`, async () => {
    const pending = deferred();
    const page = stepCard(step, { get: async () => ({ ...route, steps: [step, { ...step, id: 5 }] }), post: () => pending.promise });
    await page.flush();
    page.click("Я это сделал");
    await page.flush();
    await addAssignment(page, "Черновик");
    const sending = page.click("Готово — добавить 1");
    await page.flush();
    if (change === "step") page.setParams({ stepId: "5" });
    if (change === "session") page.setUser({ ...user, id: 99 });
    if (change === "unmount") page.unmount();
    else await page.flush();
    pending.resolve({ step: { ...step, status: "done" }, route, next_step: null, added_step_ids: [6] });
    await sending;
    await page.flush();
    assert.deepEqual(page.navigation, []);
    assert.deepEqual(page.toasts, []);
    if (change !== "unmount") {
      page.click("Я это сделал");
      await page.flush();
      assert.equal(page.all().filter((n) => n.props?.className === "picked-item").length, 0);
      assert.equal(page.input("Название назначения").props.value, "");
    }
  });
}
