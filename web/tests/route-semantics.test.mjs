import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, reminderHarness } from "./step-reminders-harness.mjs";
import { bookingTargets } from "../src/stepKinds.ts";

const user = { id: 7, max_user_id: 70, tz: "Europe/Moscow", notifications_on: true };
const booking = { id: 1, position: 1, kind: "booking", title: "Записаться", status: "current", source: "user", description: "", place: "", source_info: null,
  appointment_date: null, booking_target_step_id: null, deadline: "2030-01-02", deadline_time: "10:10", reminder_mode: "custom", reminder_at: "2030-01-01T08:00:00Z", reminder_revision: 0 };
const event = { ...booking, id: 3, position: 3, kind: "visit", title: "Приём", status: "pending", deadline: null, deadline_time: null, reminder_mode: "profile", reminder_at: null, reminder_revision: 12 };
const route = { id: 1, total_steps: 3, done_steps: 0, steps: [booking, { ...event, id: 2, position: 2, kind: "task", title: "Подготовка" }, event] };
const clean = (value) => JSON.parse(JSON.stringify(value));
const posts = (page) => page.calls.filter((c) => c.method === "post");
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function editor(step = booking, steps = route.steps, api = {}) {
  return reminderHarness("components/BookingEditor.tsx", { user, props: { step, steps, onReload() {} }, api: {
    post: async () => ({ step, route, next_step: event }), ...api,
  } });
}

test("targets use explicit same-route IDs and order, never title, source or next doctor", () => {
  const options = [booking, { ...event, id: 8, position: 0 }, { ...event, id: 9, status: "done" }, { ...event, id: 10, kind: "unknown" },
    { ...event, id: 11, kind: "booking" }, { ...event, id: 12, kind: "investigation", source: "doctor" }, event];
  assert.deepEqual(bookingTargets(options, booking).map((s) => s.id), [12, 3]);
});

test("booking editor keeps date, target and both primary actions visible while advanced details remain available", async () => {
  const page = editor({ ...booking, appointment_date: "2030-01-20", booking_target_step_id: 3 }, [booking, event]);
  await page.flush();
  assert.equal(page.input("На какую дату вы записались?").props.value, "2030-01-20");
  assert.equal(page.input("Цель записи").props.value, 3);
  assert.equal(page.button("Сохранить дату").props.disabled, false);
  assert.equal(page.button("Я записался").props.disabled, false);
  assert.ok(page.all().some((node) => node.type === "details" && page.text().includes("Подробности записи")));
});

test("booking step card keeps technical editors and source in compact advanced sections", async () => {
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "1" }, api: {
    get: async () => ({ ...route, steps: [booking, event] }),
  } });
  await page.flush();
  assert.equal(page.all().filter((node) => node.type === "BookingEditor").length, 1);
  const detailsText = page.all().filter((node) => node.type === "details").map((node) => JSON.stringify(node.props.children)).join(" ");
  assert.match(detailsText, /Срок и напоминание/);
  assert.match(detailsText, /Вид шага и связь/);
  assert.match(detailsText, /Источник/);
});

for (const kind of ["unknown", "booking", "investigation", "task", "process"]) {
  test(`${kind} completes normally without assignment sheet; done anchor cannot add assignments`, async () => {
    const value = { ...booking, kind };
    const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "1" }, api: {
      get: async () => ({ ...route, steps: [value] }), post: async () => ({ step: { ...value, status: "done" }, route: { ...route, steps: [{ ...value, status: "done" }] } }),
    } });
    await page.flush();
    const click = page.button(kind === "booking" ? "Завершить без внесения даты" : "Я это сделал").props.onClick;
    await Promise.all([click(), click()]);
    await page.flush();
    assert.equal(posts(page).length, 1);
    assert.equal(posts(page)[0].path, "/api/v1/route/steps/1/complete");
    assert.equal(page.all().filter((n) => n.type === "Sheet").length, 0);
    assert.doesNotMatch(page.text(), /Записать назначения врача/);
  });
}

test("assignment chips and own text send explicit roles, including single procedure versus process", async () => {
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "3" }, api: {
    get: async () => ({ ...route, steps: [{ ...event, status: "current" }] }), post: async () => ({ route, added_step_ids: [4, 5, 6, 7, 8, 9, 10] }),
  } });
  await page.flush(); page.click("Я это сделал"); await page.flush();
  for (const title of ["Анализы", "УЗИ", "Прививка", "Приём специалиста", "Разовая процедура", "Этап курса процедур"]) { page.click(title); await page.flush(); }
  page.change("Название назначения", "Мой контроль"); page.change("Вид своего назначения", "investigation"); await page.flush();
  page.input("Добавить назначение").props.onClick(); await page.flush();
  await page.click("Готово — добавить 7"); await page.flush();
  assert.deepEqual(clean(posts(page)[0].payload.assignments.map((s) => [s.title, s.kind])), [
    ["Мой контроль", "investigation"], ["Анализы", "investigation"], ["УЗИ", "investigation"], ["Прививка", "investigation"],
    ["Приём специалиста", "visit"], ["Разовая процедура", "investigation"], ["Этап курса процедур", "process"],
  ]);
});

test("booking entered as a doctor assignment stores obtained date, not action deadline or time", async () => {
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "3" }, api: {
    get: async () => ({ ...route, steps: [{ ...event, status: "current" }] }),
    post: async () => ({ route, added_step_ids: [4] }),
  } });
  await page.flush(); page.click("Я это сделал"); await page.flush();
  page.change("Название назначения", "Записаться на повтор"); page.change("Вид своего назначения", "booking"); await page.flush();
  page.change("Дата полученной записи назначения", "2035-10-24"); await page.flush();
  page.input("Добавить назначение").props.onClick(); await page.flush();
  assert.match(page.text(), /Пока дата не привязана/);
  await page.click("Готово — добавить 1"); await page.flush();
  assert.deepEqual(clean(posts(page)[0].payload.assignments[0]), {
    title: "Записаться на повтор", kind: "booking", appointment_date: "2035-10-24", deadline: null, deadline_time: null,
  });
});

test("booking allows unknown date/unlinked receipt, without copying action deadline or event time", async () => {
  const page = editor(); await page.flush();
  assert.match(page.text(), /Дата пока неизвестна/);
  assert.match(page.text(), /Без связи с событием/);
  assert.equal(page.input("Цель записи").props.value, "");
  await page.click("Я записался"); await page.flush();
  const body = posts(page)[0].payload;
  assert.deepEqual(clean(body), { request_id: body.request_id, complete: true, appointment_date: null, target_step_id: null,
    expected_target_revision: null, confirm_target_change: false, target_reminder_action: "keep" });
  assert.match(body.request_id, /^[0-9a-f-]{36}$/i);
  assert.equal(page.saved.length, 1);
});

test("save-only explicitly selects a later event and revision; complete is separate", async () => {
  const page = editor(); await page.flush();
  page.change("На какую дату вы записались?", "2030-01-20");
  page.change("Цель записи", "3"); await page.flush();
  await page.click("Сохранить дату"); await page.flush();
  const body = posts(page)[0].payload;
  assert.equal(body.complete, false); assert.equal(body.appointment_date, "2030-01-20");
  assert.equal(body.target_step_id, 3); assert.equal(body.expected_target_revision, 12);
  assert.equal(body.deadline, undefined); assert.equal(body.deadline_time, undefined);
  assert.match(page.text(), /Приём назначен на 2030-01-20/);
});

test("overwriting target date/time/custom needs explicit review and keep/profile decision", async () => {
  const target = { ...event, deadline: "2030-01-10", deadline_time: "14:45", reminder_mode: "custom", reminder_at: "2030-01-09T08:00:00Z" };
  const page = editor({ ...booking, booking_target_step_id: 3 }, [booking, target]); await page.flush();
  page.change("На какую дату вы записались?", "2030-01-20"); await page.flush();
  assert.match(page.text(), /2030-01-10 14:45/); assert.match(page.text(), /2030-01-20/);
  assert.match(page.text(), /Абсолютный таймер останется/);
  assert.equal(page.button("Сохранить дату").props.disabled, true);
  await page.button("Сохранить дату").props.onClick(); await page.flush();
  assert.equal(posts(page).length, 0);
  page.change("Напоминание цели", "profile"); await page.flush();
  page.confirm(); await page.flush();
  await page.click("Сохранить дату"); await page.flush();
  assert.equal(posts(page)[0].payload.confirm_target_change, true);
  assert.equal(posts(page)[0].payload.target_reminder_action, "profile");
  assert.equal(posts(page)[0].payload.expected_target_revision, 12);
});

test("clearing obtained date does not request clearing target schedule; pending save remains possible", async () => {
  const page = editor({ ...booking, status: "pending", appointment_date: "2030-01-20", booking_target_step_id: 3 }); await page.flush();
  assert.equal(page.button("Я записался").props.disabled, true);
  await page.button("Я записался").props.onClick(); await page.flush();
  assert.equal(posts(page).length, 0);
  assert.match(page.text(), /Будущую запись можно редактировать/);
  page.change("На какую дату вы записались?", ""); await page.flush();
  assert.match(page.text(), /не удаляет дату и таймер события/);
  await page.click("Сохранить дату"); await page.flush();
  assert.equal(posts(page)[0].payload.appointment_date, null);
  assert.equal(posts(page)[0].payload.complete, false);
  assert.equal(posts(page)[0].payload.target_step_id, 3);
});

test("booking double click is synchronous guarded; uncertain response freezes UUID/body across retry/auth error", async () => {
  const pending = deferred(); let attempts = 0;
  const page = editor(booking, route.steps, { post: async () => {
    if (++attempts === 1) return pending.promise;
    if (attempts === 2) throw new ApiError(401, "auth");
    return { step: booking, route, next_step: event };
  } });
  await page.flush(); page.change("На какую дату вы записались?", "2030-01-20"); await page.flush();
  const oldSave = page.button("Я записался").props.onClick;
  const oldInput = page.input("На какую дату вы записались?").props.onChange;
  const a = oldSave(), b = oldSave(); await page.flush();
  assert.equal(posts(page).length, 1); assert.equal(page.saved.length, 0);
  pending.reject(new Error("lost")); await Promise.all([a, b]); await page.flush();
  assert.match(page.text(), /могла сохраниться/); assert.equal(page.input("На какую дату вы записались?").props.disabled, true);
  oldInput({ target: { value: "2030-02-01" } }); await oldSave(); await page.flush();
  assert.equal(posts(page).length, 1); assert.equal(page.input("На какую дату вы записались?").props.value, "2030-01-20");
  await page.click("Повторить исходную отправку записи"); await page.flush();
  assert.equal(page.input("Цель записи").props.disabled, true);
  await page.click("Повторить исходную отправку записи"); await page.flush();
  assert.equal(posts(page).length, 3);
  assert.deepEqual(clean(posts(page)[0]), clean(posts(page)[1])); assert.deepEqual(clean(posts(page)[0]), clean(posts(page)[2]));
  assert.equal(page.saved.length, 1);
});

test("booking validation rejection retains editable draft; corrected operation gets a new UUID", async () => {
  let attempts = 0;
  const page = editor(booking, route.steps, { post: async () => {
    if (++attempts === 1) throw new ApiError(409, "Цель изменена в другом окне");
    return { step: booking, route, next_step: event };
  } });
  await page.flush(); page.change("На какую дату вы записались?", "2030-01-20"); await page.flush();
  await page.click("Сохранить дату"); await page.flush();
  assert.match(page.text(), /Цель изменена/); assert.equal(page.input("Цель записи").props.disabled, false);
  page.change("На какую дату вы записались?", "2030-01-21"); await page.flush();
  await page.click("Сохранить дату"); await page.flush();
  assert.notEqual(posts(page)[0].payload.request_id, posts(page)[1].payload.request_id);
  assert.equal(posts(page)[1].payload.appointment_date, "2030-01-21");
});

test("missing linked target is explained and cannot silently bind to next physician", async () => {
  const page = editor({ ...booking, booking_target_step_id: 999 }); await page.flush();
  assert.match(page.text(), /Цель недоступна/);
  await page.click("Сохранить дату"); await page.flush();
  assert.equal(posts(page).length, 0);
  page.change("Цель записи", ""); await page.flush();
  await page.click("Сохранить дату"); await page.flush();
  assert.equal(posts(page)[0].payload.target_step_id, null);
});

test("unknown old kind is explicitly clarified with PATCH, preserving scheduling fields", async () => {
  const old = { ...booking, kind: "unknown" };
  const page = reminderHarness("components/StepKindEditor.tsx", { user, props: { step: old, steps: route.steps }, api: { patch: async (_, body) => ({ ...old, ...body }) } });
  await page.flush(); assert.match(page.text(), /прежний шаг/);
  page.change("Вид шага", "booking"); await page.flush();
  page.change("Связанное событие", "3"); await page.flush();
  await page.click("Сохранить вид и связь"); await page.flush();
  assert.deepEqual(clean(page.calls[0].payload), { kind: "booking", booking_target_step_id: 3 });
  assert.equal(page.saved[0].deadline_time, "10:10");
});

test("completed old unknown is clarified by kind-only PATCH, without undoing historical completion", async () => {
  const old = { ...booking, kind: "unknown", status: "done" };
  const page = reminderHarness("components/StepKindEditor.tsx", { user, props: { step: old, steps: [old, event] }, api: {
    patch: async (_, body) => ({ ...old, ...body }),
  } });
  await page.flush(); page.change("Вид шага", "visit"); await page.flush();
  await page.click("Сохранить вид и связь"); await page.flush();
  assert.deepEqual(clean(page.calls[0].payload), { kind: "visit" });
  assert.match(page.text(), /исторические сведения не меняются/);
});

test("legacy booking editor exposes old action time separately, never accepts a new exact time", async () => {
  const page = reminderHarness("components/StepScheduleEditor.tsx", { user, props: { step: { ...booking, reminder_mode: "profile", reminder_at: null } }, api: { patch: async (_, body) => ({ ...booking, ...body }) } });
  await page.flush(); assert.match(page.text(), /Прежний срок действия записи/); assert.match(page.text(), /Прежнее время действия: 10:10/);
  assert.equal(page.all().filter((n) => n.props?.type === "time").length, 0);
  page.change("Срок действия записи", "2030-01-03"); await page.flush();
  await page.click("Сохранить срок и напоминание"); await page.flush();
  assert.equal(page.calls[0].payload.deadline, "2030-01-03");
  assert.equal("deadline_time" in page.calls[0].payload, false);
  page.click("Очистить прежнее время"); await page.flush();
  await page.click("Сохранить срок и напоминание"); await page.flush();
  assert.equal(page.calls[1].payload.deadline_time, null);
});

test("route before_step_id query opens explicit preparation insertion and sends ID plus selected role", async () => {
  const page = reminderHarness("pages/RoutePage.tsx", { user, query: "before_step_id=3", api: {
    get: async (path) => path.endsWith("checklist") ? { total: 0 } : route, post: async () => route,
  } });
  await page.flush(); page.change("Название шага", "Получить результат"); page.change("Вид шага", "task"); await page.flush();
  assert.equal(page.input("Добавить перед шагом").props.value, "3");
  await page.click("Добавить в маршрут"); await page.flush();
  assert.equal(posts(page)[0].path, "/api/v1/route/steps?before_step_id=3");
  assert.equal(posts(page)[0].payload.before_step_id, undefined); assert.equal(posts(page)[0].payload.kind, "task");
  assert.equal(posts(page)[0].payload.after_step_id, undefined);
});

test("route request failure is an error, not an empty route during semantic editing", async () => {
  const page = reminderHarness("pages/RoutePage.tsx", { user, api: {
    get: async (path) => { if (path.endsWith("checklist")) return { total: 0 }; throw new Error("network"); },
  } });
  await page.flush();
  assert.ok(page.find((n) => n.type === "ErrorView"));
  assert.doesNotMatch(page.text(), /Маршрута пока нет/);
});

test("checklist failure is retryable and never renders a missing route", async () => {
  let fail = true;
  const page = reminderHarness("pages/RoutePage.tsx", { user, api: {
    get: async (path) => {
      if (path.endsWith("checklist") && fail) throw new Error("network");
      return path.endsWith("checklist") ? { total: 0 } : null;
    },
  } });
  await page.flush();
  assert.ok(page.find((n) => n.type === "ErrorView"));
  assert.doesNotMatch(page.text(), /Маршрута пока нет/);
  fail = false;
  await page.find((n) => n.type === "ErrorView").props.onRetry();
  await page.flush();
  assert.doesNotMatch(page.text(), /Не удалось загрузить данные/);
  assert.match(page.text(), /Выберите свою первую ситуацию/);
});

test("HealthHub API failure is retryable and never looks like disabled diaries", async () => {
  let fail = true;
  const page = reminderHarness("pages/HealthHub.tsx", { user, api: {
    get: async (path) => {
      if (path.endsWith("health/settings") && fail) throw new Error("network");
      if (path.endsWith("health/settings")) return { diaries: [
        { diary: "bp", enabled: true, push_time: "09:00" },
        { diary: "weight", enabled: false, push_time: null },
        { diary: "sugar", enabled: false, push_time: null },
        { diary: "mood", enabled: true, push_time: "09:00" },
      ] };
      if (path.endsWith("/meds")) return { today: [], courses: [] };
      return [];
    },
  } });
  await page.flush();
  assert.ok(page.find((n) => n.type === "ErrorView"));
  assert.doesNotMatch(page.text(), /Дневники не выбраны/);
  assert.equal(page.find((n) => n.type === "Header").props.back, "/");
  fail = false;
  await page.find((n) => n.type === "ErrorView").props.onRetry();
  await page.flush();
  assert.doesNotMatch(page.text(), /Не удалось загрузить данные/);
  assert.doesNotMatch(page.text(), /Дневники не выбраны/);
});

test("R6: structured wellbeing notes keep the report non-empty without a free-text note", async () => {
  const page = reminderHarness("pages/Report.tsx", { user, api: {
    get: async (path) => path.endsWith("/health/report")
      ? { bp_avg: null, weight_latest: null, sugar_avg: null, meds: [], notes: [
        { at: "2030-01-02T10:00:00+03:00", note: "Самочувствие: Хорошо · боль 0/10" },
      ] }
      : { status: "idle", attempts: 0, can_retry: false },
  } });
  await page.flush();
  assert.match(page.text(), /Заметки о самочувствии/);
  assert.match(page.text(), /Самочувствие: Хорошо · боль 0\/10/);
  assert.doesNotMatch(page.text(), /Пока нечего показывать/);
});

test("Home and timeline distinguish obtained date from legacy action deadline", async () => {
  const value = { ...booking, appointment_date: "2030-02-20" };
  const data = { ...route, steps: [value, event] };
  const home = reminderHarness("pages/Home.tsx", { user, api: { get: async (path) => path.endsWith("/route") ? data : path.endsWith("/meds") ? { today: [] } : [] } });
  await home.flush();
  assert.match(home.text(), /Полученная дата события: 2030-02-20/);
  assert.match(home.text(), /Прежний срок действия записи: 2030-01-02 10:10/);
  assert.match(home.text(), /Срок действия записи: Отсчёт срока 2030-01-02/);
  assert.doesNotMatch(home.text(), /Отсчёт срока 2030-02-20/);
  const timeline = reminderHarness("pages/RoutePage.tsx", { user, api: { get: async (path) => path.endsWith("checklist") ? { total: 0 } : data } });
  await timeline.flush();
  assert.match(timeline.text(), /Полученная дата события: 2030-02-20/);
  assert.match(timeline.text(), /Прежний срок действия записи: 2030-01-02 10:10/);
  assert.match(timeline.text(), /без связи с событием/);
});

test("late booking response is ignored after leaving the form", async () => {
  const pending = deferred();
  const page = editor(booking, route.steps, { post: () => pending.promise });
  await page.flush();
  const saving = page.click("Сохранить дату"); await page.flush();
  page.unmount(); pending.resolve({ step: booking, route });
  await saving; await page.flush();
  assert.equal(page.saved.length, 0);
});

test("booking receipt lock also blocks source completion and competing role/schedule saves", async () => {
  const page = reminderHarness("pages/StepCard.tsx", { user, params: { stepId: "1" }, api: { get: async () => route } });
  await page.flush();
  const complete = page.button("Завершить без внесения даты").props.onClick;
  page.find((n) => n.type === "BookingEditor").props.onLocked(true);
  await complete(); await page.flush();
  assert.equal(posts(page).length, 0);
  assert.equal(page.button("Завершить без внесения даты").props.disabled, true);
  assert.equal(page.find((n) => n.type === "StepKindEditor").props.disabled, true);
  assert.equal(page.find((n) => n.type === "StepScheduleEditor").props.disabled, true);
});

async function addBuilderStep(page, title, kind) {
  page.change("Название шага", title); page.change("Вид шага", kind); await page.flush();
  page.input("Добавить").props.onClick(); await page.flush();
}

test("failed template preview cannot create unseen template steps; retry preserves own draft", async () => {
  let fail = true;
  const page = reminderHarness("pages/Builder.tsx", { user, api: {
    get: async (path) => {
      if (!path.endsWith("/steps")) return [{ key: "doctor", title: "Основа" }];
      if (fail) throw new Error("network");
      return [{ position: 1, key: "visit", kind: "visit", title: "Визит" }];
    }, post: async () => route,
  } });
  await page.flush(); page.find((n) => n.props?.role === "button").props.onClick(); await page.flush();
  await addBuilderStep(page, "Свой результат", "task");
  const create = page.button("Создать маршрут — 1 шагов");
  assert.equal(create.props.disabled, true);
  await create.props.onClick(); assert.equal(posts(page).length, 0);
  fail = false; await page.find((n) => n.type === "ErrorView").props.onRetry(); await page.flush();
  await page.click("Создать маршрут — 2 шагов"); await page.flush();
  assert.equal(posts(page)[0].payload.custom_steps[0].title, "Свой результат");
});

test("manual builder supports stable keys, explicit booking targets and user reordering", async () => {
  const page = reminderHarness("pages/Builder.tsx", { user, api: { get: async () => [], post: async () => route } });
  await page.flush(); page.find((n) => n.props?.role === "button").props.onClick(); await page.flush();
  await addBuilderStep(page, "Запись", "booking");
  await addBuilderStep(page, "Исследование", "investigation");
  await addBuilderStep(page, "Результат", "task");
  const targetOptions = page.input("Цель записи: Запись").props.children;
  const option = targetOptions.flat(Infinity).find((n) => n?.type === "option" && n.props.value);
  page.change("Цель записи: Запись", option.props.value); await page.flush();
  page.input("Выше: Результат").props.onClick(); await page.flush();
  await page.click("Создать маршрут — 3 шагов"); await page.flush();
  const steps = posts(page)[0].payload.custom_steps;
  assert.deepEqual(clean(steps.map((s) => [s.title, s.kind])), [["Запись", "booking"], ["Результат", "task"], ["Исследование", "investigation"]]);
  assert.equal(new Set(steps.map((s) => s.client_key)).size, 3);
  assert.equal(steps[0].booking_target_key, steps[2].client_key);
});

test("template builder keeps original positions for insertion and reports excluded target as unlinked", async () => {
  const template = [{ position: 10, key: "book", kind: "booking", title: "Запись", booking_target_key: "event", description: "" },
    { position: 20, key: "prep", kind: "task", title: "Подготовка", description: "" }, { position: 30, key: "event", kind: "visit", title: "Визит", description: "" }];
  const page = reminderHarness("pages/Builder.tsx", { user, api: { get: async (path) => path.endsWith("/steps") ? template : [{ key: "doctor", title: "Маршрут" }], post: async () => route } });
  await page.flush(); page.find((n) => n.props?.role === "button").props.onClick(); await page.flush();
  assert.doesNotMatch(page.text(), /исходная позиция|#book|#event/);
  page.change("Размещение нового шага", "30"); await page.flush();
  await addBuilderStep(page, "Фактическое назначение", "investigation");
  page.find((n) => n.type === "Switch" && n.props.label === "Подготовка").props.onChange(false); await page.flush();
  await page.click("Создать маршрут — 3 шагов"); await page.flush();
  assert.equal(posts(page)[0].payload.custom_steps[0].before_position, 30);
  assert.deepEqual(clean(posts(page)[0].payload.exclude_positions), [20]);
  page.find((n) => n.type === "Switch" && n.props.label === "Визит").props.onChange(false); await page.flush();
  assert.match(page.text(), /Без связи: цель не задана или исключена/);
  assert.match(page.text(), /исключена — уточните размещение/);
});
