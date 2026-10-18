import assert from "node:assert/strict";
import test from "node:test";
import { deferred, mapHarness } from "./organization-map-harness.mjs";

const org = (id, lon, lat, title = `Организация ${id}`) => ({ id, title, lon, lat });
const orgs = [org(1, 30, 50), org(2, 80, 65), org(3, null, null)];
const plain = (value) => JSON.parse(JSON.stringify(value));

test("bounds, callback/text updates, selection and filters share one map and SDK", async () => {
  const selected = [], latest = [];
  const h = mapHarness({ organizations: orgs, onSelect: (id) => selected.push(id) });
  await h.flush();
  assert.equal(h.maps.length, 1);
  assert.deepEqual(plain(h.maps[0].options.location), { bounds: [[30, 50], [80, 65]] });
  assert.equal(h.activeMarkers().length, 2);
  const first = h.markers[0];
  first.element.dispatch("click");
  assert.deepEqual(selected, [1]);
  h.update({ organizations: orgs.map((item) => ({ ...item, title: `${item.title} новое` })), onSelect: (id) => latest.push(id) });
  await h.flush();
  first.element.dispatch("click");
  assert.deepEqual(latest, [1]);
  assert.equal(h.markers.length, 2);
  assert.match(first.element.title, /новое/);
  assert.equal(h.maps[0].locations.length, 0);
  h.update({ selectedId: 2 }); await h.flush();
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { center: [80, 65], zoom: 15 });
  assert.match(h.markers[1].element.className, /selected/);
  assert.equal(h.markers[1].element.attributes["aria-pressed"], "true");
  h.update({ selectedId: 1 }); await h.flush();
  assert.doesNotMatch(h.markers[1].element.className, /selected/);
  assert.match(first.element.className, /selected/);
  h.update({ organizations: [orgs[1]], selectedId: null }); await h.flush();
  assert.deepEqual(h.activeMarkers(), [h.markers[1]]);
  first.element.dispatch("click"); assert.deepEqual(latest, [1]);
  assert.equal(h.maps.length, 1);
  assert.equal(h.calls.length, 1);
  assert.equal(h.scripts.length, 0);
  h.unmount();
  assert.equal(h.maps[0].destroyCount, 1);
  h.markers[1].element.dispatch("click"); assert.deepEqual(latest, [1]);
  assert.equal(h.timers.size, 0);
});

test("invalid selected coordinates never focus; empty loading/error catalogs remove stale markers", async () => {
  const h = mapHarness({ organizations: orgs, selectedId: 3 });
  await h.flush();
  assert.deepEqual(plain(h.maps[0].options.location), { bounds: [[30, 50], [80, 65]] });
  h.update({ selectedId: 2 }); await h.flush();
  h.update({ selectedId: 3 }); await h.flush();
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { bounds: [[30, 50], [80, 65]] });
  const movements = h.maps[0].locations.length;
  h.update({ organizations: [] }); await h.flush();
  assert.equal(h.activeMarkers().length, 0);
  assert.equal(h.maps[0].locations.length, movements);
  assert.equal(h.isVisible(), false);
  assert.match(h.text(), /нет координат/);
  h.update({ organizations: [orgs[1]], selectedId: 2 }); await h.flush();
  assert.equal(h.activeMarkers().length, 1);
  assert.equal(h.maps.length, 1);
  assert.equal(h.isVisible(), true);
  h.unmount();
});

test("coordinates validate finite numeric latitude/longitude and inclusive ranges", async () => {
  const h = mapHarness({ organizations: [org(1, NaN, 50), org(2, 30, Infinity), org(3, 181, 50), org(4, 30, -91), org(5, "30", 50)] });
  await h.flush();
  assert.equal(h.calls.length, 0);
  assert.equal(h.maps.length, 0);
  assert.match(h.text(), /нет координат/);
  for (const item of [org(1, NaN, 50), org(1, Infinity, 50), org(1, 30, -Infinity), org(1, -181, 0), org(1, 0, 91), org(1, null, 0)]) assert.equal(h.coordinatesOf(item), null);
  assert.deepEqual(plain(h.coordinatesOf(org(1, -180, -90))), [-180, -90]);
  assert.deepEqual(plain(h.coordinatesOf(org(1, 180, 90))), [180, 90]);
  h.update({ organizations: [org(1, 0, 0)] }); await h.flush();
  assert.deepEqual(plain(h.maps[0].options.location), { center: [0, 0], zoom: 15 });
  h.unmount();
});

test("coordinate edits replace only the affected marker and refit actual bounds", async () => {
  const h = mapHarness({ organizations: orgs }); await h.flush();
  const unchanged = h.markers[1], removed = h.markers[0];
  h.update({ organizations: [org(1, -20, 10), orgs[1], org(3, NaN, 20)] }); await h.flush();
  assert.equal(h.markers.length, 3);
  assert.ok(h.activeMarkers().includes(unchanged));
  assert.ok(!h.activeMarkers().includes(removed));
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { bounds: [[-20, 10], [80, 65]] });
  assert.equal(h.maps.length, 1);
  h.unmount();
});

test("filter updates fit visible results even when a selected card remains visible", async () => {
  const h = mapHarness({ organizations: orgs, selectedId: 2 }); await h.flush();
  assert.deepEqual(plain(h.maps[0].options.location), { center: [80, 65], zoom: 15 });
  h.update({ organizations: [], selectedId: null }); await h.flush();
  h.update({ organizations: [orgs[1], org(4, 40, 55)], selectedId: 2 }); await h.flush();
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { bounds: [[40, 55], [80, 65]] });
  const movements = h.maps[0].locations.length;
  h.update({ organizations: [orgs[1], org(4, 40, 55, "Новое название")] }); await h.flush();
  assert.equal(h.maps[0].locations.length, movements);
  h.update({ selectedId: 4 }); await h.flush();
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { center: [40, 55], zoom: 15 });
  assert.equal(h.maps.length, 1);
  h.unmount();
});

test("disabled configuration and config rejection are nonblocking and retryable", async () => {
  for (const failure of [() => ({ enabled: false, api_key: null }), () => { throw new Error("offline"); }]) {
    let failed = true;
    const h = mapHarness({ organizations: orgs, get: () => failed ? failure() : { enabled: true, api_key: "mock" } });
    await h.flush();
    assert.match(h.text(), /Повторить загрузку карты/);
    assert.equal(h.maps.length, 0);
    failed = false; h.retry(); await h.flush();
    assert.equal(h.maps.length, 1);
    h.unmount(); assert.equal(h.timers.size, 0);
  }
});

test("config timeout ignores late response and retries without unhandled rejection", async () => {
  const pending = deferred(); let count = 0;
  const h = mapHarness({ organizations: orgs, get: () => ++count === 1 ? pending.promise : { enabled: true, api_key: "mock" } });
  await h.flush(); await h.advance(12_001);
  assert.match(h.text(), /Повторить загрузку карты/);
  h.retry(); await h.flush(); assert.equal(h.maps.length, 1);
  pending.reject(new Error("late config error")); await h.flush();
  assert.equal(h.maps.length, 1);
  h.unmount(); assert.equal(h.timers.size, 0);
});

test("script error and timeout remove/reset the failed script; retry loads a fresh SDK", async () => {
  for (const kind of ["error", "timeout", "missing-api"]) {
    const h = mapHarness({ organizations: orgs, preload: false }); await h.flush();
    const old = h.scripts[0];
    const staleLoad = [...old.listeners.get("load")][0];
    const staleError = [...old.listeners.get("error")][0];
    if (kind === "error") old.dispatch("error");
    if (kind === "timeout") await h.advance(12_001);
    if (kind === "missing-api") old.dispatch("load");
    await h.flush();
    assert.equal(old.parent, null);
    assert.equal(old.listeners.get("load").size, 0);
    assert.match(h.text(), /Повторить загрузку карты/);
    h.retry(); await h.flush();
    assert.equal(h.scripts.length, 2);
    const fresh = h.scripts[1];
    staleError(); staleLoad(); await h.flush();
    assert.ok(fresh.parent);
    h.loadScript(fresh); await h.flush();
    assert.equal(h.maps.length, 1);
    assert.equal(h.isVisible(), true);
    h.unmount(); assert.equal(h.timers.size, 0);
  }
});

test("SDK ready timeout/rejection clears stale API and supports a fresh script retry", async () => {
  for (const kind of ["timeout", "rejection"]) {
    const pending = deferred();
    const h = mapHarness({ organizations: orgs, preload: false, ready: pending.promise }); await h.flush();
    h.loadScript(); await h.flush();
    if (kind === "timeout") await h.advance(12_001);
    else { pending.reject(new Error("SDK unavailable")); await h.flush(); }
    assert.equal(h.window.ymaps3, undefined);
    assert.equal(h.scripts[0].parent, null);
    h.retry(); await h.flush();
    const fresh = { ...h.sdk, ready: Promise.resolve() };
    h.loadScript(h.scripts[1], fresh); await h.flush();
    pending.resolve(); await h.flush();
    assert.equal(h.maps.length, 1);
    assert.equal(h.window.ymaps3, fresh);
    h.unmount(); assert.equal(h.timers.size, 0);
  }
});

test("unmount cancels config, script and readiness without late maps, timers or callbacks", async () => {
  for (const stage of ["config", "script", "ready"]) {
    const pending = deferred();
    const h = mapHarness({ organizations: orgs, preload: false,
      get: stage === "config" ? () => pending.promise : undefined,
      ready: stage === "ready" ? pending.promise : Promise.resolve() });
    await h.flush();
    if (stage === "ready") { h.loadScript(); await h.flush(); }
    h.unmount();
    pending.resolve({ enabled: true, api_key: "mock" }); await h.flush();
    assert.equal(h.maps.length, 0);
    assert.equal(h.timers.size, 0);
    assert.equal(h.lateUpdates(), 0);
    for (const script of h.scripts) { assert.equal(script.parent, null); assert.equal(script.listeners.get("load").size, 0); }
  }
});

test("pending initialization uses latest catalog/selection and SDK is shared by consumers", async () => {
  const pending = deferred();
  const h = mapHarness({ organizations: orgs, preload: false, get: () => pending.promise }); await h.flush();
  h.update({ organizations: [orgs[1]], selectedId: 2 }); await h.flush();
  pending.resolve({ enabled: true, api_key: "mock" }); await h.flush();
  const lease = h.loader.acquireYandexMaps("mock");
  assert.equal(h.scripts.length, 1);
  h.loadScript(); await lease.promise; await h.flush();
  assert.deepEqual(plain(h.maps[0].options.location), { center: [80, 65], zoom: 15 });
  assert.equal(h.activeMarkers().length, 1);
  lease.release(); h.unmount();
  assert.equal(h.timers.size, 0);
});

test("a shared script remains alive until its last pending consumer leaves", async () => {
  const h = mapHarness({ preload: false });
  const first = h.loader.acquireYandexMaps("mock");
  const second = h.loader.acquireYandexMaps("mock");
  assert.equal(first.promise, second.promise);
  first.release();
  assert.ok(h.scripts[0].parent);
  assert.equal(h.scripts.length, 1);
  h.loadScript();
  assert.equal(await second.promise, h.sdk);
  second.release(); h.unmount();
  assert.equal(h.timers.size, 0);
});

test("layer initialization failure destroys the partial map and explicit retry recovers", async () => {
  const h = mapHarness({ organizations: orgs });
  const Layer = h.sdk.YMapDefaultFeaturesLayer;
  h.sdk.YMapDefaultFeaturesLayer = class { constructor() { throw new Error("Layer failed"); } };
  await h.flush();
  assert.match(h.text(), /Повторить загрузку карты/);
  assert.equal(h.maps[0].destroyCount, 1);
  assert.equal(h.isVisible(), false);
  h.sdk.YMapDefaultFeaturesLayer = Layer;
  h.retry(); await h.flush();
  assert.equal(h.maps.length, 2);
  assert.equal(h.maps[0].destroyCount, 1);
  assert.equal(h.activeMarkers().length, 2);
  h.unmount();
  assert.equal(h.maps[1].destroyCount, 1);
});

test("catalog cleared during SDK readiness cannot resurrect stale organizations", async () => {
  const pending = deferred();
  const h = mapHarness({ organizations: orgs, ready: pending.promise }); await h.flush();
  h.update({ organizations: [] }); await h.flush();
  pending.resolve(); await h.flush();
  assert.equal(h.activeMarkers().length, 0);
  assert.equal(h.isVisible(), false);
  assert.match(h.text(), /нет координат/);
  h.update({ organizations: [orgs[1]] }); await h.flush();
  assert.equal(h.maps.length, 1);
  assert.equal(h.activeMarkers().length, 1);
  assert.deepEqual(plain(h.maps[0].locations.at(-1)), { center: [80, 65], zoom: 15 });
  h.unmount();
});
