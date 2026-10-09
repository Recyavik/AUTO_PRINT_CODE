import { useEffect, useRef, useState } from "react";
import { blockTitle, codeNumber, type EngineState, PROFILES } from "../../shared/model.ts";
import { typingText } from "../../shared/textprint.ts";
import {
  closeTab, command, moveBlock, openTab, pauseHotkeys, shutdownHelper, updateSettings, useApp,
} from "./api.ts";
import { importFiles, Library, newTemplate } from "./components/Library.tsx";
import { SettingsDialog } from "./components/SettingsDialog.tsx";
import { TemplateView } from "./components/TemplateView.tsx";
import { sounds } from "./sound.ts";

const STATE: Record<EngineState, [string, string]> = {
  idle: ["Готов", "#3b82f6"],
  countdown: ["Отсчёт", "#a855f7"],
  running: ["Печать", "#2ea043"],
  paused: ["Пауза", "#d29922"],
  finished: ["Готово", "#3b82f6"],
};

/** Значок вкладки — логотип, полоса которого окрашена по состоянию (как значок Python-версии в трее). */
function faviconSvg(color: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
    `<rect x="2" y="2" width="60" height="60" rx="12" fill="#1e2229"/>` +
    `<rect x="2" y="50" width="60" height="12" rx="6" fill="${color}"/>` +
    `<text x="32" y="33" font-family="Consolas,monospace" font-size="22" font-weight="bold" text-anchor="middle" ` +
    `dominant-baseline="middle" fill="${color}">&lt;/&gt;</text></svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

// Установка страницы как приложения (Chrome/Edge): своё окно и свой значок в панели задач
type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let installEvent: InstallEvent | null = null;
const installListeners = new Set<() => void>();
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installEvent = e as InstallEvent;
  installListeners.forEach((l) => l());
});
window.addEventListener("appinstalled", () => {
  installEvent = null;
  installListeners.forEach((l) => l());
});

export function App() {
  const connected = useApp((s) => s.connected);
  const everConnected = useApp((s) => s.everConnected);
  const stopped = useApp((s) => s.stopped);
  const settings = useApp((s) => s.settings);
  const templates = useApp((s) => s.templates);
  const engine = useApp((s) => s.engine);
  const toasts = useApp((s) => s.toasts);
  const version = useApp((s) => s.version);
  const [showSettings, setShowSettings] = useState(false);
  const [soundLocked, setSoundLocked] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);
  const [canInstall, setCanInstall] = useState(!!installEvent);
  useEffect(() => {
    const l = () => setCanInstall(!!installEvent);
    installListeners.add(l);
    return () => { installListeners.delete(l); };
  }, []);

  const [stateText, stateColor] = STATE[engine.state];
  const busy = engine.state === "running" || engine.state === "countdown";

  // заголовок вкладки начинается с метки — по ней помощник узнаёт окно браузера со страницей
  useEffect(() => {
    document.title = `⌨ AutoPrintCode — ${engine.state === "countdown" && engine.countdown ? `старт через ${engine.countdown}` : stateText}`;
    (document.getElementById("favicon") as HTMLLinkElement | null)?.setAttribute("href", faviconSvg(stateColor));
  }, [stateText, engine.countdown]);

  // звук разрешается после первого действия на странице
  useEffect(() => {
    const unlock = () => { sounds.unlock(); setTimeout(() => setSoundLocked(sounds.locked), 100); };
    document.addEventListener("pointerdown", unlock);
    document.addEventListener("keydown", unlock);
    return () => { document.removeEventListener("pointerdown", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === "ArrowDown") { e.preventDefault(); moveBlock(+1); }
      else if (e.altKey && e.key === "ArrowUp") { e.preventDefault(); moveBlock(-1); }
      else if (e.ctrlKey && e.key === ",") { e.preventDefault(); setShowSettings(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!settings) return;
    pauseHotkeys(showSettings);
  }, [showSettings]);

  if (!settings) {
    return (
      <div className="app">
        <div className="banner">
          {everConnected ? "Связь с помощником потеряна — переподключаюсь…" : <>
            Помощник AutoPrintCode не запущен. Запустите <code>web\start.bat</code> (или <code>npm start</code> в папке web)
            — страница подключится сама.</>}
        </div>
      </div>
    );
  }

  const openTemplates = settings.open_tabs.map((id) => templates.find((t) => t.id === id)).filter((t) => !!t);
  const current = templates.find((t) => t.id === settings.current_tab);
  const armedBlock = current?.blocks.find((b) => b.id === current.active_block);

  let armedLabel: React.ReactNode = <span style={{ color: "var(--muted)" }}>Нет активного блока — щёлкните по блоку кода или текста</span>;
  if (current && armedBlock) {
    const [text, , part] = typingText(current, armedBlock, settings);
    armedLabel = <>Печатать: <b>{current.title}</b> · {blockTitle(armedBlock, codeNumber(current, armedBlock))} · {part} ({text ? text.split("\n").length : 0} стр., {text.length} симв.)</>;
  }

  return (
    <div className="app">
      {!connected && (
        <div className="banner">{stopped
          ? <>Помощник выключен. Чтобы печатать, запустите <code>web\start.bat</code> — страница подключится сама.</>
          : "Связь с помощником потеряна — переподключаюсь… Печать и сохранение недоступны."}</div>
      )}
      {connected && settings.sound_enabled && soundLocked && (
        <div className="banner info">Щёлкните в любом месте страницы, чтобы браузер разрешил звук клавиш.</div>
      )}

      <div className="toolbar">
        <button className="btn primary" disabled={!connected} onClick={() => command("toggle", true)}>
          {busy ? "⏸ Пауза" : engine.state === "paused" ? "▶ Продолжить" : "▶ Старт"}
        </button>
        <button className="btn" disabled={!connected} onClick={() => command("restart", true)}>⟲ Сначала</button>
        <button className="btn" disabled={!connected} onClick={() => command("stop")}>■ Стоп</button>
        <label htmlFor="profile">Окно:</label>
        <select id="profile" value={settings.profile} onChange={(e) => updateSettings({ profile: e.target.value })}>
          {Object.entries(PROFILES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label htmlFor="cpm">Скорость:</label>
        <input id="cpm" type="number" min={30} max={3000} step={20} value={settings.cpm}
          onChange={(e) => updateSettings({ cpm: Math.max(30, Math.min(3000, Number(e.target.value))) })} /> <span className="unit">симв/мин</span>
        <button className="btn toggle" aria-pressed={settings.strip_comments} title="Не печатать комментарии"
          onClick={() => updateSettings({ strip_comments: !settings.strip_comments })}>Без комментариев</button>
        <button className="btn toggle" aria-pressed={settings.human_typing} title="Имитация ручного ввода: ритм, паузы, опечатки"
          onClick={() => updateSettings({ human_typing: !settings.human_typing })}>Как человек</button>
        <button className="btn ghost" title="Звук клавиш" onClick={() => { sounds.unlock(); updateSettings({ sound_enabled: !settings.sound_enabled }); }}>
          {settings.sound_enabled ? "🔊" : "🔇"}
        </button>
        <input type="range" min={0} max={100} value={settings.sound_volume} disabled={!settings.sound_enabled}
          title={`Громкость клавиш: ${settings.sound_volume}%`} style={{ width: 110 }}
          onChange={(e) => updateSettings({ sound_volume: Number(e.target.value) })}
          onPointerUp={() => engine.state !== "running" && sounds.demo()} />
        <span className="spacer" />
        {canInstall && (
          <button className="btn" title="Своё окно и значок в панели задач; приложение можно закрепить"
            onClick={async () => { await installEvent?.prompt(); installEvent = null; setCanInstall(false); }}>⇓ Установить как приложение</button>
        )}
        <button className="btn" onClick={() => setShowSettings(true)} title="Настройки (Ctrl+,)">⚙ Настройки</button>
        <button className="btn ghost" title="Выключить помощника печати (хоткеи перестанут работать)"
          onClick={() => confirm("Выключить помощника AutoPrintCode? Печать и хоткеи перестанут работать до следующего запуска start.bat.")
            && shutdownHelper()}>⏻</button>
      </div>

      <div className="status">
        <span className="state" style={{ color: stateColor }}>● {engine.state === "countdown" && engine.countdown ? `Старт через ${engine.countdown}…` : stateText}</span>
        <span className="armed">{armedLabel}</span>
        <div className="progress" title={`${engine.pos} из ${engine.total}`}>
          <div style={{ width: `${engine.total ? (100 * engine.pos) / engine.total : 0}%` }} />
        </div>
        <span className="hint">{settings.hotkey_toggle || "—"} — старт/пауза · {settings.hotkey_restart || "—"} — сначала · {settings.hotkey_stop || "—"} — стоп</span>
      </div>

      <div className="main">
        <Library fileInput={fileInput} />
        <section className="workspace">
          <nav className="tabs">
            {openTemplates.map((t) => (
              <div key={t.id} className={`tab${t.id === settings.current_tab ? " current" : ""}`} onClick={() => openTab(t.id)}
                onAuxClick={(e) => e.button === 1 && closeTab(t.id)} title={t.title}>
                <span>{t.title}</span>
                <button className="x" title="Закрыть вкладку" onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}>✕</button>
              </div>
            ))}
          </nav>
          {current ? <TemplateView key={current.id} template={current} /> : (
            <div className="empty">
              <p>Откройте образец слева или создайте новый.</p>
              <p>
                <button className="btn" onClick={newTemplate}>＋ Новый образец</button>{" "}
                <button className="btn" onClick={() => fileInput.current?.click()}>⇪ Импорт .ipynb / .md / .py</button>
              </p>
              <p className="hint">Щёлкните по блоку кода или текста — он станет активным. Поставьте курсор в нужном окне
                (Блокнот, VS Code, Jupyter) и нажмите <b>{settings.hotkey_toggle}</b>.</p>
              <p style={{ fontSize: 12 }}>AutoPrintCode {version}</p>
            </div>
          )}
        </section>
      </div>

      <input ref={fileInput} type="file" hidden multiple accept=".ipynb,.md,.markdown,.py,.json"
        onChange={(e) => { if (e.target.files) void importFiles(e.target.files); e.target.value = ""; }} />
      {showSettings && <SettingsDialog settings={settings} onSave={updateSettings} onClose={() => setShowSettings(false)} />}
      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.level}`}>{t.text}</div>)}
      </div>
    </div>
  );
}
