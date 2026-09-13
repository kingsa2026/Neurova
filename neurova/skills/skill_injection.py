# -*- coding: utf-8 -*-
"""P1-6 技能注入：$mention 全文注入 + 清单预算（Codex skills 对齐）。

- parse_skill_mentions：用户消息里的 $skill-name / @skill-name mention 提取
- collect_skill_mention_docs：命中技能的 SKILL.md 指令体全文注入本轮
  （Codex 语义：mention 后把完整技能正文作为本 turn 的用户片段注入）
- render_skill_catalog：技能清单渲染（name+description），超预算降级为
  仅名清单（Codex 别名压缩同构）——供提示词注入技能目录使用，token 有界
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# $/@ 前缀 + 技能名（字母数字-下划线-连字符-中文）
_MENTION_RE = re.compile(r"[$@]([A-Za-z0-9_\-\u4e00-\u9fa5]+)")
_DEFAULT_CATALOG_BUDGET = 6000
_DEFAULT_DOC_BUDGET = 12000


def parse_skill_mentions(text: str) -> List[str]:
    """提取消息中的技能 mention（$name / @name），去重保序。"""
    if not text:
        return []
    seen: List[str] = []
    for m in _MENTION_RE.finditer(str(text)):
        name = m.group(1)
        if name and name not in seen:
            seen.append(name)
    return seen


def _skill_doc_text(skill: Any) -> str:
    """鸭子类型取技能指令体全文：doc_text → skill_dir/SKILL.md → description。"""
    doc = getattr(skill, "doc_text", None)
    if isinstance(doc, str) and doc.strip():
        return doc
    for holder in (skill, getattr(skill, "_bridged", None)):
        executor = getattr(holder, "_executor", None) or holder
        skill_dir = getattr(executor, "skill_dir", None)
        if skill_dir:
            try:
                doc = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
                if doc.strip():
                    return doc
            except (OSError, AttributeError, TypeError):
                pass
    return str(getattr(skill, "description", "") or "")


def collect_skill_mention_docs(
    registry: Any, mentions: List[str], max_chars: int = _DEFAULT_DOC_BUDGET
) -> str:
    """按 mention 收集技能指令体全文块；无命中返回空串。

    名字解析优先精确匹配，其次前缀/包含匹配（@web 会命中 web-search）。
    """
    if not registry or not mentions:
        return ""
    skills = getattr(registry, "skills", None) or {}
    blocks: List[str] = []
    used = 0
    for mention in mentions:
        skill = skills.get(mention)
        if skill is None:
            low = mention.lower()
            for name, cand in skills.items():
                nl = str(name).lower()
                if nl.startswith(low) or low in nl:
                    skill = cand
                    break
        if skill is None:
            continue
        doc = _skill_doc_text(skill).strip()
        if not doc:
            continue
        block = f"[技能说明 {getattr(skill, 'name', mention)}]\n{doc}"
        size = len(block)
        if used + size > max_chars:
            if used >= max_chars // 2:
                # 预算已过半：后续条目整体截停
                logger.info("技能 mention 注入达预算截断: mention=%s", mention)
                break
            # 当前条目过大：跳过它继续尝试更小的
            continue
        blocks.append(block)
        used += size
    return "\n\n".join(blocks)


def render_skill_catalog(registry: Any, max_chars: int = _DEFAULT_CATALOG_BUDGET) -> str:
    """技能清单渲染：name — description 行；超预算降级为仅名清单（别名压缩）。"""
    skills = getattr(registry, "skills", None) or {}
    if not skills:
        return ""
    lines = [
        f"- {name} — {str(getattr(s, 'description', '') or '')[:120]}"
        for name, s in skills.items()
    ]
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    # 别名压缩：丢描述只留名字（模型仍能感知技能存在并主动询问）
    alias = "\n".join(f"- {name}" for name in skills.keys())
    return alias[:max_chars]


def inject_skill_mentions(
    user_input: str, registry: Any, max_chars: int = _DEFAULT_DOC_BUDGET
) -> str:
    """入口：无 registry/无 mention/无命中时原样返回（零副作用）。"""
    mentions = parse_skill_mentions(user_input or "")
    if not mentions or registry is None:
        return user_input or ""
    docs = collect_skill_mention_docs(registry, mentions, max_chars=max_chars)
    if not docs:
        return user_input or ""
    return f"{user_input}\n\n{docs}"
