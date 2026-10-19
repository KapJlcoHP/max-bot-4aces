import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("FAQ page loads the API and exposes an accessible accordion with retry", async () => {
  const page = await readFile(resolve(webRoot, "src/pages/Faq.tsx"), "utf8");
  const routes = await readFile(resolve(webRoot, "src/main.tsx"), "utf8");
  const profile = await readFile(resolve(webRoot, "src/pages/Profile.tsx"), "utf8");
  const types = await readFile(resolve(webRoot, "src/types.ts"), "utf8");

  assert.match(page, /\/api\/v1\/faq/);
  assert.match(page, /<details className="faq-item"/);
  assert.match(page, /<summary>/);
  assert.match(page, /ErrorView onRetry=\{load\}/);
  assert.match(page, /LoadingView/);
  assert.match(routes, /path="faq" element=\{<Faq \/>\}/);
  assert.match(profile, /title="Частые вопросы"/);
  assert.match(profile, /nav\("\/faq"\)/);
  assert.match(types, /interface FaqItem/);
  assert.match(types, /category: string/);
});
