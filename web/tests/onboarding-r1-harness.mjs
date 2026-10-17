import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import vm from "node:vm";
import ts from "typescript";

const source = await readFile(new URL("../src/pages/Onboarding.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// A small hook/JSX runner for the actual page, using the project's TypeScript
// dependency. It exercises state, effects and event handlers, not DOM rendering.
// All imports with network, app-context or browser behavior are replaced here.
export function onboardingHarness({ user = {}, get, post } = {}) {
  const hooks = [];
  const effects = [];
  const calls = [];
  const savedUsers = [];
  let cursor = 0;
  let dirty = true;
  let tree;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (value) => {
        hooks[index] = typeof value === "function" ? value(hooks[index]) : value;
        dirty = true;
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = { current: initial };
      return hooks[index];
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      const previous = hooks[index];
      hooks[index] = dependencies;
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous[i]))) effects.push(effect);
    },
  };
  const jsx = (type, props) => ({ type, props });
  const imports = {
    react,
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "Fragment" },
    "../api": { api: {
      get: (path) => {
        calls.push({ method: "GET", path });
        return Promise.resolve().then(() => get(path));
      },
      post: (path, payload) => {
        calls.push({ method: "POST", path, payload });
        return Promise.resolve().then(() => post(path, payload));
      },
    } },
    "../App": { useApp: () => ({ user, updateUser: (saved) => savedUsers.push(saved) }) },
    "../components/ui": { Button: "Button", Switch: "Switch" },
    "../icons": { I: new Proxy({}, { get: (_, name) => `icon:${String(name)}` }) },
    "@maxhub/max-ui": { Input: "Input" },
    "../components/OrganizationMap": { default: "OrganizationMap" },
  };
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, URLSearchParams, Intl,
    require(name) {
      assert.ok(name in imports, `Unexpected import: ${name}`);
      return imports[name];
    },
  }, { filename: "Onboarding.js" });

  function render() {
    dirty = false;
    cursor = 0;
    tree = exports.default();
    while (effects.length) effects.shift()();
  }
  function nodes(value) {
    if (!value || typeof value !== "object") return [];
    if (Array.isArray(value)) return value.flatMap((child) => nodes(child));
    return [value, ...nodes(value.props?.children)];
  }
  function text(value) {
    if (value == null || typeof value === "boolean") return "";
    if (Array.isArray(value)) return value.map(text).join("");
    return typeof value === "object" ? text(value.props?.children) : String(value);
  }
  function find(predicate) {
    const node = nodes(tree).find(predicate);
    assert.ok(node, `Control not found in: ${text(tree)}`);
    return node;
  }

  return {
    calls, savedUsers,
    async flush() {
      for (let i = 0; i < 20; i++) {
        if (dirty) render();
        await setImmediate();
        if (!dirty) return;
      }
      assert.fail("Onboarding did not settle");
    },
    button(label) { return find((node) => node.type === "Button" && text(node) === label); },
    click(label) {
      const button = this.button(label);
      assert.ok(!button.props.disabled, `Button disabled: ${label}`);
      return button.props.onClick();
    },
    change(label, value) {
      find((node) => node.props?.["aria-label"] === label).props.onChange({ target: { value } });
    },
    agree() { find((node) => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } }); },
    toggle(label, on) { find((node) => node.type === "Switch" && node.props.label === label).props.onChange(on); },
    alerts() { return nodes(tree).filter((node) => node.props?.role === "alert").map(text); },
    text() { return text(tree); },
  };
}
