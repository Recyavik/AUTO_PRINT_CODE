// Тема страницы: тёмная или светлая (палитра 1Т — как у настольного AutoPrintCode и «Таймера вебинара»).
// Выбор — кнопкой ☀/🌙 в панели, хранится в браузере; пока не выбирали — как в системе.
export type Theme = "dark" | "light";

const KEY = "apc-theme";

export function savedTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "dark" || t === "light") return t;
  } catch { /* приватный режим — как в системе */ }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

/** Подписка на смену темы (редактор кода перекрашивается вместе со страницей). Возвращает отписку. */
export function onThemeChange(fn: (t: Theme) => void): () => void {
  const h = () => fn(currentTheme());
  window.addEventListener("apc-theme", h);
  return () => window.removeEventListener("apc-theme", h);
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  window.dispatchEvent(new Event("apc-theme"));
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "dark" ? "#221836" : "#E3DBEF");
}

export function setTheme(t: Theme): void {
  applyTheme(t);
  try { localStorage.setItem(KEY, t); } catch { /* не запомнится — не страшно */ }
}
