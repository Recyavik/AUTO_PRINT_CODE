// Печать текстовых блоков совпадает с Python-версией (autoprint/textprint.py).
// Эталон — tests/fixtures/textprint-reference.json, получен из Python на тех же текстах.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { BLOCK_CODE, BLOCK_MARKDOWN, DEFAULT_SETTINGS, makeBlock, makeTemplate, navBlocks } from "../shared/model.ts";
import { printable, typingText } from "../shared/textprint.ts";

const ref = JSON.parse(fs.readFileSync(new URL("./fixtures/textprint-reference.json", import.meta.url), "utf-8"));

test("printable = textprint.printable", () => {
  for (const c of ref) assert.equal(printable(c.text, c.mode, c.lang), c.out, `${c.mode}/${c.lang}: ${JSON.stringify(c.text.slice(0, 40))}`);
});

test("текстовый блок: язык комментария — от блока кода ниже, затем выше", () => {
  const md = makeBlock(BLOCK_MARKDOWN, "## Условие\n\nСложите `a` и `b`.", { print_as: "comment" });
  const js = makeBlock(BLOCK_CODE, "a + b", { lang: "javascript" });
  const py = makeBlock(BLOCK_CODE, "a + b", { lang: "python" });
  assert.deepEqual(typingText(makeTemplate("t", [py, md, js]), md, DEFAULT_SETTINGS),
    ["// Условие\n//\n// Сложите a и b.", 0, "текст комментарием (javascript)"]);
  assert.equal(typingText(makeTemplate("t", [py, md]), md, DEFAULT_SETTINGS)[0], "# Условие\n#\n# Сложите a и b.");
  // «без комментариев» к тексту не применяется
  assert.equal(typingText(makeTemplate("t", [md, py]), md, { ...DEFAULT_SETTINGS, strip_comments: true })[0],
    "# Условие\n#\n# Сложите a и b.");
});

test("переходы по блокам: из активного текста — в код под ним", () => {
  const c1 = makeBlock(BLOCK_CODE, "1");
  const md = makeBlock(BLOCK_MARKDOWN, "текст");
  const c2 = makeBlock(BLOCK_CODE, "2");
  const t = makeTemplate("t", [c1, md, c2]);
  assert.deepEqual(navBlocks(t).map((b) => b.text), ["1", "2"]);
  t.active_block = md.id;
  assert.deepEqual(navBlocks(t).map((b) => b.text), ["1", "текст", "2"]);
});
