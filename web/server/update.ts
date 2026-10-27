// Обновления веб-версии из GitHub Releases. Релиз — общий с настольной AutoPrintCode (тег vX.Y.Z, версии
// совпадают); к нему приложен установщик веб-версии autoprintcode-web-update-X.Y.Z.exe. Помощник находит
// его, скачивает и запускает тихо: установщик закрывает помощника, ставит новую версию и запускает её снова.
// Ставить обновление умеет только установленная копия (папка с unins000.exe); из исходников — git pull.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { log } from "./log.ts";
import { DATA_DIR, WEB_DIR } from "./store.ts";

const API = "https://api.github.com/repos/Recyavik/AUTO_PRINT_CODE/releases?per_page=30";
const ASSET = /^autoprintcode-web-update-(\d+(?:\.\d+)*)\.exe$/i;

export interface UpdateInfo {
  current: string;
  latest: string | null;   // версия новее текущей или null
  notes: string;
  installed: boolean;      // копия установлена мастером — обновление ставится кнопкой
  error?: string;
}

interface Found { version: string; url: string; notes: string }
let found: Found | null = null;

const key = (v: string) => v.split(".").map((x) => Number.parseInt(x, 10) || 0);
export function isNewer(v: string, current: string): boolean {
  const [a, b] = [key(v), key(current)];
  for (let i = 0; i < Math.max(a.length, b.length); i++) if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  return false;
}

export const installedCopy = (): boolean => fs.existsSync(path.join(WEB_DIR, "unins000.exe"));

/** Самый новый релиз с установщиком веб-версии (черновики и пре-релизы — мимо). */
export function pickLatest(releases: { tag_name?: string; draft?: boolean; prerelease?: boolean; body?: string;
  assets?: { name?: string; browser_download_url?: string }[] }[]): Found | null {
  let best: Found | null = null;
  for (const r of releases) {
    // опечатка в имени тега при создании релиза: «v.0.6.8», «v-0.6.8» — номер тот же
    const m = /^v[.\-_ ]?(\d.*)$/i.exec(r.tag_name ?? "");
    if (r.draft || r.prerelease || !m) continue;
    const asset = (r.assets ?? []).find((a) => ASSET.test(a.name ?? ""));
    if (!asset?.browser_download_url) continue;
    const version = m[1];
    if (!best || isNewer(version, best.version)) best = { version, url: asset.browser_download_url, notes: r.body ?? "" };
  }
  return best;
}

export async function checkUpdate(current: string): Promise<UpdateInfo> {
  const installed = installedCopy();
  try {
    const res = await fetch(API, { headers: { Accept: "application/vnd.github+json", "User-Agent": `AutoPrintCode-web/${current}` },
      signal: AbortSignal.timeout(15000) });
    if (!res.ok) throw new Error(`GitHub ответил ${res.status}`);
    found = pickLatest(await res.json() as Parameters<typeof pickLatest>[0]);
  } catch (e) {
    return { current, latest: null, notes: "", installed, error: (e as Error).message };
  }
  const newer = found && isNewer(found.version, current) ? found : null;
  return { current, latest: newer?.version ?? null, notes: newer?.notes ?? "", installed };
}

/** Скачать установщик и запустить его тихо (через 2 с — помощник успеет завершиться). */
export async function installUpdate(): Promise<void> {
  if (!found) throw new Error("Сначала проверьте обновления");
  if (!installedCopy()) throw new Error("Эта копия запущена из исходников — обновите её через git pull");
  const dir = path.join(DATA_DIR, "updates");
  fs.mkdirSync(dir, { recursive: true });
  const dest = path.join(dir, `autoprintcode-web-update-${found.version}.exe`);
  const res = await fetch(found.url, { signal: AbortSignal.timeout(600000) });
  if (!res.ok || !res.body) throw new Error(`Не удалось скачать обновление: ${res.status}`);
  fs.writeFileSync(dest, Buffer.from(await res.arrayBuffer()));
  log("info", `Скачано обновление ${found.version}: ${dest}`);
  const cmd = `timeout /t 2 /nobreak >nul & "${dest}" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS`;
  spawn("cmd.exe", ["/d", "/s", "/c", `"${cmd}"`], { detached: true, stdio: "ignore", windowsHide: true,
    windowsVerbatimArguments: true }).unref();
}
