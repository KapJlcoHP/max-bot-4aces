import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, clinicHarness, deferred } from "./clinic-flow-harness.mjs";

const region = "Ивановская область";
const user = { id: 1, first_name: "Иван", last_name: "", region, attached_clinic_id: 1,
  notifications_on: true, notify_day_before: true, notify_hour_before: true, notify_at_deadline: true, step_day_before_time: "09:00" };
const org = (id, title, org_type = "Поликлиники", ownRegion = region) => ({ id, title, org_type, region: ownRegion,
  address: `Адрес ${id}`, phone: "123", hours: "9–18", services: [], lat: null, lon: null });
const orgs = [org(1, "Старая клиника"), org(2, "Новая клиника"), org(3, "Больница", "Больницы"), org(4, "Чужая клиника", "Поликлиники", "Владимирская область")];

test("catalog and map browse only; existing choice is marked and cannot be replaced", async () => {
  const h = clinicHarness({ user, orgs });
  await h.flush();
  assert.match(h.text(), /Текущая поликлиника/);
  assert.doesNotMatch(h.text(), /Выбрать поликлинику/);
  h.node((node) => node.type === "OrganizationMap").props.onSelect(2);
  assert.deepEqual(h.navigation, ["/orgs/2"]);
  assert.deepEqual(h.mutations(), []);
});

test("change mode locks filters, shows old/new confirmation; cancel does not mutate", async () => {
  const h = clinicHarness({ user, orgs, search: "?mode=change" });
  await h.flush();
  assert.equal(h.node((n) => n.type === "select").props.disabled, true);
  assert.match(h.calls.find((c) => c.path.startsWith("/api/v1/orgs?")).path, /org_type=.*&region=/);
  h.node((n) => n.type === "OrganizationMap").props.onSelect(2);
  assert.equal(h.navigation[0], "/orgs/2?mode=change");
  h.click("Выбрать поликлинику");
  await h.flush();
  assert.match(h.text(), /Сейчас: Старая клиника · Адрес 1/);
  assert.match(h.text(), /Новый выбор: Новая клиника · Адрес 2/);
  assert.match(h.text(), /Настройка в МедМаршруте. Не оформляет официальное прикрепление/);
  h.node((n) => n.type === "Sheet").props.onClose();
  await h.flush();
  assert.deepEqual(h.mutations(), []);
  assert.equal(h.user().attached_clinic_id, 1);
});

test("duplicate confirm clicks are synchronously guarded; network failure retains confirmation", async () => {
  const pending = deferred();
  let attempt = 0;
  const h = clinicHarness({ user, orgs, search: "?mode=change", post: () => ++attempt === 1 ? pending.promise : { ...user, attached_clinic_id: 2 } });
  await h.flush(); h.click("Выбрать поликлинику"); await h.flush();
  const confirm = h.button("Подтвердить выбор").props.onClick;
  const first = confirm(); const duplicate = confirm();
  await h.flush();
  assert.equal(h.mutations().length, 1);
  assert.equal(h.mutations()[0].path, "/api/v1/me/clinic");
  assert.equal(JSON.stringify(h.mutations()[0].payload), JSON.stringify({ attached_clinic_id: 2, expected_clinic_id: 1, expected_region: region }));
  pending.reject(new Error("offline")); await Promise.all([first, duplicate]); await h.flush();
  assert.equal(h.user().attached_clinic_id, 1);
  assert.match(h.text(), /Новый выбор: Новая клиника/);
  await h.click("Подтвердить выбор"); await h.flush();
  assert.equal(h.user().attached_clinic_id, 2);
  assert.equal(h.mutations().length, 2);
});

test("409 refreshes profile and requires a new confirmation, with no automatic replay", async () => {
  const fresh = { ...user, attached_clinic_id: null };
  const h = clinicHarness({ user, orgs, search: "?mode=change", post: () => { throw new ApiError(409); },
    get: (path) => path === "/api/v1/me" ? fresh : path === "/api/v1/regions" ? [] : path.startsWith("/api/v1/orgs?") ? orgs : orgs.find((o) => path.endsWith(`/${o.id}`)) });
  await h.flush(); h.click("Выбрать поликлинику"); await h.flush(); await h.click("Подтвердить выбор"); await h.flush();
  assert.equal(h.mutations().length, 1);
  assert.equal(h.user().attached_clinic_id, null);
  assert.doesNotMatch(h.text(), /Новый выбор:/);
  assert.ok(h.toasts.some((message) => message.includes("подтвердите выбор заново")));
});

test("first attach in normal detail requires confirmation and rejects foreign/hospital actions", async () => {
  const firstUser = { ...user, attached_clinic_id: null };
  const h = clinicHarness({ page: "OrgDetail", orgId: 2, user: firstUser, orgs,
    post: () => ({ ...firstUser, attached_clinic_id: 2 }) });
  await h.flush(); assert.deepEqual(h.mutations(), []);
  h.click("Выбрать поликлинику"); await h.flush(); assert.match(h.text(), /Сейчас: Поликлиника не выбрана/);
  await h.click("Подтвердить выбор"); await h.flush(); assert.equal(h.user().attached_clinic_id, 2);
  for (const orgId of [3, 4]) {
    const other = clinicHarness({ page: "OrgDetail", orgId, user: firstUser, orgs, search: "?mode=change" });
    await other.flush(); assert.doesNotMatch(other.text(), /Выбрать поликлинику/); assert.deepEqual(other.mutations(), []);
    assert.equal(other.node((n) => n.type === "Header").props.back, "/orgs?mode=change");
  }
});

test("profile has one clinic row, explicit change navigation and no detach control", async () => {
  const h = clinicHarness({ page: "Profile", user, orgs });
  await h.flush();
  assert.match(h.text(), /Старая клиника · Адрес 1/);
  assert.doesNotMatch(h.text(), /Открепить поликлинику/);
  h.cell("Прикрепленная поликлиника").props.onClick();
  assert.deepEqual(h.navigation, ["/orgs?mode=change"]);
  assert.deepEqual(h.mutations(), []);
});

test("region warning can cancel; save waits for response and sends acknowledged exact state", async () => {
  const pending = deferred();
  const h = clinicHarness({ page: "Profile", user, orgs, patch: () => pending.promise });
  await h.flush(); h.cell("Регион").props.onClick(); await h.flush();
  h.node((n) => n.type === "button" && n.props.children?.[1]?.props?.["aria-label"] === "Владимирская область").props.onClick();
  await h.flush(); assert.match(h.text(), /будет убрана из профиля/);
  h.click("Отмена"); await h.flush(); assert.deepEqual(h.mutations(), []);
  h.cell("Регион").props.onClick(); await h.flush();
  h.node((n) => n.type === "button" && n.props.children?.[1]?.props?.["aria-label"] === "Владимирская область").props.onClick();
  await h.flush(); const save = h.click("Изменить регион и сбросить поликлинику"); await h.flush();
  assert.equal(h.user().region, region); assert.equal(h.user().attached_clinic_id, 1);
  assert.equal(JSON.stringify(h.mutations()[0].payload), JSON.stringify({ region: "Владимирская область", expected_region: region, expected_clinic_id: 1, confirm_clinic_reset: true }));
  pending.resolve({ ...user, region: "Владимирская область", attached_clinic_id: null }); await save; await h.flush();
  assert.equal(h.user().region, "Владимирская область"); assert.equal(h.user().attached_clinic_id, null);
});

test("region failures keep the previous state and confirmation; conflict refreshes without retry", async () => {
  let conflict = false;
  const h = clinicHarness({ page: "Profile", user, orgs, patch: () => { throw conflict ? new ApiError(409) : new Error("offline"); } });
  await h.flush(); h.cell("Регион").props.onClick(); await h.flush();
  h.node((n) => n.type === "button" && n.props.children?.[1]?.props?.["aria-label"] === "Владимирская область").props.onClick();
  await h.flush(); await h.click("Изменить регион и сбросить поликлинику"); await h.flush();
  assert.equal(h.user().region, region); assert.equal(h.user().attached_clinic_id, 1);
  assert.match(h.text(), /Изменить регион и сбросить поликлинику/);
  assert.equal(h.mutations().length, 1);
  conflict = true;
  await h.click("Изменить регион и сбросить поликлинику"); await h.flush();
  assert.equal(h.mutations().length, 2);
  assert.ok(h.calls.some((call) => call.path === "/api/v1/me"));
  assert.doesNotMatch(h.text(), /Изменить регион и сбросить поликлинику/);
  assert.equal(h.user().attached_clinic_id, 1);
});
