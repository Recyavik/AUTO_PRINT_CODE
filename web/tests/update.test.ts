// Обновления веб-версии: выбор релиза с установщиком — без сети.
import assert from "node:assert/strict";
import { test } from "node:test";
import { isNewer, pickLatest } from "../server/update.ts";

const asset = (v: string) => ({ name: `autoprintcode-web-update-${v}.exe`, browser_download_url: `https://x/${v}.exe` });

test("версии сравниваются по числам", () => {
  assert.ok(isNewer("0.10.0", "0.9.3"));
  assert.ok(!isNewer("0.6.6", "0.6.6"));
  assert.ok(isNewer("0.6.7", "0.6.6"));
});

test("берётся самый новый релиз AutoPrintCode с установщиком веб-версии", () => {
  const found = pickLatest([
    { tag_name: "webinar-v9.0.0", assets: [asset("9.0.0")] },              // таймер — мимо
    { tag_name: "v0.9.0", draft: true, assets: [asset("0.9.0")] },         // черновик — мимо
    { tag_name: "v0.8.0", assets: [{ name: "autoprintcode-update-0.8.0.exe" }] },   // только настольная — мимо
    { tag_name: "v0.7.0", body: "Новое", assets: [asset("0.7.0")] },
    { tag_name: "v0.6.9", assets: [asset("0.6.9")] },
  ]);
  assert.deepEqual(found, { version: "0.7.0", url: "https://x/0.7.0.exe", notes: "Новое" });
  assert.equal(pickLatest([{ tag_name: "v0.6.3" }]), null);
});
