// Глобальные хоткеи и защита набора — один поток с очередью сообщений Windows
// (порт hotkeys.py и guard.py).
//
// Хоткеи: RegisterHotKey — работают в любом окне, до самого окна нажатие не доходит.
// Защита: пока идёт печать, ставятся низкоуровневые хуки клавиатуры и мыши. Физическое нажатие клавиши
// (кроме модификаторов и хоткеев) или кнопки мыши → событие tripped, движок встаёт на паузу.
// Нажатая клавиша поглощается, чтобы не попасть в код; клик — нет (пользователь, возможно, переключает окно).
// Свои синтетические события (флаг INJECTED) пропускаются. Ничего не записывается — только факт нажатия.
import koffi from "koffi";
import { type MessagePort, receiveMessageOnPort, workerData } from "node:worker_threads";
import { parseHotkey } from "../shared/hotkeys.ts";

export type InputCmd =
  | { c: "bindings"; bindings: Record<string, string> }
  | { c: "arm" }
  | { c: "disarm" };
export type InputEvent =
  | { e: "ready"; threadId: number }
  | { e: "hotkey"; action: string }
  | { e: "failed"; text: string }
  | { e: "tripped"; kind: "key" | "mouse" };

const user32 = koffi.load("user32.dll");
const kernel32 = koffi.load("kernel32.dll");

const POINT = koffi.struct("POINT", { x: "int32", y: "int32" });
// MSG в коде не упоминается: koffi регистрирует структуру по имени, на неё ссылаются сигнатуры "MSG *"
koffi.struct("MSG", {
  hwnd: "intptr_t", message: "uint32", wParam: "uintptr_t", lParam: "intptr_t", time: "uint32", pt: POINT, lPrivate: "uint32",
});
const KBDLLHOOKSTRUCT = koffi.struct("KBDLLHOOKSTRUCT", {
  vkCode: "uint32", scanCode: "uint32", flags: "uint32", time: "uint32", dwExtraInfo: "uintptr_t",
});
const MSLLHOOKSTRUCT = koffi.struct("MSLLHOOKSTRUCT", {
  pt: POINT, mouseData: "uint32", flags: "uint32", time: "uint32", dwExtraInfo: "uintptr_t",
});
const HookProc = koffi.proto("intptr_t __stdcall LLHookProc(int nCode, uintptr_t wParam, void *lParam)");

const GetMessageW = user32.func("int __stdcall GetMessageW(_Out_ MSG *msg, intptr_t hwnd, uint32 min, uint32 max)");
const PeekMessageW = user32.func("bool __stdcall PeekMessageW(_Out_ MSG *msg, intptr_t hwnd, uint32 min, uint32 max, uint32 remove)");
const RegisterHotKey = user32.func("bool __stdcall RegisterHotKey(intptr_t hwnd, int id, uint32 mods, uint32 vk)");
const UnregisterHotKey = user32.func("bool __stdcall UnregisterHotKey(intptr_t hwnd, int id)");
const SetWindowsHookExW = user32.func("intptr_t __stdcall SetWindowsHookExW(int id, LLHookProc *fn, intptr_t hmod, uint32 tid)");
const CallNextHookEx = user32.func("intptr_t __stdcall CallNextHookEx(intptr_t hhk, int code, uintptr_t wParam, void *lParam)");
const UnhookWindowsHookEx = user32.func("bool __stdcall UnhookWindowsHookEx(intptr_t hhk)");
const GetAsyncKeyState = user32.func("int16 __stdcall GetAsyncKeyState(int vKey)");
const GetCurrentThreadId = kernel32.func("uint32 __stdcall GetCurrentThreadId()");
const GetModuleHandleW = kernel32.func("intptr_t __stdcall GetModuleHandleW(void *name)");

const WM_HOTKEY = 0x0312;
const WM_KEYDOWN = 0x0100;
const WM_SYSKEYDOWN = 0x0104;
const MOUSE_DOWNS = new Set([0x0201, 0x0204, 0x0207, 0x020b]);
const WM_APP_WAKE = 0x8000 + 1;
const WH_KEYBOARD_LL = 13;
const WH_MOUSE_LL = 14;
const LLKHF_INJECTED = 0x10;
const LLMHF_INJECTED = 0x01;
const MOD_NOREPEAT = 0x4000;
// Модификаторы сами по себе паузу не вызывают: ими начинается хоткей.
const MODIFIERS = new Set([0x10, 0x11, 0x12, 0x5b, 0x5c, 0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5, 0x14, 0x90, 0x91]);
const MOD_VK: [number, number][] = [[0x0002, 0x11], [0x0001, 0x12], [0x0004, 0x10], [0x0008, 0x5b], [0x0008, 0x5c]];

const { port } = workerData as { port: MessagePort };
const emit = (ev: InputEvent) => port.postMessage(ev);

let ids = new Map<number, string>();
let hotkeySet = new Set<string>();   // "mods:vk" — нажатие хоткея не считается вмешательством
let armed = false;
let fired = false;
let kbHook = 0;
let msHook = 0;

const currentMods = () => MOD_VK.reduce((m, [flag, vk]) => (GetAsyncKeyState(vk) & 0x8000 ? m | flag : m), 0);

// Колбэки должны отрабатывать быстро (иначе Windows снимет хук) — только флаги и сообщение.
const kbProc = koffi.register((code: number, wParam: number, lParam: unknown) => {
  if (code === 0 && armed && (wParam === WM_KEYDOWN || wParam === WM_SYSKEYDOWN)) {
    const k = koffi.decode(lParam, KBDLLHOOKSTRUCT) as { vkCode: number; flags: number };
    if (!(k.flags & LLKHF_INJECTED) && !MODIFIERS.has(k.vkCode) && !hotkeySet.has(`${currentMods()}:${k.vkCode}`)) {
      if (!fired) {
        fired = true;
        emit({ e: "tripped", kind: "key" });
      }
      return 1;   // поглотить: случайная клавиша не должна попасть в код
    }
  }
  return CallNextHookEx(0, code, wParam, lParam);
}, koffi.pointer(HookProc));

const msProc = koffi.register((code: number, wParam: number, lParam: unknown) => {
  if (code === 0 && armed && MOUSE_DOWNS.has(wParam)) {
    const m = koffi.decode(lParam, MSLLHOOKSTRUCT) as { flags: number };
    if (!(m.flags & LLMHF_INJECTED) && !fired) {
      fired = true;
      emit({ e: "tripped", kind: "mouse" });
    }
  }
  return CallNextHookEx(0, code, wParam, lParam);
}, koffi.pointer(HookProc));

function install(): void {
  fired = false;
  armed = true;
  if (kbHook) return;
  const hmod = GetModuleHandleW(null);
  kbHook = Number(SetWindowsHookExW(WH_KEYBOARD_LL, kbProc, hmod, 0));
  msHook = Number(SetWindowsHookExW(WH_MOUSE_LL, msProc, hmod, 0));
}

function uninstall(): void {
  armed = false;
  if (kbHook) UnhookWindowsHookEx(kbHook);
  if (msHook) UnhookWindowsHookEx(msHook);
  kbHook = msHook = 0;
}

function setBindings(bindings: Record<string, string>): void {
  for (const id of ids.keys()) UnregisterHotKey(0, id);
  ids = new Map();
  hotkeySet = new Set();
  const bad: string[] = [];
  let id = 0;
  for (const [action, text] of Object.entries(bindings)) {
    id++;
    const parsed = parseHotkey(text);
    if (!parsed) {
      if (text) bad.push(text);
      continue;
    }
    const [mods, vk] = parsed;
    hotkeySet.add(`${mods}:${vk}`);
    if (RegisterHotKey(0, id, mods | MOD_NOREPEAT, vk)) ids.set(id, action);
    else bad.push(text);
  }
  if (bad.length) emit({ e: "failed", text: bad.join(", ") });
}

function drain(): void {
  for (let m = receiveMessageOnPort(port); m; m = receiveMessageOnPort(port)) {
    const cmd = m.message as InputCmd;
    if (cmd.c === "bindings") setBindings(cmd.bindings);
    else if (cmd.c === "arm") install();
    else uninstall();
  }
}

// очередь сообщений потока создаётся до того, как в неё начнут писать
const msg: Record<string, unknown> = {};
PeekMessageW(msg, 0, 0, 0, 0);
emit({ e: "ready", threadId: GetCurrentThreadId() });
drain();
while (GetMessageW(msg, 0, 0, 0) > 0) {
  if (msg.message === WM_HOTKEY) {
    const action = ids.get(Number(msg.wParam));
    if (action) emit({ e: "hotkey", action });
  } else if (msg.message === WM_APP_WAKE) {
    drain();
  }
}
uninstall();
