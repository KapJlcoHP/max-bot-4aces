import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("step card shows a plain-language instruction instead of a source reason", async () => {
  const stepCard = await readFile(resolve(webRoot, "src/pages/StepCard.tsx"), "utf8");

  assert.match(stepCard, /Простыми словами/);
  assert.match(stepCard, /toPlainInstruction/);
  assert.match(stepCard, /step\.description/);
  assert.match(stepCard, /simpleInstruction/);
  assert.doesNotMatch(stepCard, /Почему этот шаг появился/);
  assert.doesNotMatch(stepCard, /step\.reason/);
});
