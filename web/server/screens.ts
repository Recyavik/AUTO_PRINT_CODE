// Мониторы и окно страницы: на каком мониторе открывать AutoPrintCode при запуске.
//
// Настройка start_screen: "" — где было в прошлый раз (решает браузер), "primary" — основной монитор,
// иначе имя устройства Windows («\\.\DISPLAY2»). Нужна, чтобы случайно закрытое окно при новом запуске
// не появилось на мониторе демонстрации. Окно браузера двигает помощник средствами Windows —
// странице разрешений не нужно. Если выбранного монитора сейчас нет — берётся основной.
import { spawn } from "node:child_process";
import koffi from "koffi";

const user32 = koffi.load("user32.dll");

const RECT = koffi.struct("APC_RECT", { left: "int32", top: "int32", right: "int32", bottom: "int32" });
const PT = koffi.struct("APC_POINT", { x: "int32", y: "int32" });
const MONITORINFOEXW = koffi.struct("APC_MONITORINFOEXW", {
  cbSize: "uint32", rcMonitor: RECT, rcWork: RECT, dwFlags: "uint32", szDevice: koffi.array("char16_t", 32, "String"),
});
const WINDOWPLACEMENT = koffi.struct("APC_WINDOWPLACEMENT", {
  length: "uint32", flags: "uint32", showCmd: "uint32", ptMinPosition: PT, ptMaxPosition: PT, rcNormalPosition: RECT,
});
const MonitorEnumProc = koffi.proto("bool __stdcall APC_MonitorEnumProc(intptr_t hMon, intptr_t hdc, void *rect, intptr_t data)");
const WndEnumProc = koffi.proto("bool __stdcall APC_WndEnumProc(intptr_t hwnd, intptr_t data)");

const EnumDisplayMonitors = user32.func("bool __stdcall EnumDisplayMonitors(intptr_t hdc, void *clip, APC_MonitorEnumProc *cb, intptr_t data)");
const GetMonitorInfoW = user32.func("bool __stdcall GetMonitorInfoW(intptr_t hMon, _Inout_ APC_MONITORINFOEXW *info)");
const MonitorFromWindow = user32.func("intptr_t __stdcall MonitorFromWindow(intptr_t hwnd, uint32 flags)");
const GetWindowPlacement = user32.func("bool __stdcall GetWindowPlacement(intptr_t hwnd, _Inout_ APC_WINDOWPLACEMENT *wp)");
const SetWindowPlacement = user32.func("bool __stdcall SetWindowPlacement(intptr_t hwnd, APC_WINDOWPLACEMENT *wp)");
const EnumWindows = user32.func("bool __stdcall EnumWindows(APC_WndEnumProc *cb, intptr_t data)");
const IsWindowVisible = user32.func("bool __stdcall IsWindowVisible(intptr_t hwnd)");
const GetForegroundWindow = user32.func("intptr_t __stdcall GetForegroundWindow()");
const GetWindowTextW = user32.func("int __stdcall GetWindowTextW(intptr_t hWnd, _Out_ uint8_t *buf, int maxCount)");
const SetProcessDpiAwarenessContext = user32.func("bool __stdcall SetProcessDpiAwarenessContext(intptr_t value)");

const MONITORINFOF_PRIMARY = 1;
const MONITOR_DEFAULTTONEAREST = 2;
const SW_SHOWMINIMIZED = 2;
const SW_SHOWNORMAL = 1;
const DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4;

type Rect = { left: number; top: number; right: number; bottom: number };
export interface Monitor { id: string; label: string; primary: boolean; monitor: Rect; work: Rect }

/** Координаты в настоящих пикселях на каждом мониторе — иначе при масштабе 150–225 % окно уедет мимо. */
export function enableDpiAwareness(): void {
  try {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
  } catch {
    // старая Windows — останется как есть
  }
}

function monitorInfo(h: number): { id: string; primary: boolean; monitor: Rect; work: Rect } | null {
  const info: Record<string, unknown> = { cbSize: koffi.sizeof(MONITORINFOEXW) };
  if (!GetMonitorInfoW(h, info)) return null;
  return {
    id: String(info.szDevice).replace(/\0.*$/, ""),
    primary: ((info.dwFlags as number) & MONITORINFOF_PRIMARY) !== 0,
    monitor: info.rcMonitor as Rect,
    work: info.rcWork as Rect,
  };
}

const centerX = (r: Rect) => (r.left + r.right) / 2;
const centerY = (r: Rect) => (r.top + r.bottom) / 2;

/** Мониторы с подписями для настроек: «Монитор 2: 2560×1440». Номер — как у «Определить». */
export function listMonitors(): Monitor[] {
  const handles: number[] = [];
  const cb = koffi.register((h: number) => { handles.push(Number(h)); return true; }, koffi.pointer(MonitorEnumProc));
  try {
    EnumDisplayMonitors(0, null, cb, 0);
  } finally {
    koffi.unregister(cb);
  }
  // сначала основной, затем по положению — как в настольной версии
  const mons = handles.map(monitorInfo).filter((m) => m !== null)
    .sort((a, b) => Number(b.primary) - Number(a.primary) || a.monitor.left - b.monitor.left || a.monitor.top - b.monitor.top);
  return mons.map((m, i) => {
    const w = m.monitor.right - m.monitor.left;
    const h = m.monitor.bottom - m.monitor.top;
    return { ...m, label: `Монитор ${i + 1}: ${w}×${h}${m.primary ? " (основной)" : ""}` };
  });
}

function title(hwnd: number): string {
  const buf = Buffer.alloc(1024);
  const n = GetWindowTextW(hwnd, buf, 512);
  return buf.toString("utf16le", 0, n * 2);
}

/** Окно браузера со страницей AutoPrintCode (по метке в заголовке); активное — в первую очередь. */
export function findPageWindow(mark: string): number {
  const fg = Number(GetForegroundWindow());
  if (fg && title(fg).includes(mark)) return fg;
  let found = 0;
  const cb = koffi.register((h: number) => {
    if (IsWindowVisible(h) && title(Number(h)).includes(mark)) {
      found = Number(h);
      return false;
    }
    return true;
  }, koffi.pointer(WndEnumProc));
  try {
    EnumWindows(cb, 0);
  } finally {
    koffi.unregister(cb);
  }
  return found;
}

/** Обычное (не развёрнутое) положение окна по центру рабочей области монитора, размер — не больше неё.
 *  rcNormalPosition — в координатах рабочей области: они смещены, если панель задач основного монитора слева или сверху. */
export function normalRectOn(n: Rect, target: Pick<Monitor, "work">, primary: Pick<Monitor, "work" | "monitor">): Rect {
  const dx = primary.work.left - primary.monitor.left;
  const dy = primary.work.top - primary.monitor.top;
  const work = target.work;
  const w = Math.min(n.right - n.left, work.right - work.left);
  const h = Math.min(n.bottom - n.top, work.bottom - work.top);
  const left = Math.round(centerX(work) - w / 2) - dx;
  const top = Math.round(centerY(work) - h / 2) - dy;
  return { left, top, right: left + w, bottom: top + h };
}

/** Перенести окно на выбранный монитор. Возвращает подпись монитора или "" — двигать не понадобилось. */
export function placeWindow(hwnd: number, startScreen: string): string {
  if (!hwnd || !startScreen) return "";
  const mons = listMonitors();
  const primary = mons.find((m) => m.primary) ?? mons[0];
  const target = (startScreen === "primary" ? primary : mons.find((m) => m.id === startScreen)) ?? primary;
  const current = monitorInfo(Number(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)));
  if (!target || !current || current.id === target.id) return "";

  const wp: Record<string, unknown> = { length: koffi.sizeof(WINDOWPLACEMENT) };
  if (!GetWindowPlacement(hwnd, wp)) return "";
  wp.rcNormalPosition = normalRectOn(wp.rcNormalPosition as Rect, target, primary);
  if (wp.showCmd === SW_SHOWMINIMIZED) wp.showCmd = SW_SHOWNORMAL;
  wp.flags = 0;
  return SetWindowPlacement(hwnd, wp) ? target.label : "";
}

/** «Определить»: на каждом мониторе на пару секунд — крупный номер, как в списке «Окно при запуске».
 *  У помощника нет своих окон — значки рисует скрытый PowerShell (Windows Forms), в настоящих пикселях. */
export function identifyMonitors(ms = 2500): void {
  // кириллица и кавычки — без экранирования: скрипт передаётся в UTF-16 base64
  const encoded = Buffer.from(identifyScript(listMonitors(), ms), "utf16le").toString("base64");
  spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-EncodedCommand", encoded], { detached: true, stdio: "ignore", windowsHide: true }).unref();
}

/** Скрипт PowerShell со значками для мониторов (отдельно — чтобы проверять без показа).
 *  Мониторы находятся по имени устройства («\.\DISPLAY1»), границы берутся в координатах самого PowerShell —
 *  так значок встаёт по центру при любом масштабе экрана (225 % на 4K и т. п.). */
export function identifyScript(mons: Pick<Monitor, "id" | "primary">[], ms: number): string {
  const items = mons.map((m, i) => `@{n='${i + 1}';dev='${m.id.replace(/'/g, "''")}';note='${m.primary ? "основной" : ""}'}`).join(",");
  return `
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
try {
  Add-Type 'using System; using System.Runtime.InteropServices; public static class Dpi { [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v); }'
  [Dpi]::SetProcessDpiAwarenessContext([IntPtr]-4) | Out-Null
} catch {}
$screens = [System.Windows.Forms.Screen]::AllScreens
$forms = @()
foreach ($m in @(${items})) {
  $sc = $screens | Where-Object { $_.DeviceName -eq $m.dev } | Select-Object -First 1
  if (-not $sc) { continue }
  $b = $sc.Bounds
  $k = [Math]::Max(1.0, $b.Height / 1080.0)
  $w = [int](420 * $k); $h = [int](300 * $k)
  $f = New-Object System.Windows.Forms.Form
  $f.FormBorderStyle = 'None'; $f.StartPosition = 'Manual'; $f.TopMost = $true; $f.ShowInTaskbar = $false
  $f.BackColor = [System.Drawing.Color]::FromArgb(30, 34, 41)
  $f.Bounds = New-Object System.Drawing.Rectangle(([int]($b.X + ($b.Width - $w) / 2)), ([int]($b.Y + ($b.Height - $h) / 2)), $w, $h)
  $num = New-Object System.Windows.Forms.Label
  $num.Text = $m.n; $num.Dock = 'Fill'; $num.TextAlign = 'MiddleCenter'
  $num.ForeColor = [System.Drawing.Color]::FromArgb(167, 139, 250)
  $num.Font = New-Object System.Drawing.Font('Segoe UI', [float](150 * $k), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $note = New-Object System.Windows.Forms.Label
  $note.Text = $m.note; $note.Dock = 'Bottom'; $note.Height = [int](48 * $k); $note.TextAlign = 'MiddleCenter'
  $note.ForeColor = [System.Drawing.Color]::FromArgb(230, 232, 235)
  $note.Font = New-Object System.Drawing.Font('Segoe UI', [float](22 * $k), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $f.Controls.Add($num); $f.Controls.Add($note)
  $forms += $f
}
# процесс запущен «скрытым»: Windows прячет первое показанное окно — показываем каждое дважды
foreach ($f in $forms) { $f.Show(); $f.Hide(); $f.Show(); $f.Bounds = $f.Bounds; $f.Activate() }
foreach ($f in $forms) { Write-Output ("монитор {0}: {1} visible={2}" -f $f.Controls[0].Text, $f.Bounds, $f.Visible) }
$t = New-Object System.Windows.Forms.Timer
$t.Interval = ${ms}
$t.Add_Tick({ $t.Stop(); foreach ($f in $forms) { $f.Close() }; [System.Windows.Forms.Application]::ExitThread() })
$t.Start()
[System.Windows.Forms.Application]::Run()
`;
}
