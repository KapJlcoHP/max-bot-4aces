import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";
import ts from "typescript";

const files = ["components/StepScheduleEditor.tsx", "components/EventDateTimeInputs.tsx", "stepReminderTime.ts", "pages/StepCard.tsx", "pages/RoutePage.tsx", "pages/Builder.tsx"];
const compiled = Object.fromEntries(await Promise.all(files.map(async (file) => [file, ts.transpileModule(await readFile(new URL(`../src/${file}`, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText])));

// As in onboarding-r1: exercise actual TSX hook state and handlers without a
// browser/network. Stateless date inputs are expanded from their real source.
export function reminderHarness(file, { props = {}, user = {}, params = {}, api = {} } = {}) {
  const hooks = [], effects = [], calls = [], navigation = [], saved = [], toasts = [];
  let cursor = 0, dirty = true, tree;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => { hooks[index] = typeof value === "function" ? value(hooks[index]) : value; dirty = true; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = { current: initial };
      return hooks[index];
    },
    useEffect(effect, dependencies = []) {
      const index = cursor++, previous = hooks[index];
      hooks[index] = dependencies;
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous[i]))) effects.push(effect);
    },
    useMemo(compute, dependencies) {
      const index = cursor++, previous = hooks[index];
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) hooks[index] = { dependencies, value: compute() };
      return hooks[index].value;
    },
    useCallback(fn, dependencies) { return react.useMemo(() => fn, dependencies); },
  };
  const jsx = (type, props) => {
    if (typeof type === "function") return type(props);
    if (type === "Sheet" && !props.open) return null;
    return { type, props };
  };
  const ui = Object.fromEntries(["Button", "Sheet", "ErrorView", "Header", "LoadingView", "StateView", "Switch"].map((key) => [key, key]));
  const apiMock = Object.fromEntries(["get", "post", "patch", "del"].map((method) => [method, (path, payload) => {
    calls.push({ method, path, payload });
    return Promise.resolve().then(() => {
      assert.ok(api[method], `Unexpected ${method} ${path}`);
      return api[method](path, payload);
    });
  }]));
  const imports = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "react-router-dom": { useNavigate: () => (path) => navigation.push(path), useParams: () => params },
    "../api": { api: apiMock },
    "../App": { useApp: () => ({ user }) },
    "../hooks/useNow": { useNow: () => new Date("2030-01-02T10:00:00Z") },
    "../components/StepCountdown": { default: "StepCountdown" },
    "../components/StepScheduleEditor": { default: "StepScheduleEditor" },
    "../bridge": { openExternalLink() {} },
    "../format": { fmtDeadline: (date, time) => `${date} ${time ?? ""}`, fmtDateNumeric: (value) => value, fmtDayMonth: (value) => value },
    "../icons": { I: new Proxy({}, { get: (_, name) => `icon:${String(name)}` }), SituationIcon: "SituationIcon" },
    "@maxhub/max-ui": { Radio: "Radio" },
    "../components/ui": { ...ui, useToast: () => [null, (message) => toasts.push(message)] },
    "./ui": ui,
  };
  function load(source) {
    const exports = {};
    vm.runInNewContext(compiled[source], { exports, Date, Intl, Error, require(name) {
      assert.ok(name in imports, `Unexpected import ${name} in ${source}`);
      return imports[name];
    } }, { filename: source });
    return exports;
  }
  imports["../stepReminderTime"] = load("stepReminderTime.ts");
  imports["./EventDateTimeInputs"] = imports["../components/EventDateTimeInputs"] = load("components/EventDateTimeInputs.tsx");
  const component = load(file).default;
  let currentProps = { ...props, user, now: new Date("2030-01-02T10:00:00Z"), onSaved: (step) => { saved.push(step); currentProps = { ...currentProps, step }; dirty = true; } };
  function render() {
    dirty = false; cursor = 0;
    tree = component(currentProps);
    while (effects.length) effects.shift()();
  }
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
  function find(predicate) {
    const node = nodes(tree).find(predicate);
    assert.ok(node, `Control not found: ${text(tree)}`);
    return node;
  }
  return {
    calls, navigation, saved, toasts, find,
    async flush() {
      for (let i = 0; i < 25; i++) {
        if (dirty) render();
        await setImmediate();
        if (!dirty) return;
      }
      assert.fail("Component did not settle");
    },
    input(label) { return find((node) => node.props?.["aria-label"] === label); },
    change(label, value) { this.input(label).props.onChange({ target: { value } }); },
    button(label) { return find((node) => (node.type === "Button" || node.type === "button") && text(node).trim() === label); },
    click(label) { const node = this.button(label); assert.ok(!node.props.disabled, `Disabled ${label}`); return node.props.onClick(); },
    radio(label) { find((node) => node.type === "label" && text(node).trim() === label).props.children[0].props.onChange(); },
    confirm() { find((node) => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } }); },
    all() { return nodes(tree); },
    text() { return text(tree); },
  };
}
