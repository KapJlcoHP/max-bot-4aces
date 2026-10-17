import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("profile exposes configurable step reminder leads", async () => {
  const profile = await readFile(resolve(webRoot, "src/pages/Profile.tsx"), "utf8");
  const types = await readFile(resolve(webRoot, "src/types.ts"), "utf8");

  for (const field of ["notify_day_before", "notify_hour_before", "notify_at_deadline"]) {
    assert.match(profile, new RegExp(field));
    assert.match(types, new RegExp(`${field}: boolean`));
  }
  assert.match(profile, /step_day_before_time/);
  assert.match(types, /step_day_before_time: string/);
  assert.match(profile, /type="time"/);
  assert.match(profile, /\/api\/v1\/me\/settings/);
  assert.match(profile, /За день до срока/);
  assert.match(profile, /За час до срока/);
  assert.match(profile, /В момент срока/);
});
