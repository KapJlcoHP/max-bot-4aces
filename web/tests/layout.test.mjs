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
  assert.match(css, /@media \(min-width: 900px\)[\s\S]*\.screen-body\s*\{[^}]*var\(--desktop-tabbar-gap\)/);
  assert.match(css, /@media \(min-width: 900px\)[\s\S]*\.foot\s*\{[^}]*var\(--desktop-tabbar-gap\)/);
});

test("mobile add-step date and time fields can wrap without horizontal overlap", async () => {
  const css = await readFile(resolve(webRoot, "src/styles.css"), "utf8");

  assert.match(css, /\.step-date-time-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(0,\s*1fr\)/);
  assert.match(css, /\.step-time-field\s*\{[^}]*white-space:\s*normal/);
  assert.match(css, /\.own-row input, \.step-date-time-row input, \.step-schedule-date-row input\s*\{[^}]*box-sizing:\s*border-box;[^}]*min-width:\s*0/);
  assert.match(css, /\.own-row\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0/);
  assert.match(css, /\.own-row\s*>\s*\.step-date-time-row[^}]*flex:\s*0 1 100%[^}]*max-width:\s*100%/);
  assert.match(css, /\.route-add-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+46px/);
  assert.match(css, /\.route-add-row\s*>\s*\.step-date-time-row[^}]*grid-column:\s*1 \/ -1[^}]*grid-row:\s*2/);
  assert.match(css, /\.step-date-time-row input,[\s\S]*\.step-schedule-date-row input,[\s\S]*min-width:\s*0;[^}]*min-inline-size:\s*0;[^}]*inline-size:\s*100%/);
  assert.match(css, /\.step-schedule-date-row\s*\{[^}]*overflow:\s*hidden/);
});
