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
  const hooks = [], effects = [], calls = [], savedUsers = [], navigation = [], toasts = [], jumps = [];
  const timers = new Map();
  let currentUser = user, currentOrgId = orgId, currentSearch = search, cursor = 0, dirty = true, tree, clock = 0, nextTimer = 0;
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
    useMemo(factory, deps) {
      const index = cursor++, previous = hooks[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) hooks[index] = { deps, value: factory() };
      return hooks[index].value;
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
    if (path.startsWith("/api/v1/orgs?")) {
      const params = new URLSearchParams(path.split("?")[1]);
      const region = params.has("region") ? params.get("region") : currentUser.region;
      const type = params.get("org_type"), q = params.get("q")?.toLocaleLowerCase("ru");
      return orgs.filter((org) => (!region || region === "Все" || org.region === region)
        && (!type || type === "Все" || org.org_type === type)
        && (!q || `${org.title} ${org.address}`.toLocaleLowerCase("ru").includes(q)));
    }
    if (path.startsWith("/api/v1/orgs/")) {
      const found = orgs.find((org) => org.id === Number(path.split("/").at(-1)));
      if (!found) throw new ApiError(404);
      return found;
    }
    assert.fail(`Unexpected GET ${path}`);
  };
  const network = (method, handler) => (path, payload) => {
    calls.push({ method, path, payload });
    return Promise.resolve().then(() => handler(path, payload));
  };
  const imports = {
    react, "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-router-dom": { useNavigate: () => (path) => navigation.push(path), useLocation: () => ({ search: currentSearch }), useParams: () => ({ orgId: currentOrgId === undefined ? undefined : String(currentOrgId) }) },
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
      exports, URLSearchParams,
      window: {
        setTimeout(callback, delay = 0) { const id = ++nextTimer; timers.set(id, { callback, at: clock + delay }); return id; },
        clearTimeout(id) { timers.delete(id); },
      },
      document: { getElementById: (id) => ({ scrollIntoView: () => jumps.push({ id, action: "scroll" }), focus: () => jumps.push({ id, action: "focus" }) }) },
      require(path) { assert.ok(path in imports, `Unexpected import ${path}`); return imports[path]; },
    }, { filename: `${name}.js` });
    return exports;
  }
  imports["../components/ClinicChoice"] = load("ClinicChoice");
  imports["./Orgs"] = load("Orgs");
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
    calls, savedUsers, navigation, toasts, jumps,
    async flush() {
      for (let i = 0; i < 25; i++) {
        if (dirty) {
          dirty = false; cursor = 0; tree = component();
          while (effects.length) effects.shift()();
        }
        for (const [id, timer] of timers) {
          if (timer.at <= clock) { timers.delete(id); timer.callback(); }
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
    nodes(predicate = () => true) { return nodes(tree).filter(predicate); },
    async advance(ms) { clock += ms; await this.flush(); },
    route(nextOrgId, nextSearch = currentSearch) { currentOrgId = nextOrgId; currentSearch = nextSearch; dirty = true; },
    unmount() { for (const hook of hooks) hook?.cleanup?.(); },
    text() { return text(tree); },
    user() { return currentUser; },
    mutations() { return calls.filter((call) => call.method !== "GET"); },
  };
}
