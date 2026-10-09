// Библиотека образцов: поиск, новый, импорт, контекстное меню (переименовать, дублировать, экспорт, удалить).
import { useState } from "react";
import { exportIpynb, exportJson, importFile } from "../../../shared/importers.ts";
import {
  BLOCK_CODE, BLOCK_MARKDOWN, codeBlocks, freshIds, makeBlock, makeTemplate, type Template,
} from "../../../shared/model.ts";
import { addTemplate, deleteTemplate, openTab, toast, updateTemplate, useApp } from "../api.ts";
import { Menu, type MenuItem } from "./Menu.tsx";

export function download(name: string, content: string, type = "application/json"): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const safeName = (s: string) => s.replace(/[\\/:*?"<>|]+/g, "_").trim() || "образец";

export function exportTemplate(t: Template, fmt: "ipynb" | "json"): void {
  download(`${safeName(t.title)}.${fmt}`, fmt === "ipynb" ? exportIpynb(t) : exportJson(t));
}

export function newTemplate(): void {
  const title = prompt("Название образца:", "Новое занятие")?.trim();
  if (!title) return;
  addTemplate(makeTemplate(title, [makeBlock(BLOCK_MARKDOWN, "## Задача 1\n\n", { role: "task" }), makeBlock(BLOCK_CODE, "")]));
}

export async function importFiles(files: FileList | File[]): Promise<void> {
  for (const f of Array.from(files)) {
    try {
      const t = importFile(f.name, await f.text());
      if (!t.blocks.length) {
        toast(`${f.name}: нет ячеек для импорта.`, "warn");
        continue;
      }
      addTemplate(t);
      toast(`Импортировано: ${t.title} (${t.blocks.length} блоков)`);
    } catch (e) {
      toast(`${f.name}: ${(e as Error).message}`, "warn");
    }
  }
}

export function Library({ fileInput }: { fileInput: React.RefObject<HTMLInputElement | null> }) {
  const templates = useApp((s) => s.templates);
  const current = useApp((s) => s.settings?.current_tab);
  const [q, setQ] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const [renaming, setRenaming] = useState("");

  const query = q.trim().toLowerCase();
  const shown = templates.filter((t) => !query || t.title.toLowerCase().includes(query)
    || t.blocks.some((b) => b.text.toLowerCase().includes(query)));

  const context = (e: React.MouseEvent, t: Template) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: "Открыть", run: () => openTab(t.id) },
      { label: "Переименовать", run: () => setRenaming(t.id) },
      { label: "Дублировать", run: () => addTemplate({ ...freshIds(t), title: t.title + " (копия)" }) },
      { separator: true, label: "" },
      { label: "Экспорт в .ipynb…", run: () => exportTemplate(t, "ipynb") },
      { label: "Экспорт в .json…", run: () => exportTemplate(t, "json") },
      { separator: true, label: "" },
      { label: "Удалить…", danger: true, run: () => {
        if (confirm(`Удалить образец «${t.title}»? Это нельзя отменить.`)) deleteTemplate(t.id);
      } },
    ] });
  };

  return (
    <aside className="library"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); void importFiles(e.dataTransfer.files); }}>
      <input type="search" placeholder="Поиск по образцам…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="row">
        <button className="btn" onClick={newTemplate} title="Новый образец">＋ Новый</button>
        <button className="btn" onClick={() => fileInput.current?.click()} title="Импорт .ipynb, .md, .py, .json (или перетащите файлы сюда)">⇪ Импорт</button>
      </div>
      <div className="list">
        {shown.map((t) => (
          <div key={t.id} className={`item${t.id === current ? " current" : ""}`} onClick={() => openTab(t.id)}
            onContextMenu={(e) => context(e, t)} onDoubleClick={() => setRenaming(t.id)} title={t.title}>
            {renaming === t.id ? (
              <input type="text" defaultValue={t.title} autoFocus style={{ flex: 1 }}
                onClick={(e) => e.stopPropagation()}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v && v !== t.title) updateTemplate({ ...t, title: v }, 0);
                  setRenaming("");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  if (e.key === "Escape") setRenaming("");
                }} />
            ) : (
              <>
                <span className="title">{t.title}</span>
                <span className="meta">{codeBlocks(t).length}</span>
              </>
            )}
          </div>
        ))}
        {!shown.length && <div className="empty">{templates.length ? "Ничего не найдено" : "Образцов пока нет"}</div>}
      </div>
      <button className="btn ghost small" title="Служебный журнал помощника: старт, пауза, целевое окно, ошибки"
        onClick={() => window.open("/api/log", "_blank")}>Журнал работы</button>
      {menu && <Menu {...menu} onClose={() => setMenu(null)} />}
    </aside>
  );
}
