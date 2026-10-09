// Числовое поле: значение в пределах [min, max] применяется сразу (стрелки, колёсико),
// а набираемое «по цифре» (4 → 40 → 400) не обрезается на полпути — пределы применяются при выходе из поля.
import { useState } from "react";

export function NumberField({ id, value, min, max, step = 1, onCommit }: {
  id?: string; value: number; min: number; max: number; step?: number; onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const finish = (raw: string) => {
    const n = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(n)) onCommit(Math.max(min, Math.min(max, n)));
    setDraft(null);
  };
  return (
    <input id={id} type="number" min={min} max={max} step={step} value={draft ?? value}
      onChange={(e) => {
        const raw = e.target.value;
        const n = Number(raw);
        if (raw.trim() !== "" && n >= min && n <= max) {
          onCommit(n);
          setDraft(null);
        } else setDraft(raw);
      }}
      onBlur={(e) => draft !== null && finish(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && finish((e.target as HTMLInputElement).value)} />
  );
}
