"""План урока и уроки по нему (без Qt).

План — обычный урок (Template) с kind == "plan": этапы с минутами, видом, разделом, пометкой и видео зарядки,
а под этапами — заготовки (заметки, код, картинки), которые копируются в новый урок один раз. Урок по плану
хранит plan_id, а каждый его этап — link на этап плана. После любой правки плана sync_topic приводит этапы
урока к плану: названия, минуты, вид, порядок — как в плане; содержание урока остаётся его собственным.

Этап убрали из плана — его блоки в уроке не пропадают: уезжают в конец предыдущего этапа после
заметки-разделителя «Из этапа «X», которого больше нет в плане» (у разделителя link = id убранного этапа).
Этап вернули («Вернуть» на странице плана — тот же id) — блоки после разделителя возвращаются под него.
"""
from __future__ import annotations

import copy

from .storage import BLOCK_MARKDOWN, BLOCK_STAGE, KIND_PLAN, Block, Template, new_id

SYNC_FIELDS = ("title", "minutes", "stage_kind", "part", "text", "exercise")
MOVED_NOTE = "Из этапа «{title}», которого больше нет в плане"


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold().replace("ё", "е")


def _split(blocks: list[Block]) -> tuple[list[Block], list[tuple[Block, list[Block]]]]:
    """→ (блоки до первого этапа, [(этап, его блоки)])."""
    intro: list[Block] = []
    groups: list[tuple[Block, list[Block]]] = []
    for b in blocks:
        if b.type == BLOCK_STAGE:
            groups.append((b, []))
        elif groups:
            groups[-1][1].append(b)
        else:
            intro.append(b)
    return intro, groups


def _is_divider(b: Block) -> bool:
    return b.type == BLOCK_MARKDOWN and bool(b.link)


def _signature(t: Template) -> list:
    return [t.look, t.plan_id] + [(b.id, b.type, b.title, b.minutes, b.stage_kind, b.part, b.text, b.exercise, b.link,
                                   b.role) for b in t.blocks]


def _copy_block(b: Block) -> Block:
    c = copy.deepcopy(b)
    c.id = new_id()
    c.link = ""
    return c


def sync_topic(topic: Template, plan: Template) -> bool:
    """Этапы урока — как в плане (поля SYNC_FIELDS, порядок, новые и убранные этапы), оформление — как у плана.
    → True, если урок изменился."""
    before = _signature(topic)
    intro, groups = _split(topic.blocks)
    plan_stages = [b for b in plan.blocks if b.type == BLOCK_STAGE]
    plan_ids = {s.id for s in plan_stages}
    by_link: dict[str, tuple[Block, list[Block]]] = {}
    for g in groups:
        if g[0].link in plan_ids and g[0].link not in by_link:
            by_link[g[0].link] = g
    # этап вернули в план: блоки после его разделителя возвращаются под него
    restored: dict[str, list[Block]] = {}
    for _st, content in groups:
        i = 0
        while i < len(content):
            b = content[i]
            if _is_divider(b) and b.link in plan_ids and b.link not in by_link:
                j = i + 1
                while j < len(content) and not _is_divider(content[j]):
                    j += 1
                restored.setdefault(b.link, []).extend(content[i + 1:j])
                del content[i:j]
                continue
            i += 1
    # новый порядок — по плану
    out: list[tuple[Block, list[Block]]] = []
    out_by_link: dict[str, tuple[Block, list[Block]]] = {}
    for ps in plan_stages:
        g = by_link.get(ps.id)
        if g is None:
            g = (Block(BLOCK_STAGE, "", id=new_id(), link=ps.id), [])
        st, content = g
        for f in SYNC_FIELDS:
            setattr(st, f, getattr(ps, f))
        st.link = ps.id
        content.extend(restored.get(ps.id, []))
        out.append((st, content))
        out_by_link[ps.id] = out[-1]
    # этапов урока, которых в плане нет, — блоки в предыдущий оставшийся этап (нет такого — в первый)
    homeless: list[Block] = []
    last_kept: tuple[Block, list[Block]] | None = None
    pending: list[tuple[Block, list[Block]]] = []          # этапы до первого оставшегося
    for st, content in groups:
        if by_link.get(st.link) is not None and by_link[st.link][0] is st:
            last_kept = out_by_link[st.link]
            continue
        if not content:
            continue
        moved = [Block(BLOCK_MARKDOWN, MOVED_NOTE.format(title=st.title or "Этап"), role="text", link=st.link)] + content
        if last_kept is not None:
            last_kept[1].extend(moved)
        else:
            pending.append((st, moved))
    for _st, moved in pending:
        if out:
            out[0][1].extend(moved)
        else:
            homeless.extend(moved)
    blocks = list(intro) + homeless
    for st, content in out:
        blocks.append(st)
        blocks.extend(content)
    topic.blocks[:] = blocks
    topic.plan_id = plan.id
    if plan.look:
        topic.look = plan.look
    return _signature(topic) != before


def link_topic(topic: Template, plan: Template) -> list[str]:
    """Первая привязка урока к плану (ответ нейросети, «Привязать к плану»): этапы сопоставляются по названию,
    остальные — по порядку среди этапов того же вида. → замечания."""
    _intro, groups = _split(topic.blocks)
    plan_stages = [b for b in plan.blocks if b.type == BLOCK_STAGE]
    match: dict[str, Block] = {}
    used: set[str] = set()
    for st, _c in groups:
        ps = next((p for p in plan_stages if p.id not in used and _norm(p.title) == _norm(st.title)), None)
        if ps is not None:
            match[st.id] = ps
            used.add(ps.id)
    for kind in {p.stage_kind for p in plan_stages}:
        rest_t = [st for st, _c in groups if st.id not in match and st.stage_kind == kind]
        rest_p = [p for p in plan_stages if p.id not in used and p.stage_kind == kind]
        for st, ps in zip(rest_t, rest_p):
            match[st.id] = ps
            used.add(ps.id)
    notes: list[str] = []
    last: Block | None = None
    first_plan = plan_stages[0] if plan_stages else None
    pending: list[str] = []
    for st, content in groups:
        ps = match.get(st.id)
        st.link = ps.id if ps is not None else ""
        if ps is not None:
            last = ps
            for name in pending:
                notes.append(f"Этап «{name}» не нашёлся в плане — его заметки перенесены в «{ps.title}»")
            pending = []
        elif content:
            if last is not None:
                notes.append(f"Этап «{st.title}» не нашёлся в плане — его заметки перенесены в «{last.title}»")
            else:
                pending.append(st.title)
    if pending and first_plan is not None:
        notes += [f"Этап «{n}» не нашёлся в плане — его заметки перенесены в «{first_plan.title}»" for n in pending]
    for ps in plan_stages:
        if ps.id not in used and not ps.stage_kind:
            notes.append(f"Этап плана «{ps.title}» в ответе пустой")
    topic.plan_id = plan.id
    sync_topic(topic, plan)
    return notes


def plan_from_lesson(t: Template) -> Template:
    """«Сделать из этапов план»: новый план с копиями этапов урока (без заметок); урок привязывается к нему."""
    stages = [b for b in t.blocks if b.type == BLOCK_STAGE]
    p = Template(f"План: {t.title}", [_copy_block(b) for b in stages], kind=KIND_PLAN, look=t.look)
    for b, pb in zip(stages, p.blocks):
        b.link = pb.id
    t.plan_id = p.id
    return p


def new_topic(plan: Template, title: str = "Новый урок") -> Template:
    """Новый урок по плану: этапы плана со связью и копии его заготовок; без заготовок — пустая «Говоришь»
    (под перерывом — ничего), перед уроком — заготовки плана до первого этапа или пустая «Цель урока»."""
    intro, groups = _split(plan.blocks)
    blocks = [_copy_block(b) for b in intro] or [Block(BLOCK_MARKDOWN, "", role="goal")]
    for ps, content in groups:
        st = Block(BLOCK_STAGE, "", link=ps.id)
        for f in SYNC_FIELDS:
            setattr(st, f, getattr(ps, f))
        blocks.append(st)
        if content:
            blocks.extend(_copy_block(b) for b in content)
        elif ps.stage_kind != "break":
            blocks.append(Block(BLOCK_MARKDOWN, "", role="say"))
    return Template(title, blocks, plan_id=plan.id, look=plan.look)


def unlink(topic: Template) -> None:
    """Урок становится обычным: этапы остаются, правятся в самом уроке."""
    topic.plan_id = ""
    for b in topic.blocks:
        b.link = ""
