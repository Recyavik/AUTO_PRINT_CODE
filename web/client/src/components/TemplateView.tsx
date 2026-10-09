// Образец — лента блоков сверху вниз: текст (Markdown с ролью) и код.
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useEffect, useMemo, useRef, useState } from "react";
import { stripComments } from "../../../shared/comments.ts";
import {
  BLOCK_CODE, BLOCK_MARKDOWN, type Block, blockTitle, makeBlock, ROLES, type Settings, type Template, typingSlice,
} from "../../../shared/model.ts";
import { findSelection, PRINT_MODES } from "../../../shared/textprint.ts";
import { getState, updateBlock, updateTemplate, useApp } from "../api.ts";
import { CodeEditor } from "./CodeEditor.tsx";
import { Menu, type MenuItem } from "./Menu.tsx";

// ссылки из текста блока — в новой вкладке, а не вместо страницы приложения
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

const PRINT_AS_TIP = "Как печатать этот блок:\n" +
  "• как Markdown — исходник с ## и `…` (markdown-ячейка Jupyter, .md-файл);\n" +
  "• простым текстом — без разметки (Блокнот, Word, чат);\n" +
  "• комментарием в коде — каждая строка с # или // по языку блока кода рядом";

const LANGS = ["python", "javascript", "typescript", "java", "c", "cpp", "csharp", "go", "rust", "php", "kotlin",
  "swift", "sql", "html", "css", "json", "yaml", "bash", "text"];

export function TemplateView({ template }: { template: Template }) {
  const settings = useApp((s) => s.settings)!;
  const engine = useApp((s) => s.engine);
  const focus = useApp((s) => s.focus);
  const feed = useRef<HTMLDivElement>(null);
  let codeN = 0;

  // хоткей «следующий блок» — прокрутить к нему
  useEffect(() => {
    if (!focus || focus.tid !== template.id) return;
    feed.current?.querySelector(`[data-bid="${focus.bid}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus?.n]);

  const save = (t: Template, delay?: number) => updateTemplate(t, delay);
  const arm = (bid: string) => {
    const t = getState().templates.find((x) => x.id === template.id) ?? template;
    if (t.active_block === bid) return;
    // выделение остаётся только в активном блоке
    save({ ...t, active_block: bid, blocks: t.blocks.map((b) => (b.id !== bid && b.sel.length ? { ...b, sel: [] } : b)) }, 0);
  };
  const insertAt = (idx: number, type: string) => {
    const b = makeBlock(type, "", type === BLOCK_CODE ? { lang: lastLang(template, idx) } : {});
    const blocks = [...template.blocks];
    blocks.splice(idx, 0, b);
    save({ ...template, blocks, active_block: type === BLOCK_CODE ? b.id : template.active_block }, 0);
  };
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= template.blocks.length) return;
    const blocks = [...template.blocks];
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    save({ ...template, blocks }, 0);
  };
  const remove = (b: Block) => {
    if (b.text.trim() && !confirm(`Удалить блок «${blockTitle(b)}»?`)) return;
    save({ ...template, blocks: template.blocks.filter((x) => x.id !== b.id),
      active_block: template.active_block === b.id ? "" : template.active_block }, 0);
  };

  return (
    <div className="feed" ref={feed}>
      {template.blocks.length === 0 && <div className="empty">Образец пуст. Добавьте текст условия и блок кода.</div>}
      {template.blocks.map((b, i) => {
        const n = b.type === BLOCK_CODE ? ++codeN : 0;
        const job = engine.job;
        const typed: [number, number] | null = job && job.tid === template.id && job.bid === b.id && !settings.strip_comments
          && engine.state !== "idle" ? [job.base, job.base + engine.pos] : null;
        return (
          <BlockView key={b.id} block={b} codeNumber={n} armed={template.active_block === b.id} settings={settings}
            typed={typed} onChange={(patch, delay) => updateBlock(template.id, b.id, patch, delay)} onArm={() => arm(b.id)} onMove={(d) => move(i, d)}
            onInsert={(after, type) => insertAt(after ? i + 1 : i, type)} onDelete={() => remove(b)} />
        );
      })}
      <div className="add">
        <button className="btn" onClick={() => insertAt(template.blocks.length, BLOCK_MARKDOWN)}>＋ Текст (Markdown)</button>
        <button className="btn" onClick={() => insertAt(template.blocks.length, BLOCK_CODE)}>＋ Блок кода</button>
      </div>
    </div>
  );
}

function lastLang(t: Template, idx: number): string {
  for (let i = idx - 1; i >= 0; i--) if (t.blocks[i].type === BLOCK_CODE) return t.blocks[i].lang;
  return t.blocks.find((b) => b.type === BLOCK_CODE)?.lang ?? "python";
}

interface BlockProps {
  block: Block;
  codeNumber: number;
  armed: boolean;
  settings: Settings;
  typed: [number, number] | null;
  onChange: (patch: Partial<Block>, delay?: number) => void;   // правка поверх последней версии блока
  onArm: () => void;
  onMove: (d: number) => void;
  onInsert: (after: boolean, type: string) => void;
  onDelete: () => void;
}

function BlockView({ block: b, codeNumber, armed, settings, typed, onChange, onArm, onMove, onInsert, onDelete }: BlockProps) {
  const el = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const isCode = b.type === BLOCK_CODE;
  const role = ROLES[b.role] ?? ROLES.text;

  // Ctrl/Shift + колёсико — масштаб блока (обработчик не пассивный, чтобы не масштабировалась вся страница)
  useEffect(() => {
    const node = el.current!;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.shiftKey) return;
      e.preventDefault();
      const zoom = Math.max(50, Math.min(300, b.zoom + (e.deltaY < 0 ? 10 : -10)));
      if (zoom !== b.zoom) onChange({ zoom });
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [b]);

  const kindValue = isCode ? "code" : b.role;
  const setKind = (v: string) => {
    if (v === "code") onChange({ type: BLOCK_CODE }, 0);
    else onChange({ type: BLOCK_MARKDOWN, role: v }, 0);
  };

  const insertMenu = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ x: r.left, y: r.bottom + 4, items: [
      { label: "↑ 📝 Текст выше", run: () => onInsert(false, BLOCK_MARKDOWN) },
      { label: "↑ 💻 Код выше", run: () => onInsert(false, BLOCK_CODE) },
      { label: "↓ 📝 Текст ниже", run: () => onInsert(true, BLOCK_MARKDOWN) },
      { label: "↓ 💻 Код ниже", run: () => onInsert(true, BLOCK_CODE) },
    ] });
  };

  return (
    <div ref={el} data-bid={b.id} className={`block${armed ? " armed" : ""}`}
      style={{ "--role": isCode ? undefined : role[2] } as React.CSSProperties}>
      <div className="block-head">
        <select value={kindValue} onChange={(e) => setKind(e.target.value)} title="Тип блока">
          {Object.entries(ROLES).map(([k, [icon, name]]) => <option key={k} value={k}>{icon} {name}</option>)}
          <option value="code">💻 Код</option>
        </select>
        <input className="title-edit" value={b.title} placeholder={blockTitle({ ...b, title: "" }, codeNumber)}
          title="Заголовок блока" onChange={(e) => onChange({ title: e.target.value })} />
        <button className={`btn small arm-btn${armed ? " on" : ""}`} onClick={onArm}
          title="Блок, который напечатается по хоткею">{armed ? "● Активный" : "▶ Печатать этот"}</button>
        {!isCode && (
          <select value={b.print_as in PRINT_MODES ? b.print_as : "markdown"} title={PRINT_AS_TIP}
            onChange={(e) => { onChange({ print_as: e.target.value }, 0); onArm(); }}>
            {Object.entries(PRINT_MODES).map(([k, name]) => <option key={k} value={k}>Печатать {name}</option>)}
          </select>
        )}
        {!isCode && b.sel.length === 2 && (
          <span className="info sel-info">· выделено строк: {b.text.slice(b.sel[0], b.sel[1]).replace(/\n+$/, "").split("\n").length}</span>
        )}
        {isCode && (
          <>
            <select value={b.lang} onChange={(e) => onChange({ lang: e.target.value }, 0)} title="Язык подсветки и комментариев">
              {[...new Set([b.lang, ...LANGS])].map((l) => <option key={l}>{l}</option>)}
            </select>
            <CodeInfo block={b} settings={settings} />
          </>
        )}
        <span className="grow" />
        {b.zoom !== 100 && (
          <button className="btn small ghost" title="Обычный размер" onClick={() => onChange({ zoom: 100 })}>{b.zoom}%</button>
        )}
        <span className="tools">
          <button className="btn small ghost" title="Выше" onClick={() => onMove(-1)}>▲</button>
          <button className="btn small ghost" title="Ниже" onClick={() => onMove(+1)}>▼</button>
          <button className="btn small ghost" title="Вставить блок" onClick={insertMenu}>＋</button>
          <button className="btn small ghost" title="Удалить блок" onClick={onDelete}>✕</button>
        </span>
      </div>
      {isCode ? (
        <div className="code-wrap">
          <CodeEditor value={b.text} lang={b.lang} sel={armed ? b.sel : []} zoom={b.zoom} typed={typed}
            onFocus={onArm}
            onChange={(text) => onChange({ text })}
            onSelection={(sel) => {
              if (sel.join() !== b.sel.join()) onChange({ sel }, 250);
            }} />
        </div>
      ) : (
        <MarkdownBlock block={b} onChange={onChange} onArm={onArm} />
      )}
      {menu && <Menu {...menu} onClose={() => setMenu(null)} />}
    </div>
  );
}

function CodeInfo({ block: b, settings }: { block: Block; settings: Settings }) {
  const text = useMemo(() => {
    let [t] = typingSlice(b.text, b.sel, settings.selection_whole_lines);
    if (settings.strip_comments) t = stripComments(t, b.lang)[0];
    return t;
  }, [b.text, b.sel, b.lang, settings.selection_whole_lines, settings.strip_comments]);
  const lines = text ? text.split("\n").length : 0;
  const part = b.sel.length === 2 ? "выделение" : "весь блок";
  return <span className="info">· {part}: {lines} стр., {text.length} симв.{settings.strip_comments ? " без комм." : ""}</span>;
}

function MarkdownBlock({ block: b, onChange, onArm }: { block: Block; onChange: (patch: Partial<Block>, delay?: number) => void; onArm: () => void }) {
  const [editing, setEditing] = useState(!b.text.trim());
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(b.text, { async: false, gfm: true, breaks: false })), [b.text]);
  const ta = useRef<HTMLTextAreaElement>(null);
  const view = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (editing && ta.current) {
      ta.current.style.height = "auto";
      ta.current.style.height = ta.current.scrollHeight + 4 + "px";
    }
  }, [editing, b.text]);

  // выделение: печатаются только выделенные строки (как в блоке кода)
  const setSel = (sel: number[]) => {
    if (sel.join() !== b.sel.join()) onChange({ sel }, 250);
  };
  const selectionFromView = () => {
    const el = view.current;
    const s = window.getSelection();
    if (!el || !s || !s.rangeCount) return;
    if (s.isCollapsed) return setSel([]);
    const r = s.getRangeAt(0);
    if (!el.contains(r.commonAncestorContainer)) return;
    const pre = document.createRange();   // где началось выделение — если кусок встречается несколько раз
    pre.selectNodeContents(el);
    pre.setEnd(r.startContainer, r.startOffset);
    setSel(findSelection(b.text, s.toString(), pre.toString().length / Math.max(1, el.textContent?.length ?? 0)));
  };

  if (editing) {
    return (
      <textarea ref={ta} className="md-edit" value={b.text} autoFocus={!!b.text} spellCheck
        style={{ fontSize: `${(13.5 * b.zoom) / 100}px` }} placeholder="Текст в формате Markdown"
        onChange={(e) => onChange({ text: e.target.value })}
        onSelect={(e) => {
          const { selectionStart: a, selectionEnd: z } = e.currentTarget;
          setSel(z > a ? [a, z] : []);
        }}
        onBlur={() => b.text.trim() && setEditing(false)}
        onKeyDown={(e) => { if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur(); }} />
    );
  }
  return (
    <div ref={view} className="md-view" style={{ fontSize: `${(14 * b.zoom) / 100}px` }} title="Щёлкните дважды, чтобы изменить"
      onMouseUp={selectionFromView} onKeyUp={selectionFromView}
      onClick={(e) => !(e.target as HTMLElement).closest("a") && onArm()}
      onDoubleClick={() => { setSel([]); setEditing(true); }} dangerouslySetInnerHTML={{ __html: html }} />
  );
}
