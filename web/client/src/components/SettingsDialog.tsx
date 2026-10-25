// Настройки — те же вкладки и поля, что у Python-версии.
import { useState } from "react";
import { hotkeyFromEvent, parseHotkey } from "../../../shared/hotkeys.ts";
import { HOTKEYS, PROFILES, type Settings, SOUND_STYLES } from "../../../shared/model.ts";
import { setAutostart, useApp } from "../api.ts";
import { sounds } from "../sound.ts";
import { NumberField } from "./NumberField.tsx";

type Tab = "hotkeys" | "typing" | "human" | "sound" | "behavior";
const TABS: [Tab, string][] = [["hotkeys", "Хоткеи"], ["typing", "Печать"], ["human", "Как человек"], ["sound", "Звук"], ["behavior", "Поведение"]];

export function SettingsDialog({ settings, onSave, onClose }: {
  settings: Settings; onSave: (patch: Partial<Settings>) => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("hotkeys");
  const [s, setS] = useState<Settings>({ ...settings });
  const autostart0 = useApp((x) => x.autostart);
  const [autostart, setAuto] = useState(autostart0);
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS((x) => ({ ...x, [k]: v }));

  const num = (k: keyof Settings, min: number, max: number, step = 1, suffix = "") => (
    <span><NumberField value={s[k] as number} min={min} max={max} step={step} onCommit={(v) => set(k, v as never)} /> {suffix}</span>
  );
  const check = (k: keyof Settings, label: string, title?: string, disabled = false) => (
    <label className="check full" title={title}>
      <input type="checkbox" checked={s[k] as boolean} disabled={disabled} onChange={(e) => set(k, e.target.checked as never)} />
      <span>{label}</span>
    </label>
  );

  const save = () => {
    const used = new Map<string, string>();
    for (const [k] of HOTKEYS) {
      const v = String(s[k] ?? "");
      if (!v) continue;
      if (!parseHotkey(v)) return alert(`Сочетание «${v}» не поддерживается.`);
      if (used.has(v)) return alert(`«${v}» назначен дважды.`);
      used.set(v, k);
    }
    if (!s.hotkey_toggle) return alert("Нужен хоткей «Старт / пауза».");
    const patch: Partial<Settings> = {};
    for (const k of Object.keys(s) as (keyof Settings)[]) if (s[k] !== settings[k]) (patch as Record<string, unknown>)[k] = s[k];
    onSave(patch);
    if (autostart !== autostart0) setAutostart(autostart);
    onClose();
  };
  const cancel = () => {
    sounds.configure(settings);   // проба звука могла сменить стиль
    onClose();
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && cancel()}>
      <div className="dialog" role="dialog" aria-label="Настройки" onKeyDown={(e) => e.key === "Escape" && cancel()}>
        <h2>Настройки</h2>
        <div className="dtabs">
          {TABS.map(([k, name]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{name}</button>)}
        </div>
        <div className="body">
          {tab === "hotkeys" && <>
            {HOTKEYS.map(([k, label]) => (
              <HotkeyRow key={k} label={label} value={String(s[k] ?? "")} onChange={(v) => set(k, v as never)} />
            ))}
            <p className="note full">Хоткеи глобальные — работают в любом окне и до него не доходят (их держит помощник).
              Удобны F-клавиши с Ctrl/Shift: они редко заняты в редакторах. Щёлкните по полю и нажмите сочетание.</p>
          </>}

          {tab === "typing" && <>
            <span>Скорость:</span>{num("cpm", 30, 3000, 10, "симв/мин")}
            <span>Разброс темпа:</span>{num("jitter", 0, 90, 1, "%")}
            <span>Пауза после Enter:</span>{num("newline_pause_ms", 0, 3000, 10, "мс")}
            <span>Пауза после , ; : ) ]:</span>{num("punct_pause_ms", 0, 1000, 10, "мс")}
            <span>Таб в образце =</span>{num("tab_width", 1, 8, 1, "пробелов")}
            <span title="Меньше — быстрее служебные нажатия, но медленные редакторы (Блокнот Windows 11, браузерные IDE) начинают терять символы">
              Мин. интервал нажатий:</span>{num("key_gap_ms", 5, 200, 5, "мс")}
            {check("fast_indent", "Отступы печатать быстро")}
            {check("indent_with_tab", "Отступы набирать клавишей Tab (как программист)",
              "Одно нажатие Tab на каждые «Таб в образце» пробелов. Не включайте для простых полей ввода в браузере: там Tab переводит фокус.")}
            {check("selection_whole_lines", "Выделение в образце расширять до целых строк")}
            {check("strip_comments", "Не печатать комментарии (# …, // …, /* … */)",
              "Строки-комментарии пропускаются целиком, комментарии в конце строки отрезаются. Сам образец не меняется.")}
            <span>Профиль окна:</span>
            <select value={s.profile} onChange={(e) => set("profile", e.target.value)}>
              {Object.entries(PROFILES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            {check("esc_before_enter", "Esc перед Enter (закрыть подсказки). Не для Jupyter!")}
            <p className="note full"><b>IDE</b>: убирает автоотступы и автоскобки редактора, чтобы код получился точно как
              в образце. <b>Блокнот</b>: печать «как есть». Если в редакторе пропадают символы — увеличьте мин. интервал нажатий.</p>
          </>}

          {tab === "human" && <>
            {check("human_typing", "Имитация ручного ввода")}
            <span>Опечатки:</span>
            <span><input type="number" min={0} max={30} value={s.typo_per_100_words} disabled={!s.human_typing}
              onChange={(e) => set("typo_per_100_words", Number(e.target.value))} /> на 100 слов</span>
            <span>Обдумывание строки:</span>
            <span><input type="number" min={0} max={10} step={0.5} value={s.think_pause_s} disabled={!s.human_typing}
              onChange={(e) => set("think_pause_s", Number(e.target.value))} /> с</span>
            <p className="note full">Как набирает человек:<br />
              • <b>неровный ритм</b> — знакомые слова (print, return, self) быстрой очередью, первая буква слова,
              заглавные и символы с Shift — медленнее, темп плавно «гуляет»;<br />
              • <b>обдумывание</b> — пауза перед новой строкой, дольше перед новым куском кода, иногда заминка между словами;<br />
              • <b>опечатки</b> — соседняя клавиша, перестановка букв, двойное нажатие; ошибка замечается через 0–2 буквы
              и исправляется Backspace. Скобки, кавычки, отступы и Enter не задеваются.<br />
              «Разброс темпа» на вкладке «Печать» задаёт неровность ритма. Из-за пауз набор идёт медленнее заданной скорости.</p>
          </>}

          {tab === "sound" && <>
            {check("sound_enabled", "Звук клавиш")}
            <span>Звук:</span>
            <select value={s.sound_style} onChange={(e) => set("sound_style", e.target.value)}>
              {Object.entries(SOUND_STYLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <span>Громкость:</span>
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="range" min={0} max={100} value={s.sound_volume} style={{ flex: 1 }}
                onChange={(e) => set("sound_volume", Number(e.target.value))} />
              <span style={{ width: 40 }}>{s.sound_volume}%</span>
              <button className="btn small" onClick={() => {
                sounds.configure({ ...s, sound_enabled: true });
                sounds.demo(s.sound_style);
              }}>▶ Проба</button>
            </span>
            <p className="note full">Звук играет страница, поэтому вкладку с AutoPrintCode не закрывайте — её можно свернуть.
              Записи настоящих клавиатур, лицензия CC0.</p>
          </>}

          {tab === "behavior" && <>
            <span>Задержка старта по хоткею:</span>{num("hotkey_start_delay_ms", 0, 3000, 50, "мс")}
            <span>Отсчёт при старте кнопкой:</span>{num("button_countdown_s", 0, 10, 1, "с")}
            {check("minimize_on_button_start", "Сворачивать браузер при старте кнопкой (фокус вернётся в прошлое окно)")}
            {check("autopause_on_focus_change", "Пауза, если сменилось активное окно")}
            {check("guard_enabled", "Пауза, если во время печати нажата клавиша или кнопка мыши (случайная клавиша не попадёт в код)")}
            {check("auto_advance", "По окончании переходить к следующему блоку кода")}
            <label className="check full" title="Помощник стартует при входе в Windows без окна — останется открыть приложение AutoPrintCode">
              <input type="checkbox" checked={autostart} onChange={(e) => setAuto(e.target.checked)} />
              <span>Запускать помощника вместе с Windows (без окна)</span>
            </label>
          </>}
        </div>
        <div className="foot">
          <button className="btn" onClick={cancel}>Отмена</button>
          <button className="btn primary" onClick={save}>OK</button>
        </div>
      </div>
    </div>
  );
}

function HotkeyRow({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [listening, setListening] = useState(false);
  return <>
    <span>{label}:</span>
    <span className="hotkey-input">
      <input readOnly value={listening ? "Нажмите сочетание…" : value || "—"} className={listening ? "listening" : ""}
        onFocus={() => setListening(true)} onBlur={() => setListening(false)}
        onKeyDown={(e) => {
          if (e.key === "Tab") return;
          e.preventDefault();
          e.stopPropagation();   // Esc здесь отменяет ввод сочетания, а не закрывает окно настроек
          if (e.key === "Escape") return (e.target as HTMLInputElement).blur();
          const hk = hotkeyFromEvent(e);
          if (hk) {
            onChange(hk);
            (e.target as HTMLInputElement).blur();
          }
        }} />
      <button className="btn small" title="Без хоткея" onClick={() => onChange("")}>✕</button>
    </span>
  </>;
}
