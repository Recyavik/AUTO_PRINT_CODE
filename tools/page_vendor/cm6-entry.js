// CodeMirror 6 для экрана урока: только то, что нужно редактору кода на странице (без интернета —
// собирается в один файл autoprint/efir/page/vendor/cm6.js: npm install && npm run build).
export {EditorView, keymap, lineNumbers, gutter, GutterMarker, Decoration, drawSelection, highlightActiveLine,
        ViewPlugin} from "@codemirror/view";
export {EditorState, StateField, StateEffect, RangeSetBuilder, Compartment} from "@codemirror/state";
export {history, defaultKeymap, historyKeymap, indentWithTab} from "@codemirror/commands";
export {syntaxHighlighting, HighlightStyle, indentUnit, bracketMatching} from "@codemirror/language";
export {tags} from "@lezer/highlight";
export {python} from "@codemirror/lang-python";
export {javascript} from "@codemirror/lang-javascript";
export {html} from "@codemirror/lang-html";
export {css} from "@codemirror/lang-css";
export {java} from "@codemirror/lang-java";
export {cpp} from "@codemirror/lang-cpp";
export {sql} from "@codemirror/lang-sql";
export {json} from "@codemirror/lang-json";
