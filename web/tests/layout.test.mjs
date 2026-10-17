import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("desktop route shell keeps page app outside the inner screen scroll context", async () => {
  const app = await readFile(resolve(webRoot, "src/App.tsx"), "utf8");
  const css = await readFile(resolve(webRoot, "src/styles.css"), "utf8");

  assert.match(app, /<div className="app-layout">[\s\S]*<Outlet \/>/);
  assert.match(css, /\.app-layout\s*\{[^}]*min-height:\s*100%/);
  assert.match(css, /@media \(min-width: 900px\)[\s\S]*\.header\s*\{[^}]*background:\s*var\(--bg\)/);
});
