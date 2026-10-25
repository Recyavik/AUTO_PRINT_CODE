// Хоткеи и защита набора со стороны главного потока: запускает input-worker.ts.
// Поток спит в GetMessageW, поэтому после каждой команды его будит PostThreadMessageW.
import koffi from "koffi";
import { EventEmitter } from "node:events";
import { MessageChannel, Worker } from "node:worker_threads";
import type { InputCmd, InputEvent } from "./input-worker.ts";

const PostThreadMessageW = koffi.load("user32.dll")
  .func("bool __stdcall PostThreadMessageW(uint32 tid, uint32 msg, uintptr_t w, intptr_t l)");
const WM_QUIT = 0x0012;
const WM_APP_WAKE = 0x8000 + 1;

export class InputHooks extends EventEmitter<{ hotkey: [string]; failed: [string]; tripped: ["key" | "mouse"]; error: [Error] }> {
  private readonly worker: Worker;
  private readonly port;
  private threadId = 0;

  constructor() {
    super();
    const { port1, port2 } = new MessageChannel();
    this.port = port1;
    this.worker = new Worker(new URL("./input-worker.ts", import.meta.url), {
      workerData: { port: port2 }, transferList: [port2], name: "input-hooks",
    });
    this.worker.on("error", (err) => this.emit("error", err as Error));   // без обработчика падение потока уронило бы помощника
    port1.on("message", (ev: InputEvent) => {
      if (ev.e === "ready") {
        this.threadId = ev.threadId;
        this.wake();   // команды, отправленные до готовности потока
      } else if (ev.e === "hotkey") this.emit("hotkey", ev.action);
      else if (ev.e === "failed") this.emit("failed", ev.text);
      else if (ev.e === "tripped") this.emit("tripped", ev.kind);
    });
  }

  private wake(): void {
    if (this.threadId) PostThreadMessageW(this.threadId, WM_APP_WAKE, 0, 0);
  }

  private send(cmd: InputCmd): void {
    this.port.postMessage(cmd);
    this.wake();
  }

  /** {действие: 'Ctrl+F9'}; пустые строки — без хоткея. */
  setBindings(bindings: Record<string, string>): void { this.send({ c: "bindings", bindings }); }
  arm(): void { this.send({ c: "arm" }); }
  disarm(): void { this.send({ c: "disarm" }); }

  async close(): Promise<void> {
    if (this.threadId) PostThreadMessageW(this.threadId, WM_QUIT, 0, 0);
    await this.worker.terminate();
  }
}
