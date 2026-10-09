// Редактор блока кода (CodeMirror 6 — тот же, что в JupyterLab): подсветка языка, выделение, подсветка напечатанного.
import { languages } from "@codemirror/language-data";
import { EditorSelection, type Extension, StateEffect, StateField } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView } from "@codemirror/view";
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { useEffect, useMemo, useRef, useState } from "react";

// ---- подсветка напечатанной части: [from, to) — набрано, остальное — ещё нет
const setTyped = StateEffect.define<[number, number] | null>();
const typedField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setTyped)) continue;
      const len = tr.state.doc.length;
      const r = e.value;
      deco = r && r[1] > r[0] && r[0] < len
        ? Decoration.set([Decoration.mark({ class: "cm-typed" }).range(r[0], Math.min(r[1], len))])
        : Decoration.none;
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

const langCache = new Map<string, Promise<Extension | null>>();
function loadLang(name: string): Promise<Extension | null> {
  let p = langCache.get(name);
  if (!p) {
    const desc = languages.find((l) => l.name.toLowerCase() === name || l.alias.includes(name) || l.extensions.includes(name));
    p = desc ? desc.load().then((s) => s as Extension) : Promise.resolve(null);
    langCache.set(name, p);
  }
  return p;
}

const dark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

interface Props {
  value: string;
  lang: string;
  sel: number[];
  zoom: number;
  typed: [number, number] | null;
  onChange: (text: string) => void;
  onSelection: (sel: number[]) => void;
  onFocus: () => void;
}

export function CodeEditor({ value, lang, sel, zoom, typed, onChange, onSelection, onFocus }: Props) {
  const ref = useRef<ReactCodeMirrorRef>(null);
  const [langExt, setLangExt] = useState<Extension | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(dark() ? "dark" : "light");

  useEffect(() => {
    let alive = true;
    void loadLang((lang || "").toLowerCase()).then((ext) => alive && setLangExt(ext));
    return () => { alive = false; };
  }, [lang]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setTheme(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  useEffect(() => {
    ref.current?.view?.dispatch({ effects: setTyped.of(typed) });
  }, [typed?.[0], typed?.[1]]);

  // выделение пришло извне (другой блок стал активным → выделение здесь снято)
  useEffect(() => {
    const view = ref.current?.view;
    if (!view) return;
    const r = view.state.selection.main;
    const want = sel.length === 2 ? sel : [];
    const has = r.empty ? [] : [r.from, r.to];
    if (want.length === 0 && has.length) view.dispatch({ selection: EditorSelection.cursor(r.head) });
  }, [sel[0], sel[1]]);

  const extensions = useMemo(() => [
    typedField,
    EditorView.lineWrapping,
    EditorView.theme({ "&": { fontSize: `${(13.5 * zoom) / 100}px` } }),
    ...(langExt ? [langExt] : []),
  ], [langExt, zoom]);

  return (
    <CodeMirror
      ref={ref}
      value={value}
      theme={theme}
      extensions={extensions}
      basicSetup={{ foldGutter: false, highlightActiveLine: false, autocompletion: false, searchKeymap: true }}
      onChange={onChange}
      onFocus={onFocus}
      onCreateEditor={(view) => {
        if (sel.length === 2 && sel[1] <= view.state.doc.length) {
          view.dispatch({ selection: EditorSelection.range(sel[0], sel[1]) });
        }
        if (typed) view.dispatch({ effects: setTyped.of(typed) });
      }}
      onUpdate={(u) => {
        if (!u.selectionSet || !u.view.hasFocus) return;
        const r = u.state.selection.main;
        onSelection(r.empty ? [] : [r.from, r.to]);
      }}
    />
  );
}
