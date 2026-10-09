// Звук клавиш — записи настоящих клавиатур (CC0, autoprint/sounds/SOURCES.md) через Web Audio.
// Нажатие + отпускание через естественную паузу, чуть разная высота и сила удара у каждого нажатия.
// Пробел и Enter — крупные клавиши: ниже по тону и громче.
import type { Settings } from "../../shared/model.ts";

type Kind = "key" | "space" | "enter";
// kind → [высота тона, громкость, пауза до отпускания, мс]
const KIND: Record<Kind, [number, number, [number, number]]> = {
  key: [1.0, 1.0, [70, 115]],
  space: [0.86, 1.12, [85, 135]],
  enter: [0.9, 1.25, [95, 150]],
};
const COUNTS: Record<string, [number, number]> = { office: [14, 0], blue: [6, 4], brown: [6, 4], red: [6, 4], cream: [6, 4] };

const rand = (a: number, b: number) => a + (b - a) * Math.random();
const pick = <T,>(a: T[]) => a[Math.floor(Math.random() * a.length)];

class KeySounds {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private packs = new Map<string, Promise<{ downs: AudioBuffer[]; ups: AudioBuffer[] }>>();
  private style = "office";
  private volume = 0.35;
  enabled = true;

  /** Браузер разрешает звук только после действия пользователя на странице. */
  unlock(): void {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: "interactive" });
      this.gain = this.ctx.createGain();
      this.gain.gain.value = this.volume;
      // ограничитель: громкий Enter поверх ещё звучащего нажатия не должен хрипеть
      const limiter = new DynamicsCompressorNode(this.ctx, { threshold: -3, knee: 0, ratio: 20, attack: 0.001, release: 0.05 });
      this.gain.connect(limiter).connect(this.ctx.destination);
      void this.load(this.style);
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
  }

  get locked(): boolean {
    return !this.ctx || this.ctx.state !== "running";
  }

  configure(s: Settings): void {
    this.enabled = s.sound_enabled;
    this.volume = Math.max(0, Math.min(100, s.sound_volume)) / 100;
    if (this.gain) this.gain.gain.value = this.volume;
    if (s.sound_style !== this.style) {
      this.style = s.sound_style;
      if (this.ctx) void this.load(this.style);
    }
  }

  private load(style: string) {
    let p = this.packs.get(style);
    if (!p) {
      const [nd, nu] = COUNTS[style] ?? COUNTS.office;
      const fetchAll = (prefix: string, n: number) => Promise.all(Array.from({ length: n }, async (_, i) => {
        const r = await fetch(`/sounds/${style}/${prefix}_${String(i).padStart(2, "0")}.wav`);
        if (!r.ok) throw new Error(`звук ${r.url}: ${r.status}`);
        return this.ctx!.decodeAudioData(await r.arrayBuffer());
      }));
      p = Promise.all([fetchAll("down", nd), fetchAll("up", nu)]).then(([downs, ups]) => ({ downs, ups }));
      // не загрузился — повторить не раньше чем через 30 с, а не на каждом нажатии
      p.catch(() => setTimeout(() => this.packs.delete(style), 30_000));
      this.packs.set(style, p);
    }
    return p;
  }

  private hit(buf: AudioBuffer, when: number, rate: number, gain: number): void {
    const ctx = this.ctx!;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = rate;
    const g = ctx.createGain();
    g.gain.value = gain;
    src.connect(g).connect(this.gain!);
    src.start(when);
  }

  play(kind: Kind, force = false): void {
    if ((!this.enabled && !force) || this.volume <= 0 || !this.ctx || this.ctx.state !== "running") return;
    void this.load(this.style).then(({ downs, ups }) => {
      const [pitch0, gain0, [lo, hi]] = KIND[kind] ?? KIND.key;
      const pitch = pitch0 * rand(0.97, 1.03);
      const gain = gain0 * rand(0.85, 1.0);
      const t = this.ctx!.currentTime;
      this.hit(pick(downs), t, pitch, gain);
      if (ups.length) this.hit(pick(ups), t + rand(lo, hi) / 1000, pitch * rand(0.98, 1.02), gain * rand(0.75, 1.0));
    }).catch(() => {});   // без звука — не беда, печать идёт
  }

  /** Проба звука: несколько нажатий подряд. */
  demo(style?: string): void {
    this.unlock();
    if (style && style !== this.style) {
      this.style = style;
      void this.load(style);
    }
    (["key", "key", "key", "space", "key", "key", "enter"] as Kind[])
      .forEach((k, i) => setTimeout(() => this.play(k, true), 150 + i * 140));
  }
}

export const sounds = new KeySounds();
