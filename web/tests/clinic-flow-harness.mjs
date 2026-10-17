import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";
import ts from "typescript";

const compiled = {};
for (const name of ["Orgs", "OrgDetail", "Profile", "ClinicChoice"]) {
  const folder = name === "ClinicChoice" ? "components" : "pages";
  const source = await readFile(new URL(`../src/${folder}/${name}.tsx`, import.meta.url), "utf8");
  compiled[name] = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
}

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export class ApiError extends Error {
  constructor(status) { super(`HTTP ${status}`); this.status = status; }
}

// Runs the real clinic hook and page event handlers, without network/browser APIs.
export function clinicHarness({ page = "Orgs", user, orgs = [], search = "", orgId, get, post, patch } = {}) {
  const hooks = [], effects = [], calls = [], savedUsers = [], navigation = [], toasts = [];
  let currentUser = user, cursor = 0, dirty = true, tree;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => { hooks[index] = typeof value === "function" ? value(hooks[index]) : value; dirty = true; }];
    },
    useRef(initial) { const index = cursor++; return hooks[index] ??= { current: initial }; },
    useEffect(effect, deps) {
      const index = cursor++, previous = hooks[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        hooks[index] = { deps, cleanup: previous?.cleanup };
        effects.push(() => { hooks[index].cleanup?.(); hooks[index].cleanup = effect(); });
      }
    },
    useCallback(callback, deps) {
      const index = cursor++, previous = hooks[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) hooks[index] = { deps, callback };
      return hooks[index].callback;
    },
  };
  const jsx = (type, props) => {
    if (typeof type === "function") return type(props);
    if (type === "Sheet" && !props.open) return null;
    if (type === "CellSimple") props = { ...props, children: [props.title, props.subtitle, props.after] };
    return { type, props };
  };
  const updateUser = (saved) => { savedUsers.push(saved); currentUser = saved; dirty = true; };
  const defaultGet = (path) => {
    if (path === "/api/v1/me") return currentUser;
    if (path === "/api/v1/regions") return [{ key: "one", title: "Ивановская область" }, { key: "two", title: "Владимирская область" }];
    if (path.startsWith("/api/v1/orgs?")) return orgs;
    if (path.startsWith("/api/v1/orgs/")) return orgs.find((org) => org.id === Number(path.split("/").at(-1)));
    assert.fail(`Unexpected GET ${path}`);
  };
  const network = (method, handler) => (path, payload) => {
    calls.push({ method, path, payload });
    return Promise.resolve().then(() => handler(path, payload));
  };
  const imports = {
    react, "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-router-dom": { useNavigate: () => (path) => navigation.push(path), useLocation: () => ({ search }), useParams: () => ({ orgId: String(orgId) }) },
    "../api": { api: { get: network("GET", get ?? defaultGet), post: network("POST", post ?? (() => assert.fail("Unexpected POST"))), patch: network("PATCH", patch ?? (() => assert.fail("Unexpected PATCH"))) }, ApiError },
    "../App": { useApp: () => ({ user: currentUser, updateUser, refreshUser: async () => updateUser(await (get ?? defaultGet)("/api/v1/me")) }) },
    "../bridge": { openExternalLink: (url) => navigation.push(url) },
    "../format": { fmtDayMonth: () => "" },
    "../icons": { I: new Proxy({}, { get: (_, name) => `icon:${String(name)}` }) },
    "@maxhub/max-ui": { Input: "Input", CellSimple: "CellSimple", CellList: "CellList", Radio: "Radio" },
    "../components/OrganizationMap": { default: "OrganizationMap" },
  };
  imports["./ui"] = imports["../components/ui"] = {
    Button: "Button", Header: "Header", LoadingView: "LoadingView", Sheet: "Sheet", Switch: "Switch", UserAvatar: "UserAvatar", useToast: () => [null, (message) => toasts.push(message)],
  };
  function load(name) {
    const exports = {};
    vm.runInNewContext(compiled[name], {
      exports, URLSearchParams, window: { setTimeout, clearTimeout },
      require(path) { assert.ok(path in imports, `Unexpected import ${path}`); return imports[path]; },
    }, { filename: `${name}.js` });
    return exports;
  }
  imports["../components/ClinicChoice"] = load("ClinicChoice");
  const component = load(page).default;
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
  const find = (predicate) => { const node = nodes(tree).find(predicate); assert.ok(node, `Control not found in: ${text(tree)}`); return node; };
  return {
    calls, savedUsers, navigation, toasts,
    async flush() {
      for (let i = 0; i < 25; i++) {
        if (dirty) {
          dirty = false; cursor = 0; tree = component();
          while (effects.length) effects.shift()();
        }
        await setImmediate();
        await new Promise((resolve) => setTimeout(resolve, 1));
        if (!dirty && i > 1) return;
      }
      assert.fail("Clinic flow did not settle");
    },
    button(label) { return find((node) => node.type === "Button" && text(node) === label); },
    click(label) { const button = this.button(label); assert.ok(!button.props.disabled); return button.props.onClick({ stopPropagation() {} }); },
    cell(title) { return find((node) => node.type === "CellSimple" && node.props.title === title); },
    node: find,
    text() { return text(tree); },
    user() { return currentUser; },
    mutations() { return calls.filter((call) => call.method !== "GET"); },
  };
}
