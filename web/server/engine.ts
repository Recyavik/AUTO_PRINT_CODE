// Движок печати со стороны главного потока: запускает engine-worker.ts и пересылает ему команды.
import { EventEmitter } from "node:events";
import { MessageChannel, Worker } from "node:worker_threads";
import type { EngineState, Settings } from "../shared/model.ts";
import type { EngineCmd, EngineEvent } from "./engine-worker.ts";

export class Engine extends EventEmitter<{ event: [EngineEvent] }> {
  state: EngineState = "idle";
  pos = 0;
  total = 0;
  countdown = 0;
  /** Идёт подготовка (отсчёт, задержка хоткея, ожидание отпускания Ctrl/Alt/Shift) — её тоже ставят на паузу. */
  preparing = false;
  private readonly worker: Worker;
  private readonly port;
  private readonly ctrl = new Int32Array(new SharedArrayBuffer(8));

  constructor(settings: Settings, ownTitleMark: string, opts: { requireTitle?: string; dryRun?: boolean } = {}) {
    super();
    const { port1, port2 } = new MessageChannel();
    this.port = port1;
    this.worker = new Worker(new URL("./engine-worker.ts", import.meta.url), {
      workerData: { port: port2, ctrl: this.ctrl.buffer, settings, ownTitleMark, ...opts },
      transferList: [port2],
      name: "typing-engine",
    });
    this.worker.on("error", (err) => this.emit("event", { e: "log", level: "error", text: `Движок упал: ${(err as Error).stack}` }));
    port1.on("message", (ev: EngineEvent) => {
      if (ev.e === "state") this.state = ev.state;
      else if (ev.e === "progress") { this.pos = ev.pos; this.total = ev.total; }
      else if (ev.e === "countdown") this.countdown = ev.n;
      else if (ev.e === "preparing") this.preparing = ev.on;
      this.emit("event", ev);
    });
  }

  private send(cmd: EngineCmd): void {
    this.port.postMessage(cmd);
    Atomics.add(this.ctrl, 0, 1);
    Atomics.notify(this.ctrl, 0);
  }

  setSettings(settings: Settings): void { this.send({ c: "settings", settings }); }
  load(text: string): void { this.state = "idle"; this.send({ c: "load", text }); }
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
    this.stop();
    await this.worker.terminate();
  }
}
