import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";
import ts from "typescript";

const compiled = {};
for (const name of ["OrganizationMap", "organizationMapSdk"]) {
  const source = await readFile(new URL(`../src/components/${name}.${name === "OrganizationMap" ? "tsx" : "ts"}`, import.meta.url), "utf8");
  compiled[name] = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
}

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

class Element {
  constructor(tag) { this.tag = tag; this.listeners = new Map(); this.attributes = {}; this.children = []; }
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }
  removeEventListener(name, callback) { this.listeners.get(name)?.delete(callback); }
  dispatch(name) { for (const callback of [...this.listeners.get(name) ?? []]) callback(); }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { child.parent = this; this.children.push(child); }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
}

// Execute actual TSX effects and SDK loader, substituting only React hooks, DOM,
// SDK primitives, API transport and a deterministic clock. No network is used.
export function mapHarness({ organizations = [], selectedId, onSelect = () => {}, preload = true, get, ready = Promise.resolve() } = {}) {
  const hooks = [], effects = [], maps = [], markers = [], calls = [], scripts = [], timers = new Map();
  const head = new Element("head"), container = new Element("div");
  const document = {
    head,
    createElement(tag) { const element = new Element(tag); if (tag === "script") scripts.push(element); return element; },
    getElementById(id) { return head.children.find((element) => element.id === id) ?? null; },
  };
  let cursor = 0, dirty = true, mounted = true, tree, clock = 0, nextTimer = 0, lateUpdates = 0;
  let props = { organizations, selectedId, onSelect };
  const sdk = {
    ready,
    YMap: class {
      constructor(element, options) {
        this.element = element; this.options = options; this.children = []; this.locations = []; this.removed = []; this.destroyCount = 0;
        maps.push(this);
      }
      addChild(child) { this.children.push(child); }
      removeChild(child) { assert.ok(this.children.includes(child)); this.children = this.children.filter((item) => item !== child); this.removed.push(child); }
      setLocation(location) { this.locations.push(location); }
      destroy() { this.destroyCount++; this.children = []; }
    },
    YMapDefaultSchemeLayer: class {},
    YMapDefaultFeaturesLayer: class {},
    YMapMarker: class {
      constructor(options, element) { this.options = options; this.element = element; markers.push(this); }
    },
  };
  const window = preload ? { ymaps3: sdk } : {};
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => {
        if (!mounted) { lateUpdates++; return; }
        const next = typeof value === "function" ? value(hooks[index]) : value;
        if (!Object.is(next, hooks[index])) { hooks[index] = next; dirty = true; }
      }];
    },
    useRef(initial) { const index = cursor++; return hooks[index] ??= { current: initial }; },
    useEffect(effect, deps) {
      const index = cursor++, previous = hooks[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        hooks[index] = { deps, cleanup: previous?.cleanup };
        effects.push(() => { hooks[index].cleanup?.(); hooks[index].cleanup = effect(); });
      }
    },
  };
  const jsx = (type, props) => typeof type === "function" ? type(props) : { type, props };
  const imports = {
    react, "react/jsx-runtime": { jsx, jsxs: jsx },
    "../api": { api: { get(path) { calls.push(path); return Promise.resolve().then(() => get ? get(path) : { enabled: true, api_key: "mock-only", lang: "ru_RU" }); } } },
  };
  const context = vm.createContext({
    window, document, URLSearchParams, AbortController,
    setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, { callback, time: clock + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  function load(name) {
    const exports = {};
    const require = (path) => { assert.ok(path in imports, `Unexpected import ${path}`); return imports[path]; };
    const execute = vm.runInContext(`(function(exports, require) { ${compiled[name]}\n})`, context, { filename: `${name}.js` });
    execute(exports, require);
    return exports;
  }
  const loader = load("organizationMapSdk");
  imports["./organizationMapSdk"] = loader;
  const component = load("OrganizationMap");
  function nodes(value) {
    if (!value || typeof value !== "object") return [];
    if (Array.isArray(value)) return value.flatMap(nodes);
    return [value, ...nodes(value.props?.children)];
  }
  function text(value) {
    if (value == null || typeof value === "boolean") return "";
    if (Array.isArray(value)) return value.map(text).join("");
    return typeof value === "object" ? text(value.props?.children) : String(value);
  }
  return {
    maps, markers, calls, scripts, timers, window, sdk, loader,
    coordinatesOf: component.coordinatesOf,
    update(next) { props = { ...props, ...next }; dirty = true; },
    async flush() {
      for (let i = 0; i < 30; i++) {
        if (dirty && mounted) {
          dirty = false; cursor = 0; tree = component.default(props);
          for (const node of nodes(tree)) if (node.props?.ref) node.props.ref.current = container;
          while (effects.length) effects.shift()();
        }
        await setImmediate();
        if (!dirty && i > 2) return;
      }
      assert.fail("Map did not settle");
    },
    async advance(ms) {
      clock += ms;
      for (const [id, timer] of [...timers]) if (timer.time <= clock) { timers.delete(id); timer.callback(); }
      await this.flush();
    },
    loadScript(script = scripts.at(-1), api = sdk) { window.ymaps3 = api; script.dispatch("load"); },
    retry() {
      const retry = nodes(tree).find((node) => node.type === "button" && /Повторить/.test(text(node)));
      assert.ok(retry, `Retry missing: ${text(tree)}`);
      retry.props.onClick();
    },
    activeMarkers() { return maps.at(-1)?.children.filter((child) => child.element) ?? []; },
    text() { return text(tree); },
    isVisible() { return nodes(tree).some((node) => node.props?.className === "organization-map is-ready"); },
    unmount() {
      mounted = false;
      for (const hook of hooks) hook?.cleanup?.();
      for (const node of nodes(tree)) if (node.props?.ref) node.props.ref.current = null;
    },
    lateUpdates() { return lateUpdates; },
  };
}
