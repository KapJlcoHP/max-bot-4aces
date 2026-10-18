import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, clinicHarness, deferred } from "./clinic-flow-harness.mjs";

const home = "Ивановская область", away = "Владимирская область";
const user = { id: 1, first_name: "Иван", last_name: "", region: home, attached_clinic_id: 1 };
const org = (id, title, org_type = "Поликлиники", region = home, lat = 57, lon = 41) => ({
  id, title, org_type, region, address: `Адрес ${id}`, phone: "+7 (4932) 56-95-66",
  hours: "Пн–Пт 9–18", services: [`Услуга ${id}`], lat, lon,
});
const orgs = [org(1, "Текущая клиника"), org(2, "Больница", "Больницы"),
  org(3, "Клиника без точки", "Поликлиники", home, null, null), org(4, "Чужая клиника", "Поликлиники", away),
  org(5, "Чужой центр", "Центры", away), org(6, "Городская поликлиника №12"),
  org(7, "Неверные координаты", "Диспансеры", home, 100, NaN)];
const map = (h) => h.node((node) => node.type === "OrganizationMap");
const mapIds = (h) => Array.from(map(h).props.organizations, (item) => item.id);
const cardIds = (h) => h.nodes((node) => node.type === "article").map((node) => Number(node.props.id.replace("org-card-", "")));
const assertAgreement = (h, ids) => { assert.deepEqual(mapIds(h), ids); assert.deepEqual(cardIds(h), ids); assert.equal(h.nodes((node) => node.type === "OrganizationMap").length, 1); };
const card = (h, id) => h.node((node) => node.type === "button" && node.props["aria-controls"] === `org-details-${id}`);
const selectCard = async (h, id) => { card(h, id).props.onClick(); await h.flush(); };
const chip = (h, title) => h.node((node) => node.type === "button" && node.props.children === title);
const regionControl = (h) => h.node((node) => node.type === "select");
const searchControl = (h) => h.node((node) => node.type === "Input");
const listCalls = (h) => h.calls.filter((call) => call.path.startsWith("/api/v1/orgs?"));
const params = (call) => new URLSearchParams(call.path.split("?")[1]);
function defaultGet(path) {
  if (path === "/api/v1/me") return user;
  if (path === "/api/v1/regions") return [{ key: "home", title: home }, { key: "away", title: away }];
  if (path.startsWith("/api/v1/orgs?")) return orgs;
  const found = orgs.find((item) => path === `/api/v1/orgs/${item.id}`);
  if (found) return found;
  throw new ApiError(404);
}

test("M1: card and marker select inline details independently from the attached clinic", async () => {
  const h = clinicHarness({ user, orgs });
  await h.flush();
  assertAgreement(h, [1, 2, 3, 6, 7]);
  const originalArray = map(h).props.organizations;
  assert.equal(map(h).props.selectedId, null);
  assert.equal(card(h, 1).props["aria-expanded"], false);
  await selectCard(h, 2);
  assert.equal(map(h).props.selectedId, 2);
  assert.equal(map(h).props.organizations, originalArray, "selection must not change the map dataset");
  assert.equal(card(h, 2).props["aria-expanded"], true);
  assert.match(h.text(), /Контакты и режим работы.*Пн–Пт 9–18.*Доступные услуги.*Услуга 2/);
  assert.equal(card(h, 1).props["aria-expanded"], false);
  map(h).props.onSelect(1); await h.flush();
  assert.equal(map(h).props.selectedId, 1);
  assert.equal(card(h, 1).props["aria-expanded"], true);
  assert.equal(card(h, 2).props["aria-expanded"], false);
  assert.equal(h.user().attached_clinic_id, 1);
  assert.deepEqual(h.navigation, []);
  assert.deepEqual(h.mutations(), []);
});

test("M1: region/type/search/reset handlers use one array and never edit profile", async () => {
  const h = clinicHarness({ user, orgs }); await h.flush();
  assert.equal(params(listCalls(h)[0]).get("region"), home);
  await selectCard(h, 1);
  regionControl(h).props.onChange({ target: { value: "Все" } }); await h.flush();
  assertAgreement(h, [1, 2, 3, 4, 5, 6, 7]);
  assert.equal(params(listCalls(h).at(-1)).has("region"), true);
  assert.equal(params(listCalls(h).at(-1)).get("region"), "");
  chip(h, "Больницы").props.onClick(); await h.flush();
  assertAgreement(h, [2]); assert.equal(map(h).props.selectedId, null);
  regionControl(h).props.onChange({ target: { value: away } }); await h.flush();
  assertAgreement(h, []); assert.match(h.text(), /Организации не найдены/);
  h.click("Сбросить фильтры"); await h.flush();
  assertAgreement(h, [1, 2, 3, 4, 5, 6, 7]); assert.equal(map(h).props.selectedId, null);
  searchControl(h).props.onChange({ target: { value: "  чУжАя  " } }); await h.flush(); await h.advance(250);
  assertAgreement(h, [4]); assert.equal(params(listCalls(h).at(-1)).get("q"), "чУжАя");
  assert.equal(h.user().region, home); assert.equal(h.user().attached_clinic_id, 1);
  assert.deepEqual(h.savedUsers, []); assert.deepEqual(h.mutations(), []);
});

test("M1: the active filter is a no-op rather than an endless loading state", async () => {
  const h = clinicHarness({ user, orgs }); await h.flush();
  const count = listCalls(h).length;
  chip(h, "Все").props.onClick(); await h.flush();
  regionControl(h).props.onChange({ target: { value: home } }); await h.flush();
  searchControl(h).props.onChange({ target: { value: "" } }); await h.flush();
  assertAgreement(h, [1, 2, 3, 6, 7]); assert.equal(listCalls(h).length, count);
});

test("M1: filter invalidation precedes debounce, ignoring a response arriving before the new request", async () => {
  const old = deferred(), next = deferred();
  const h = clinicHarness({ user, orgs, get: (path) => path.startsWith("/api/v1/orgs?") ? (new URLSearchParams(path.split("?")[1]).has("q") ? next.promise : old.promise) : defaultGet(path) });
  await h.flush(); assertAgreement(h, []);
  searchControl(h).props.onChange({ target: { value: "Больница" } });
  old.resolve(orgs); await h.flush();
  assertAgreement(h, []); assert.equal(listCalls(h).length, 1);
  await h.advance(249); assert.equal(listCalls(h).length, 1); assertAgreement(h, []);
  await h.advance(1); assert.equal(listCalls(h).length, 2); assertAgreement(h, []);
  next.resolve(orgs); await h.flush(); assertAgreement(h, [2]);
  assert.doesNotMatch(h.text(), /Не удалось загрузить/);
});

test("M1: superseded failures cannot overwrite newer filters or results", async () => {
  const old = deferred(); let attempt = 0;
  const h = clinicHarness({ user, orgs, get: (path) => path.startsWith("/api/v1/orgs?") ? (++attempt === 1 ? old.promise : orgs) : defaultGet(path) });
  await h.flush(); chip(h, "Больницы").props.onClick(); await h.flush(); assertAgreement(h, [2]);
  old.reject(new Error("stale offline")); await h.flush();
  assertAgreement(h, [2]); assert.doesNotMatch(h.text(), /Не удалось загрузить организации/);
});

test("M1: network errors clear map/list and retry the current filters without remounting the map", async () => {
  let offline = true; const retry = deferred();
  const h = clinicHarness({ user, orgs, get: (path) => {
    if (!path.startsWith("/api/v1/orgs?")) return defaultGet(path);
    if (offline) throw new Error("offline");
    return retry.promise;
  } });
  await h.flush(); assertAgreement(h, []); assert.match(h.text(), /Не удалось загрузить организации/);
  offline = false; h.click("Повторить"); await h.flush(); assertAgreement(h, []);
  retry.resolve(orgs); await h.flush(); assertAgreement(h, [1, 2, 3, 6, 7]);
  assert.equal(params(listCalls(h).at(-1)).get("region"), home);
});

test("M1: mobile map/card jumps focus explicit targets and missing coordinates retain usable details", async () => {
  const h = clinicHarness({ user, orgs }); await h.flush();
  assert.equal(h.button("К выбранной карточке").props.disabled, true);
  h.click("К карте"); h.click("К списку");
  await selectCard(h, 2); h.click("К точке на карте"); h.click("К выбранной карточке");
  assert.deepEqual(h.jumps.filter((jump) => jump.action === "focus").map((jump) => jump.id), ["org-map", "org-list", "org-map", "org-card-2"]);
  h.click("Построить путь в Яндексе");
  assert.equal(h.navigation.at(-1), "https://yandex.ru/maps/?rtext=~57,41&rtt=auto");
  for (const id of [3, 7]) {
    await selectCard(h, id);
    assert.equal(map(h).props.selectedId, id);
    assert.match(h.text(), /Координаты не указаны или некорректны.*точка на карте не показана/);
    assert.match(h.text(), new RegExp(`Услуга ${id}`));
    assert.equal(h.nodes((node) => node.type === "Button" && node.props.children === "К точке на карте").length, 0);
    h.click("Искать адрес в Яндексе");
    assert.equal(h.navigation.at(-1), `https://yandex.ru/maps/?text=${encodeURIComponent(`Адрес ${id}`)}`);
  }
  assert.deepEqual(h.mutations(), []);
});

test("M1: synthetic phone data is labelled and has no callable action", async () => {
  const h = clinicHarness({ user, orgs }); await h.flush(); await selectCard(h, 6);
  assert.match(h.text(), /Модельная организация.*данные демонстрационные/);
  assert.equal(h.nodes((node) => node.type === "a" && node.props.href?.startsWith("tel:")).length, 0);
  await selectCard(h, 2);
  assert.match(h.text(), /Телефон и часы работы справочные/);
  assert.equal(h.nodes((node) => node.type === "a" && node.props.href === "tel:+74932569566").length, 1);
});

test("M2: a legacy direct link fetches the organization and initializes matching region/type inline", async () => {
  const h = clinicHarness({ page: "OrgDetail", orgId: 5, user, orgs }); await h.flush();
  assert.equal(regionControl(h).props.value, away);
  assert.equal(chip(h, "Центры").props["aria-pressed"], true);
  assertAgreement(h, [5]); assert.equal(map(h).props.selectedId, 5);
  assert.equal(card(h, 5).props["aria-expanded"], true); assert.match(h.text(), /Услуга 5/);
  assert.equal(params(listCalls(h).at(-1)).get("region"), away);
  assert.equal(params(listCalls(h).at(-1)).get("org_type"), "Центры");
  assert.equal(h.user().region, home); assert.equal(h.user().attached_clinic_id, 1);
  assert.deepEqual(h.navigation, []); assert.deepEqual(h.mutations(), []);
});

test("M2: a fetched direct-link record is retained even if the list response omits it", async () => {
  const h = clinicHarness({ page: "OrgDetail", orgId: 4, user, orgs, get: (path) => path.startsWith("/api/v1/orgs?") ? [] : defaultGet(path) });
  await h.flush(); assertAgreement(h, [4]); assert.equal(map(h).props.selectedId, 4);
  regionControl(h).props.onChange({ target: { value: home } }); await h.flush();
  assertAgreement(h, []); assert.equal(map(h).props.selectedId, null);
});

test("M2: invalid identifiers and 404 are distinct from network errors", async () => {
  for (const orgId of ["0", "-2", "abc", "1.5", "9007199254740992"]) {
    const h = clinicHarness({ page: "OrgDetail", orgId, user: { ...user, attached_clinic_id: null }, orgs }); await h.flush();
    assert.match(h.text(), /Некорректная ссылка/); assertAgreement(h, []);
    assert.equal(h.calls.some((call) => call.path.startsWith("/api/v1/orgs/")), false);
    assert.equal(listCalls(h).length, 0);
  }
  const h = clinicHarness({ page: "OrgDetail", orgId: 999, user, orgs }); await h.flush();
  assert.match(h.text(), /Организация не найдена/); assert.doesNotMatch(h.text(), /Не удалось загрузить организацию/); assertAgreement(h, []);
  h.click("К списку организаций"); assert.deepEqual(h.navigation, ["/orgs"]);
});

test("M2: direct-link network failure has an explicit retry that restores the same screen", async () => {
  let fail = true;
  const h = clinicHarness({ page: "OrgDetail", orgId: 4, user, orgs, get: (path) => {
    if (path === "/api/v1/orgs/4" && fail) throw new Error("offline");
    return defaultGet(path);
  } });
  await h.flush(); assert.match(h.text(), /Не удалось загрузить организацию/); assertAgreement(h, []);
  fail = false; h.click("Повторить загрузку организации"); await h.flush();
  assertAgreement(h, [4]); assert.equal(map(h).props.selectedId, 4);
  assert.equal(regionControl(h).props.value, away); assert.deepEqual(h.mutations(), []);
});

test("M2: late direct-link responses cannot override the next URL or its filters", async () => {
  const old = deferred();
  const h = clinicHarness({ page: "OrgDetail", orgId: 2, user, orgs, get: (path) => path === "/api/v1/orgs/2" ? old.promise : defaultGet(path) });
  await h.flush(); assertAgreement(h, []);
  h.route(5); await h.flush(); assertAgreement(h, [5]); assert.equal(map(h).props.selectedId, 5);
  old.resolve(orgs[1]); await h.flush();
  assertAgreement(h, [5]); assert.equal(map(h).props.selectedId, 5);
  assert.equal(regionControl(h).props.value, away); assert.equal(chip(h, "Центры").props["aria-pressed"], true);
});

test("M2/C1–C4: change-mode links never bypass clinic/region locks, even with unfiltered API data", async () => {
  for (const orgId of [2, 4, 5]) {
    const h = clinicHarness({ page: "OrgDetail", orgId, user, orgs, search: "?mode=change", get: defaultGet });
    await h.flush(); assert.match(h.text(), /Организация недоступна для выбора/);
    assertAgreement(h, [1, 3, 6]); assert.equal(map(h).props.selectedId, null);
    assert.equal(regionControl(h).props.disabled, true); assert.equal(regionControl(h).props.value, home);
    assert.equal(chip(h, "Поликлиники").props["aria-pressed"], true);
    regionControl(h).props.onChange({ target: { value: "Все" } }); chip(h, "Больницы").props.onClick(); map(h).props.onSelect(orgId); await h.flush();
    assertAgreement(h, [1, 3, 6]); assert.equal(map(h).props.selectedId, null);
    assert.equal(params(listCalls(h).at(-1)).get("region"), home);
    assert.equal(params(listCalls(h).at(-1)).get("org_type"), "Поликлиники");
    assert.equal(h.user().attached_clinic_id, 1); assert.equal(h.user().region, home); assert.deepEqual(h.mutations(), []);
  }
});

test("M2/C1–C4: an eligible direct link is selected but attachment still requires confirmation", async () => {
  const h = clinicHarness({ page: "OrgDetail", orgId: 3, user, orgs, search: "?mode=change", post: () => ({ ...user, attached_clinic_id: 3 }) });
  await h.flush(); assertAgreement(h, [1, 3, 6]); assert.equal(map(h).props.selectedId, 3);
  assert.deepEqual(h.mutations(), []); assert.equal(h.user().attached_clinic_id, 1);
  const selectedArticle = h.node((node) => node.type === "article" && node.props.id === "org-card-3");
  const choose = selectedArticle.props.children.find((node) => node?.type === "Button");
  choose.props.onClick(); await h.flush();
  assert.match(h.text(), /Сейчас: Текущая клиника · Адрес 1.*Новый выбор: Клиника без точки · Адрес 3/);
  assert.deepEqual(h.mutations(), []);
  await h.click("Подтвердить выбор"); await h.flush();
  assert.equal(h.user().attached_clinic_id, 3);
  assert.deepEqual(h.mutations().map((call) => JSON.parse(JSON.stringify(call.payload))), [{ attached_clinic_id: 3, expected_clinic_id: 1, expected_region: home }]);
});
