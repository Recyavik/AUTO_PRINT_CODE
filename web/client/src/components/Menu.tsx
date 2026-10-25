// Всплывающее меню (контекстное меню образца, «вставить блок»).
import { useEffect, useRef } from "react";

export interface MenuItem { label: string; run?: () => void; danger?: boolean; separator?: boolean }

export function Menu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);   // onClose — новая функция на каждый рендер; подписка — одна
  onCloseRef.current = onClose;
  useEffect(() => {
    const close = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onCloseRef.current(); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    // нажатие, открывшее меню, ещё всплывает — слушать «мимо меню» начинаем со следующего
    const timer = setTimeout(() => document.addEventListener("mousedown", close));
    document.addEventListener("keydown", esc);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, []);
  // не вылезать за край окна
  const left = Math.min(x, window.innerWidth - 220);
  const top = Math.min(y, window.innerHeight - items.length * 32 - 16);
  return (
    <div ref={ref} className="menu" style={{ left, top }}>
      {items.map((it, i) => it.separator ? <hr key={i} /> : (
        <button key={i} className={it.danger ? "danger" : ""} onClick={() => { onClose(); it.run?.(); }}>{it.label}</button>
      ))}
    </div>
  );
}
