import assert from "node:assert/strict";
import test from "node:test";
import { deferred, onboardingHarness } from "./onboarding-r1-harness.mjs";

const regions = [{ key: "moscow", title: "Москва" }];
const clinics = [{ id: 17, title: "Поликлиника №17", address: "Улица 1" }];
const saved = { id: 42, consent_accepted: true };

function setup(overrides = {}) {
  return onboardingHarness({
    get: async (path) => path === "/api/v1/regions" ? regions : clinics,
    post: async () => saved,
    ...overrides,
  });
}

async function reachRegion(page) {
  await page.flush();
  page.click("Дальше");
  await page.flush();
  page.agree();
  await page.flush();
  page.click("Продолжить");
  await page.flush();
}

async function selectRegion(page) {
  await reachRegion(page);
  page.change("Регион", "Москва");
  await page.flush();
}

for (const clinicId of [null, 17]) {
  test(`R1: consent submits ${clinicId === null ? "without" : "with"} an optional clinic and awaits the response`, async () => {
    const pending = deferred();
    const page = setup({ post: () => pending.promise });
    await selectRegion(page);
    if (clinicId !== null) {
      page.change("Поликлиника", String(clinicId));
      await page.flush();
    }
    page.click(clinicId === null ? "Выбрать поликлинику позже" : "Продолжить");
    await page.flush();
    const start = page.button("Начать");
    assert.equal(Boolean(start.props.disabled), false);
    const submission = page.click("Начать");
    // Invoke the same handler twice before React can commit a disabled button.
    const duplicate = start.props.onClick();
    await page.flush();
    assert.equal(page.calls.filter((call) => call.method === "POST").length, 1);
    assert.equal(page.savedUsers.length, 0);
    assert.equal(page.button("Настраиваем…").props.disabled, true);
    const request = page.calls.find((call) => call.method === "POST");
    assert.equal(request.path, "/api/v1/me/consent");
    assert.equal(request.payload.region, "Москва");
    assert.equal(request.payload.attached_clinic_id, clinicId);
    assert.ok(request.payload.diaries.every((diary) => diary.push_time === null));
    pending.resolve(saved);
    await Promise.all([submission, duplicate]);
    await page.flush();
    assert.deepEqual(page.savedUsers, [saved]);
  });
}

for (const region of ["", "Несуществующий регион"]) {
  test(`R1: step 2 rejects ${region ? "an invalid" : "a missing"} region before continuing`, async () => {
    const page = setup();
    await reachRegion(page);
    if (region) {
      page.change("Регион", region);
      await page.flush();
    }
    page.click("Выбрать поликлинику позже");
    await page.flush();
    assert.match(page.text(), /Ваш регион и прикрепленная поликлиника/);
    assert.ok(page.alerts().includes("Выберите регион из списка"));
    assert.equal(page.calls.filter((call) => call.method === "POST").length, 0);
    page.change("Регион", "Москва");
    await page.flush();
    page.click("Выбрать поликлинику позже");
    await page.flush();
    assert.match(page.text(), /Дневники под себя/);
    assert.deepEqual(page.alerts(), []);
  });
}

test("R1: clinics request failure permits consent with a valid region and null clinic", async () => {
  const page = setup({ get: async (path) => {
    if (path === "/api/v1/regions") return regions;
    throw new Error("Clinics unavailable");
  } });
  await selectRegion(page);
  assert.ok(page.alerts().some((message) => message.includes("Не удалось загрузить поликлиники")));
  page.click("Выбрать поликлинику позже");
  await page.flush();
  await page.click("Начать");
  await page.flush();
  assert.equal(page.calls.find((call) => call.method === "POST").payload.attached_clinic_id, null);
  assert.deepEqual(page.savedUsers, [saved]);
});

test("R1: a pending optional clinics request does not block continuing without a clinic", async () => {
  const pending = deferred();
  const page = setup({ get: (path) => path === "/api/v1/regions" ? Promise.resolve(regions) : pending.promise });
  await selectRegion(page);
  page.click("Выбрать поликлинику позже");
  await page.flush();
  await page.click("Начать");
  await page.flush();
  assert.deepEqual(page.savedUsers, [saved]);
  pending.reject(new Error("Clinics unavailable"));
  await page.flush();
});

for (const clinicId of [null, 17]) {
  test(`R1: consent failure retains choices, announces an error on the final screen and retries (${clinicId})`, async () => {
    let attempts = 0;
    const page = setup({ post: async () => {
      if (++attempts === 1) throw new Error("Consent unavailable");
      return saved;
    } });
    await selectRegion(page);
    if (clinicId !== null) {
      page.change("Поликлиника", String(clinicId));
      await page.flush();
    }
    page.click(clinicId === null ? "Выбрать поликлинику позже" : "Продолжить");
    await page.flush();
    page.toggle("Давление и пульс", false);
    page.toggle("Сахар крови", true);
    page.change("Часовой пояс", "Asia/Omsk");
    await page.flush();
    await page.click("Начать");
    await page.flush();
    assert.match(page.text(), /Дневники под себя/);
    assert.ok(page.alerts().some((message) => message.includes("Не удалось сохранить настройки")));
    assert.equal(page.savedUsers.length, 0);
    assert.equal(Boolean(page.button("Начать").props.disabled), false);
    await page.click("Начать");
    await page.flush();
    const requests = page.calls.filter((call) => call.method === "POST");
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[1].payload, requests[0].payload);
    assert.equal(requests[1].payload.attached_clinic_id, clinicId);
    assert.equal(requests[1].payload.tz, "Asia/Omsk");
    assert.equal(requests[1].payload.diaries.find((diary) => diary.diary === "bp").enabled, false);
    assert.equal(requests[1].payload.diaries.find((diary) => diary.diary === "sugar").enabled, true);
    assert.deepEqual(page.savedUsers, [saved]);
    assert.deepEqual(page.alerts(), []);
  });
}
