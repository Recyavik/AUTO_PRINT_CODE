"""Подсветка синтаксиса для редактора образца (Pygments → QSyntaxHighlighter)."""
from __future__ import annotations

from bisect import bisect_right

from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.lexers.special import TextLexer
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

LANGUAGES = ["python", "javascript", "typescript", "html", "css", "sql", "java", "c", "cpp",
             "csharp", "go", "rust", "php", "bash", "powershell", "json", "yaml", "markdown", "text"]

# Редактор образца — по теме окна: тёмная в духе One Dark; светлая — сиреневая подложка на тон темнее панели
# (код выделяется), цвета подсветки — тёмные, читаемые на светлом. set_editor_theme() переключает на лету.
EDITOR_THEMES = {
    "dark": {
        "EDITOR_BG": "#1e2229", "EDITOR_FG": "#d7dae0", "EDITOR_LINE": "#2a2f38",
        "EDITOR_GUTTER": "#5c6370", "EDITOR_GUTTER_SEL": "#e5c07b",
        "STYLE": [
            (Comment, "#7f848e", False, True),
            (Keyword, "#c678dd", False, False),
            (Name.Builtin, "#56b6c2", False, False),
            (Name.Function, "#61afef", False, False),
            (Name.Class, "#e5c07b", True, False),
            (Name.Decorator, "#e5c07b", False, False),
            (Name.Tag, "#e06c75", False, False),
            (Name.Attribute, "#d19a66", False, False),
            (String, "#98c379", False, False),
            (Number, "#d19a66", False, False),
            (Operator, "#56b6c2", False, False),
        ],
    },
    "light": {
        "EDITOR_BG": "#CEC3E2", "EDITOR_FG": "#241A38", "EDITOR_LINE": "#C3B6DB",
        "EDITOR_GUTTER": "#7A6F96", "EDITOR_GUTTER_SEL": "#7A3FE0",
        "STYLE": [
            (Comment, "#6C6386", False, True),
            (Keyword, "#8A23B5", False, False),
            (Name.Builtin, "#0B6E7D", False, False),
            (Name.Function, "#2552B5", False, False),
            (Name.Class, "#8A5A00", True, False),
            (Name.Decorator, "#8A5A00", False, False),
            (Name.Tag, "#B3261E", False, False),
            (Name.Attribute, "#9A4F00", False, False),
            (String, "#2E6B1F", False, False),
            (Number, "#9A4F00", False, False),
            (Operator, "#0B6E7D", False, False),
        ],
    },
}
EDITOR_BG = EDITOR_FG = EDITOR_LINE = EDITOR_GUTTER = EDITOR_GUTTER_SEL = ""
_FORMATS: list = []


def _fmt(color: str, bold: bool, italic: bool) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    f.setFontItalic(italic)
    return f


def set_editor_theme(name: str) -> None:
    """Цвета редактора и подсветки — по теме окна (dark | light). Открытые редакторы перекрашивает окно."""
    global _FORMATS
    t = EDITOR_THEMES.get(name, EDITOR_THEMES["dark"])
    globals().update({k: v for k, v in t.items() if k != "STYLE"})
    _FORMATS = [(tt, _fmt(c, b, i)) for tt, c, b, i in t["STYLE"]]


set_editor_theme("dark")


def _format_for(ttype) -> QTextCharFormat | None:
    while ttype is not Token:
        for tt, f in _FORMATS:
            if ttype is tt:
                return f
        ttype = ttype.parent
    return None


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, lang: str = "python") -> None:
        super().__init__(document)
        self._starts: list[int] = []
        self._spans: list[tuple[int, int, QTextCharFormat]] = []
        self._lexer = TextLexer()
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._refresh)
        document.contentsChange.connect(self._on_change)
        self.set_language(lang)

    def set_language(self, lang: str) -> None:
        try:
            self._lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
        except Exception:
            self._lexer = TextLexer()
        self._refresh()

    def _on_change(self, _pos, removed, added):
        if not self._busy and (removed or added):
            self._timer.start()

    def refresh(self) -> None:
        """Перекрасить заново (сменили тему окна)."""
        self._refresh()

    def _refresh(self) -> None:
        self._relex()
        self._busy = True
        try:
            self.rehighlight()
        finally:
            self._busy = False

    def _relex(self) -> None:
        text = self.document().toPlainText()
        spans = []
        pos = 0
        for ttype, value in lex(text, self._lexer):
            f = _format_for(ttype)
            if f is not None and value:
                spans.append((pos, pos + len(value), f))
            pos += len(value)
        self._spans = spans
        self._starts = [s for s, _, _ in spans]

    def highlightBlock(self, text: str) -> None:
        start = self.currentBlock().position()
        end = start + len(text)
        i = max(0, bisect_right(self._starts, start) - 1)
        while i < len(self._spans):
            s, e, f = self._spans[i]
            if s >= end:
                break
            if e > start:
                a, b = max(s, start), min(e, end)
                self.setFormat(a - start, b - a, f)
            i += 1
