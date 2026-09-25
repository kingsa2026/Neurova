# -*- coding: utf-8 -*-
"""反思「进视图才记账」的判据与降档兜底（Issue #90 · 决策 D5，B6-11）。

## 根因（不是"少传一个参数"）

账目原来记在**选中**那一刻：`select_reflection_logs` 选出条目后立刻
`mark_injected_logs`（pending→applied + 挂本轮痕迹）。而"能不能到模型面前"
要过池的相关性门槛（反思归档优先级 60，低于记忆 70 等），两件事之间没有任何因果。

实测（真 `build_context`，无关输入）：`status=applied`、痕迹里有该 id，
**视图里一行 `[反思]` 都没有**。后果二重 —— ① `applied` 被谎报；② 效力裁决的
输入（assistant metadata 的 `injected_reflections` → `/chat/feedback` 的
like→validated / dislike→降置信）建立在幻影注入上，用户对一个从未见过的教训投票。

## 「进视图」的客观判据

判据取**视图注入面里有没有这条教训的文本**，而不是"draw 取出了它"：

- draw 之后还有一步 `compress_envelope` 确定性淘汰，`<history>` 块可能被整块丢弃
  ——那时条目确实没到模型面前（取"draw 输出集合"会把这一步漏掉）；
- 非池分支的反思由注入器**另行渲染**（`_build_reflection_context` 自带一趟读取），
  条目身份与文本也仍要按同一条规则判定。

注入面 = 各条消息的**信封块**（`parse_envelope`，免疫句与标签不计）或消息正文本身
——用户原文不属于注入面（`strip_envelope` 之后的部分），否则"模型看过用户说的这句话"
会被算成"教训进过视图"。

文本比对取教训的**首段**（`VIEW_MATCH_CHARS`）：渲染侧有封顶（信封块 200 /
system 行 400 字符，单源见 `context/models.py`），取全长比对会在截断形态下漏判。

## 降档兜底

连续 `VIEW_MISS_LIMIT` 轮被选中却从未进视图的条目走**既有**降档单一事实源
`GrowthLogManager.register_negative_feedback`（只降不删，跌破阈值转 rejected）。
不新建降档实现：写了第二份置信度账，两处迟早对不上（修复教义第 6 条）。
rejected 条目脱离恒定注入（`select_reflection_logs` 过滤），池内原文仍在
（无损归档语义不变）——这就是"低相关教训的退出路径"。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

#: 连续未进视图的降档阈值："N 轮未进视图则降档"（审计 §10 D5）。
#: 取 3 与反思注入的每轮选条量同阶：单轮抖动不会触发，持续不相关才降档。
VIEW_MISS_LIMIT = 3

#: 文本比对的教训首段长度。必须短于渲染侧最紧的封顶（信封块 200 字符），
#: 否则截断形态下会漏判"其实进了视图"。
VIEW_MATCH_CHARS = 32


def lessonHead(lesson: Any) -> str:
    """教训正文的比对首段（单一出处：判据与测试都取它，不各写一份截断长度）。"""
    return str(lesson or "")[:VIEW_MATCH_CHARS]


def injectionSurface(messages: Iterable[Dict[str, Any]]) -> str:
    """本轮**模型实际看到**的注入面文本（信封块优先，否则消息正文）。

    信封里不含用户原文（`build_envelope` 的块全在 `<system-reminder>` 内，
    用户输入拼在信封之后），故取块内容即为注入面本身。
    """
    from neurova.context.envelope import parse_envelope

    parts: List[str] = []
    for msg in messages or []:
        content = str((msg or {}).get("content", "") or "")
        blocks = parse_envelope(content)
        parts.append("\n".join(blocks.values()) if blocks else content)
    return "\n".join(parts)


def enteredViewIds(
    messages: Iterable[Dict[str, Any]],
    lessons: Sequence[Tuple[str, Any]],
) -> Set[str]:
    """`[(条目 id, 教训正文)]` → 真进了视图的 id 集（判据唯一实现处）。"""
    surface = injectionSurface(messages)
    entered: Set[str] = set()
    for entryId, lesson in lessons:
        head = lessonHead(lesson)
        if head and head in surface:
            entered.add(str(entryId))
    return entered
