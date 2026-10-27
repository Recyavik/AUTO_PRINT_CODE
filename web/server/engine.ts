// Движок печати со стороны главного потока: запускает engine-worker.ts и пересылает ему команды.
// Если поток печати упадёт — он запускается заново, состояние сбрасывается в «готов»
// (иначе «печать» висела бы вечно: хоткей шлёт паузы в мёртвый поток, хоткеи не освобождаются).
import { EventEmitter } from "node:events";
import { MessageChannel, type MessagePort, Worker } from "node:worker_threads";
import type { EngineState, Settings } from "../shared/model.ts";
import type { EngineCmd, EngineEvent } from "./engine-worker.ts";

export class Engine extends EventEmitter<{ event: [EngineEvent] }> {
  state: EngineState = "idle";
  pos = 0;
  total = 0;
  countdown = 0;
  /** Идёт подготовка (отсчёт, задержка хоткея, ожидание отпускания Ctrl/Alt/Shift) — её тоже ставят на паузу. */
  preparing = false;
  private worker!: Worker;
  private port!: MessagePort;
  private ctrl = new Int32Array(new SharedArrayBuffer(8));
  private settings: Settings;
  private closing = false;
  private readonly ownTitleMark: string;
  private readonly opts: { requireTitle?: string; dryRun?: boolean };

  constructor(settings: Settings, ownTitleMark: string, opts: { requireTitle?: string; dryRun?: boolean } = {}) {
    super();
    this.settings = settings;
    this.ownTitleMark = ownTitleMark;
    this.opts = opts;
    this.spawn();
  }

  private spawn(): void {
    const { port1, port2 } = new MessageChannel();
    this.port = port1;
    this.ctrl = new Int32Array(new SharedArrayBuffer(8));
    this.worker = new Worker(new URL("./engine-worker.ts", import.meta.url), {
      workerData: { port: port2, ctrl: this.ctrl.buffer, settings: this.settings, ownTitleMark: this.ownTitleMark, ...this.opts },
      transferList: [port2],
      name: "typing-engine",
    });
    this.worker.on("error", (err) => this.recover(`Движок упал: ${(err as Error).stack}`));
    this.worker.on("exit", (code) => { if (!this.closing && code !== 0) this.recover(`Движок завершился с кодом ${code}`); });
    port1.on("message", (ev: EngineEvent) => {
      if (ev.e === "state") this.state = ev.state;
      else if (ev.e === "progress") { this.pos = ev.pos; this.total = ev.total; }
      else if (ev.e === "countdown") this.countdown = ev.n;
      else if (ev.e === "preparing") this.preparing = ev.on;
      this.emit("event", ev);
    });
  }

  private recover(why: string): void {
    if (this.closing) return;
    this.emit("event", { e: "log", level: "error", text: `${why} — запускаю заново` });
    this.port.close();
    void this.worker.terminate();
    this.preparing = false;
    this.countdown = 0;
    this.pos = 0;
    this.spawn();
    this.state = "idle";
    this.emit("event", { e: "state", state: "idle" });
    this.emit("event", { e: "message", text: "Сбой движка печати — он перезапущен. Запустите печать снова." });
  }

  private send(cmd: EngineCmd): void {
    this.port.postMessage(cmd);
    Atomics.add(this.ctrl, 0, 1);
    Atomics.notify(this.ctrl, 0);
  }

  setSettings(settings: Settings): void { this.settings = settings; this.send({ c: "settings", settings }); }
  load(text: string, profile = ""): void { this.state = "idle"; this.send({ c: "load", text, profile }); }
  start(delay: number, countdown: number): void { this.send({ c: "start", delay, countdown }); }
  resume(delay: number, countdown: number): void { this.send({ c: "resume", delay, countdown }); }
  restart(delay: number, countdown: number): void { this.send({ c: "restart", delay, countdown }); }
  pause(reason = "хоткей/кнопка"): void { this.send({ c: "pause", reason }); }
  stop(): void { this.send({ c: "stop" }); }

  /** Печать идёт или готовится: «старт/пауза» в этот момент ставит на паузу. */
  get active(): boolean {
    return this.state === "running" || this.state === "countdown" || this.preparing;
  }

  get busy(): boolean {
    return this.state === "running" || this.state === "countdown" || this.state === "paused";
  }

  async close(): Promise<void> {
    this.closing = true;
    this.stop();
    await this.worker.terminate();
  }
}
