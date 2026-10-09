// Тонкая обёртка над WinAPI через koffi (порт autoprint/winapi.py): эмуляция клавиатуры (SendInput),
// активное окно, права процесса. Символы печатаются через KEYEVENTF_UNICODE — не зависит от раскладки
// (кириллица, спецсимволы, эмодзи работают одинаково). Дескрипторы окон — числа (intptr).
import koffi from "koffi";

const user32 = koffi.load("user32.dll");
const kernel32 = koffi.load("kernel32.dll");
const advapi32 = koffi.load("advapi32.dll");
const winmm = koffi.load("winmm.dll");

export const INPUT_KEYBOARD = 1;
export const KEYEVENTF_EXTENDEDKEY = 0x0001;
export const KEYEVENTF_KEYUP = 0x0002;
export const KEYEVENTF_UNICODE = 0x0004;

export const VK_BACK = 0x08;
export const VK_TAB = 0x09;
export const VK_RETURN = 0x0d;
export const VK_SHIFT = 0x10;
export const VK_CONTROL = 0x11;
export const VK_MENU = 0x12;
export const VK_ESCAPE = 0x1b;
export const VK_END = 0x23;
export const VK_HOME = 0x24;
export const VK_LWIN = 0x5b;
export const VK_RWIN = 0x5c;

// Клавиши, которым нужен флаг EXTENDEDKEY (иначе Windows считает их цифровым блоком).
const EXTENDED = new Set([VK_HOME, VK_END, 0x25, 0x26, 0x27, 0x28, 0x2e, 0x21, 0x22, 0x2d]);

const KEYBDINPUT = koffi.struct("KEYBDINPUT", {
  wVk: "uint16", wScan: "uint16", dwFlags: "uint32", time: "uint32", dwExtraInfo: "uintptr_t",
});
const MOUSEINPUT = koffi.struct("MOUSEINPUT", {
  dx: "int32", dy: "int32", mouseData: "uint32", dwFlags: "uint32", time: "uint32", dwExtraInfo: "uintptr_t",
});
const INPUT_UNION = koffi.union("INPUT_UNION", { ki: KEYBDINPUT, mi: MOUSEINPUT });
const INPUT = koffi.struct("INPUT", { type: "uint32", u: INPUT_UNION });
const INPUT_SIZE = koffi.sizeof(INPUT);

const SendInput = user32.func("uint32 __stdcall SendInput(uint32 cInputs, INPUT *pInputs, int cbSize)");
const MapVirtualKeyW = user32.func("uint32 __stdcall MapVirtualKeyW(uint32 uCode, uint32 uMapType)");
const GetAsyncKeyState = user32.func("int16 __stdcall GetAsyncKeyState(int vKey)");
const GetForegroundWindow = user32.func("intptr_t __stdcall GetForegroundWindow()");
const GetWindowThreadProcessId = user32.func(
  "uint32 __stdcall GetWindowThreadProcessId(intptr_t hWnd, _Out_ uint32 *pid)");
const GetWindowTextLengthW = user32.func("int __stdcall GetWindowTextLengthW(intptr_t hWnd)");
const GetWindowTextW = user32.func("int __stdcall GetWindowTextW(intptr_t hWnd, _Out_ uint8_t *buf, int maxCount)");
const ShowWindow = user32.func("bool __stdcall ShowWindow(intptr_t hWnd, int nCmdShow)");
const GetLastError = kernel32.func("uint32 __stdcall GetLastError()");
const OpenProcess = kernel32.func("intptr_t __stdcall OpenProcess(uint32 access, bool inherit, uint32 pid)");
const CloseHandle = kernel32.func("bool __stdcall CloseHandle(intptr_t h)");
const GetCurrentProcess = kernel32.func("intptr_t __stdcall GetCurrentProcess()");
const QueryFullProcessImageNameW = kernel32.func(
  "bool __stdcall QueryFullProcessImageNameW(intptr_t h, uint32 flags, _Out_ uint8_t *buf, _Inout_ uint32 *size)");
const OpenProcessToken = advapi32.func(
  "bool __stdcall OpenProcessToken(intptr_t h, uint32 access, _Out_ intptr_t *token)");
const GetTokenInformation = advapi32.func(
  "bool __stdcall GetTokenInformation(intptr_t token, int cls, _Out_ uint32 *info, uint32 len, _Out_ uint32 *ret)");
const timeBeginPeriod = winmm.func("uint32 __stdcall timeBeginPeriod(uint32 ms)");
const timeEndPeriod = winmm.func("uint32 __stdcall timeEndPeriod(uint32 ms)");

const PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
const TOKEN_QUERY = 0x0008;
const TokenElevation = 20;
const SW_MINIMIZE = 6;

type KeyInput = { type: number; u: { ki: { wVk: number; wScan: number; dwFlags: number; time: number; dwExtraInfo: number } } };

function keyInput(vk = 0, scan = 0, flags = 0): KeyInput {
  return { type: INPUT_KEYBOARD, u: { ki: { wVk: vk, wScan: scan, dwFlags: flags, time: 0, dwExtraInfo: 0 } } };
}

function send(inputs: KeyInput[]): void {
  if (!inputs.length) return;
  const sent = SendInput(inputs.length, inputs, INPUT_SIZE);
  if (sent !== inputs.length) {
    throw new Error(`SendInput заблокирован (ошибка ${GetLastError()}; окно с правами администратора?)`);
  }
}

function vkEvent(vk: number, up: boolean): KeyInput {
  let flags = up ? KEYEVENTF_KEYUP : 0;
  if (EXTENDED.has(vk)) flags |= KEYEVENTF_EXTENDEDKEY;
  return keyInput(vk, MapVirtualKeyW(vk, 0), flags);
}

/** Печатает один символ (вне BMP — суррогатной парой). */
export function typeChar(ch: string): void {
  const inputs: KeyInput[] = [];
  for (let i = 0; i < ch.length; i++) {
    const u = ch.charCodeAt(i);
    inputs.push(keyInput(0, u, KEYEVENTF_UNICODE), keyInput(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP));
  }
  send(inputs);
}

/** Нажимает vk, удерживая модификаторы (например tap(VK_HOME, VK_SHIFT)). */
export function tap(vk: number, ...modifiers: number[]): void {
  send([
    ...modifiers.map((m) => vkEvent(m, false)),
    vkEvent(vk, false), vkEvent(vk, true),
    ...[...modifiers].reverse().map((m) => vkEvent(m, true)),
  ]);
}

const MODIFIER_VKS = [VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN];

export function modifiersDown(): boolean {
  return MODIFIER_VKS.some((vk) => GetAsyncKeyState(vk) & 0x8000);
}


export function foregroundWindow(): number {
  return Number(GetForegroundWindow());
}

export function windowPid(hwnd: number): number {
  const pid = [0];
  GetWindowThreadProcessId(hwnd, pid);
  return pid[0];
}

export function windowTitle(hwnd: number): string {
  if (!hwnd) return "";
  const n = GetWindowTextLengthW(hwnd);
  const buf = Buffer.alloc((n + 1) * 2);
  const got = GetWindowTextW(hwnd, buf, n + 1);
  return buf.toString("utf16le", 0, got * 2);
}

export function windowProcessName(hwnd: number): string {
  const pid = windowPid(hwnd);
  if (!pid) return "?";
  const h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid);
  if (!h) return `pid ${pid}`;
  try {
    const buf = Buffer.alloc(1040);
    const size = [520];
    if (QueryFullProcessImageNameW(h, 0, buf, size)) return buf.toString("utf16le", 0, size[0] * 2).split("\\").pop()!;
    return `pid ${pid}`;
  } finally {
    CloseHandle(h);
  }
}

export function describeWindow(hwnd: number): string {
  let title = windowTitle(hwnd);
  if (title.length > 60) title = title.slice(0, 57) + "…";
  return `${windowProcessName(hwnd)} «${title}»`;
}

function processElevated(hproc: number): boolean | null {
  const tok = [0];
  if (!OpenProcessToken(hproc, TOKEN_QUERY, tok)) return null;
  try {
    const val = [0];
    const size = [0];
    if (!GetTokenInformation(tok[0], TokenElevation, val, 4, size)) return null;
    return val[0] !== 0;
  } finally {
    CloseHandle(tok[0]);
  }
}

export function selfElevated(): boolean {
  return !!processElevated(Number(GetCurrentProcess()));
}

/** Окно процесса с правами администратора? Ввод в такое окно Windows молча отбрасывает (UIPI). */
export function windowElevated(hwnd: number): boolean {
  const pid = windowPid(hwnd);
  if (!pid) return false;
  const h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid);
  if (!h) return true;   // доступ запрещён — скорее всего, процесс повышенный
  try {
    return !!processElevated(h);
  } finally {
    CloseHandle(h);
  }
}

export function minimizeWindow(hwnd: number): void {
  if (hwnd) ShowWindow(hwnd, SW_MINIMIZE);
}

/** Точность системного таймера 1 мс на время печати (по умолчанию 15,6 мс — слишком грубо для темпа). */
export function highResTimer(on: boolean): void {
  if (on) timeBeginPeriod(1);
  else timeEndPeriod(1);
}
