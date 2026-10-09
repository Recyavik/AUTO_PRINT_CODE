// Хранилище: settings.json и templates.json в web/data/ — тот же формат, что у Python-версии.
// При первом запуске копируются образцы и настройки Python-версии (../data), если они есть.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  mergeSettings, sampleTemplate, type Settings, type Template, templateFrom,
} from "../shared/model.ts";

export const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const DATA_DIR = path.resolve(process.env.AUTOPRINT_DATA || path.join(WEB_DIR, "data"));
const PY_DATA_DIR = path.resolve(WEB_DIR, "..", "data");
const SETTINGS_FILE = path.join(DATA_DIR, "settings.json");
const TEMPLATES_FILE = path.join(DATA_DIR, "templates.json");
const TEMPLATES_BAK = TEMPLATES_FILE + ".bak";
const BACKUP_EVERY_MS = 10 * 60 * 1000;   // резервная копия — не чаще раза в 10 минут: есть куда откатиться

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** Переименование с повтором: антивирус, OneDrive или индексатор ненадолго держат файл (EPERM/EBUSY). */
function renameRetry(from: string, to: string): void {
  for (let i = 0; ; i++) {
    try {
      fs.renameSync(from, to);
      return;
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code;
      if (i >= 9 || (code !== "EPERM" && code !== "EBUSY" && code !== "EACCES")) throw e;
      sleepSync(50 * (i + 1));
    }
  }
}

/** Запись через временный файл: на диске остаётся либо старая, либо новая версия.
 *  backup — перед записью скопировать текущий файл в .bak (если копия старше BACKUP_EVERY_MS). */
function atomicWrite(file: string, data: unknown, backup = false): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + ".tmp";
  const fd = fs.openSync(tmp, "w");
  try {
    fs.writeSync(fd, JSON.stringify(data, null, 2));
    fs.fsyncSync(fd);   // иначе после сбоя питания файл может оказаться пустым
  } finally {
    fs.closeSync(fd);
  }
  if (backup && fs.existsSync(file)) {
    const bak = file + ".bak";
    try {
      if (!fs.existsSync(bak) || Date.now() - fs.statSync(bak).mtimeMs > BACKUP_EVERY_MS) fs.copyFileSync(file, bak);
    } catch {
      // без свежей копии — не повод не сохранить сами данные
    }
  }
  renameRetry(tmp, file);
}

function readJson(file: string): Record<string, unknown> | null {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf-8").replace(/^\uFEFF/, ""));
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("ожидался объект JSON");
    return raw;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new Error(`Не удалось прочитать ${file}: ${(e as Error).message}`);
  }
}

function readTemplates(file: string): Template[] | null {
  const raw = readJson(file);
  if (raw === null) return null;
  const list = raw.templates ?? [];
  if (!Array.isArray(list) || list.some((t) => !t || typeof t !== "object")) {
    throw new Error(`Не удалось прочитать ${file}: неверная структура`);
  }
  return list.map(templateFrom);
}

/** Первый запуск: забрать данные Python-версии (копия — исходные файлы не меняются). */
function adoptPythonData(): string {
  if (process.env.AUTOPRINT_DATA || fs.existsSync(TEMPLATES_FILE)) return "";
  const src = path.join(PY_DATA_DIR, "templates.json");
  if (!fs.existsSync(src)) return "";
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.copyFileSync(src, TEMPLATES_FILE);
  const st = path.join(PY_DATA_DIR, "settings.json");
  if (fs.existsSync(st) && !fs.existsSync(SETTINGS_FILE)) fs.copyFileSync(st, SETTINGS_FILE);
  return src;
}

export class Store {
  settings: Settings;
  templates: Template[];
  readonly adoptedFrom: string;
  /** Что пошло не так при загрузке (показать на странице). */
  warning = "";
  /** Ошибка отложенного сохранения — помощник не падает, а сообщает. */
  onSaveError: (text: string) => void = () => {};
  private saveTimer: NodeJS.Timeout | null = null;
  private settingsTimer: NodeJS.Timeout | null = null;

  constructor() {
    this.adoptedFrom = adoptPythonData();
    let settings: Record<string, unknown> = {};
    try {
      settings = readJson(SETTINGS_FILE) ?? {};
    } catch {
      // испорченные настройки — по умолчанию; файл перезапишется при первом изменении
    }
    this.settings = mergeSettings(settings);
    this.templates = this.loadTemplates();
  }

  private loadTemplates(): Template[] {
    let why: string;
    try {
      const list = readTemplates(TEMPLATES_FILE);
      if (list) return list;
      if (!fs.existsSync(TEMPLATES_BAK)) {
        const sample = [sampleTemplate()];
        this.templates = sample;
        this.saveTemplatesNow();
        return sample;
      }
      why = "templates.json не найден";
    } catch (e) {
      if (!fs.existsSync(TEMPLATES_BAK)) throw e;
      why = `templates.json повреждён (${(e as Error).message})`;
    }
    // основной файл не читается — берём резервную копию, испорченный файл откладываем
    const list = readTemplates(TEMPLATES_BAK);
    if (!list) throw new Error(`${why}, резервной копии нет`);
    if (fs.existsSync(TEMPLATES_FILE)) {
      const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
      let broken = path.join(DATA_DIR, `templates.broken-${stamp}.json`);
      for (let n = 2; fs.existsSync(broken); n++) broken = path.join(DATA_DIR, `templates.broken-${stamp}-${n}.json`);
      fs.renameSync(TEMPLATES_FILE, broken);
      why += `; он сохранён как ${path.basename(broken)}`;
    }
    fs.copyFileSync(TEMPLATES_BAK, TEMPLATES_FILE);
    this.warning = `${why}. Образцы восстановлены из резервной копии templates.json.bak.`;
    return list;
  }

  get(id: string): Template | undefined {
    return this.templates.find((t) => t.id === id);
  }

  put(t: Template): void {
    const i = this.templates.findIndex((x) => x.id === t.id);
    if (i >= 0) this.templates[i] = t;
    else this.templates.push(t);
    this.saveTemplates();
  }

  remove(id: string): void {
    this.templates = this.templates.filter((t) => t.id !== id);
    this.saveTemplates();
  }

  /** Сохранение настроек с задержкой: ползунок громкости и поле скорости меняются шаг за шагом. */
  saveSettings(): void {
    if (this.settingsTimer) clearTimeout(this.settingsTimer);
    this.settingsTimer = setTimeout(() => this.saveSettingsNow(), 500);
  }

  saveSettingsNow(): void {
    if (this.settingsTimer) clearTimeout(this.settingsTimer);
    this.settingsTimer = null;
    this.guard("настройки", () => atomicWrite(SETTINGS_FILE, this.settings));
  }

  /** Сохранение с задержкой: правки в редакторе идут потоком. */
  saveTemplates(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.saveTemplatesNow(), 700);
  }

  saveTemplatesNow(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = null;
    this.guard("образцы", () => atomicWrite(TEMPLATES_FILE, { version: 3, templates: this.templates }, true));
  }

  /** Всё несохранённое — на диск сейчас (выход, сбой). */
  flush(): void {
    if (this.settingsTimer) this.saveSettingsNow();
    if (this.saveTimer) this.saveTemplatesNow();
  }

  private guard(what: string, write: () => void): void {
    try {
      write();
    } catch (e) {
      this.onSaveError(`Не удалось сохранить ${what}: ${(e as Error).message}. Повторю при следующем изменении.`);
    }
  }
}
