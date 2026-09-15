# -*- coding: utf-8 -*-
"""P1-6 技能注入：$mention 全文注入 + 清单预算。

- parse_skill_mentions：用户消息里的 $skill-name / @skill-name mention 提取
- collect_skill_mention_docs：命中技能的 SKILL.md 指令体全文注入本轮
- render_skill_catalog：技能清单渲染（name+description），超预算降级为
 仅名清单——供提示词注入技能目录使用，token 有界
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class QualityInfo:
    """技能质量读数（漏斗计数，SkillService usage 的只读视图）。"""

    applications: int = 0
    completions: int = 0
    fallbacks: int = 0

# $/@ 前缀 + 技能名（字母数字-下划线-连字符-中文）
_MENTION_RE = re.compile(r"[$@]([A-Za-z0-9_\-\u4e00-\u9fa5]+)")
_DEFAULT_CATALOG_BUDGET = 6000
_DEFAULT_DOC_BUDGET = 12000
_MAX_DESC_CHARS = 250


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
    registry: Any,
    mentions: List[str],
    max_chars: int = _DEFAULT_DOC_BUDGET,
    allowed_names: Optional[set] = None,
) -> str:
    """按 mention 收集技能指令体全文块；无命中返回空串。

    名字解析优先精确匹配，其次前缀/包含匹配（@web 会命中 web-search）。
    allowed_names（Wave H-W2 三层库）：非 None 时仅可见集内技能可注入正文
    ——mention 是全文泄露面，视图外技能即使 registry 有执行体也拒绝注入。
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
        _nm = str(getattr(skill, "name", "") or "")
        if allowed_names is not None and mention not in allowed_names and _nm not in allowed_names:
            logger.info("[技能注入] %s 不在本轮可见集，跳过正文注入", mention)
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


def render_skill_catalog(
    registry: Any,
    max_chars: int = _DEFAULT_CATALOG_BUDGET,
    max_lines: int = 30,
    user_input: str = "",
    trust_lookup: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """技能清单渲染。

    - 每行 `- name — description[:250]`（MAX_LISTING_DESC_CHARS 同值）
    - 行数超 max_lines：截断并在块尾提示未列数与发现途径
    - 总长超预算：别名压缩——丢描述保名字
    - model_invocable=False / enabled=False 的技能不进目录；paths 未激活的
      技能仅在**传入 user_input 时**过滤（常驻目录调用 user_input="" →
      字节稳定，尊重 build_context "system 会话内恒定"设计；工具面侧按
      真实轮次输入做 paths 门）
    """
    skills = getattr(registry, "skills", None) or {}
    if not skills:
        return ""

    lines: List[str] = []
    hidden = 0
    for name, s in skills.items():
        cfg = getattr(s, "config", None)
        if isinstance(cfg, dict) and cfg.get("model_invocable") is False:
            continue
        if getattr(s, "enabled", True) is False:
            continue
        if user_input and not match_skill_paths(s, user_input):
            continue
        desc = str(getattr(s, "description", "") or "")[:_MAX_DESC_CHARS]
        line = f"- {name} — {desc}" if desc else f"- {name}"
        # P0-2 消费面：进化产物未晋升前对模型软标注
        if trust_lookup is not None and trust_lookup(name) == "provisional":
            line += " (provisional)"
        lines.append(line)

    total = len(lines)
    if total == 0:
        return ""
    if total > max_lines:
        hidden = total - max_lines
        lines = lines[:max_lines]

    text = "\n".join(lines)
    if hidden:
        text += f"\n（还有 {hidden} 个技能未列出，可用 $技能名 显式调用）"
    if len(text) <= max_chars:
        return text
    # 别名压缩：丢描述只留名字（模型仍能感知技能存在并主动询问）
    names_only = [ln.split(" — ")[0] for ln in text.splitlines() if ln.startswith("- ")]
    tail = [ln for ln in text.splitlines() if not ln.startswith("- ")]
    alias = "\n".join(names_only + tail)
    return alias[:max_chars]


# ── P2-5 paths 条件激活 + P2-2 阶梯检索──

import fnmatch


def match_skill_paths(skill: Any, user_input: str) -> bool:
    """config.paths glob 条件激活。

    未设定 paths → 恒 True（存量技能行为零变化）；设定后，仅当本轮用户输入
    命中任一 glob（对输入里的文件名/路径 token 逐个 fnmatch，或整段子串命中）
    才视为激活——未激活技能不进目录、不进 function-calling 工具面。
    """
    cfg = getattr(skill, "config", None)
    patterns = cfg.get("paths") if isinstance(cfg, dict) else None
    if not patterns or not isinstance(patterns, list):
        return True
    text = str(user_input or "")
    tokens = re.split(r"[^A-Za-z0-9_\-\u4e00-\u9fa5./\\]", text)
    tokens = [t for t in tokens if t]
    for pat in patterns:
        p = str(pat)
        for tok in tokens:
            if fnmatch.fnmatch(tok, p) or fnmatch.fnmatch(tok.split("/")[-1], p):
                return True
        # 模式片段直接出现在输入里（如 "src/**" 命中含 src/ 的文本）
        stem = p.replace("*", "").strip("/\\")
        if stem and stem in text:
            return True
    return False


def score_skill_for_query(skill: Any, query: str, quality: Optional[Dict[str, Any]] = None) -> float:
    """关键词重合打分。

    quality 传入 {completions, fallbacks} 时叠加 ±min(n,5)*0.05 微调——
    """
    name = str(getattr(skill, "name", "") or "")
    desc = str(getattr(skill, "description", "") or "")
    cfg = getattr(skill, "config", None)
    when = str(cfg.get("when_to_use", "")) if isinstance(cfg, dict) else ""
    blob = f"{desc} {when}".lower()
    q = str(query or "").lower().strip()
    if not q:
        return 0.0
    tokens = sorted(set(re.split(r"[^a-z0-9\u4e00-\u9fa5_\-]", q)) - {""}, key=len, reverse=True)
    score = 0.0
    nl = name.lower()
    if nl and nl in q:
        score += 10.0
    for tok in tokens:
        if len(tok) < 2:
            continue
        if tok in nl:
            score += 4.0
        if tok in blob:
            score += 2.0
    if quality:
        score += min(int(quality.get("completions", 0) or 0), 5) * 0.05
        score -= min(int(quality.get("fallbacks", 0) or 0), 5) * 0.05
    return score


# 语义 cosine 计入排序的最低门槛
_SEMANTIC_FLOOR = 0.15


def quality_blocked(q: Optional[QualityInfo]) -> bool:
    """质量熔断判据：
    applications≥2 且（零完成 或 fallback 率>0.5）→ 本轮不得出现在模型工具面。
    无数据/样本不足一律放行（增量不下降：新技能冷启动零误杀）。"""
    if q is None or q.applications < 2:
        return False
    return q.completions == 0 or (q.fallbacks / q.applications) > 0.5


def select_skills_for_turn(
    skills: Dict[str, Any],
    user_input: str,
    max_skills: int = 20,
    quality_lookup: Optional[Callable[[str], Optional[QualityInfo]]] = None,
    semantic_scores: Optional[Dict[str, float]] = None,
) -> List[str]:
    """P2-2 阶梯检索：≤max 全量（现状语义）；>max 精确名必进 + 打分 top-k。

    零命中回退全量——宁可全而不缺（不可让模型瞎掉所有技能）。paths 未激活
    /禁用/model_invocable=False 的技能直接出局（与目录渲染同过滤）。

    applications≥2 且（零完成 或 fallback 率>0.5）→ 本轮不再进工具面；无数据
    不熔断）。semantic_scores 提供时并入打分（keyword + max(0, cos≥floor)）。
    """
    active: List[str] = []
    unpacked: Dict[str, Any] = {}
    for name, raw in skills.items():
        skill = raw[0] if isinstance(raw, tuple) and raw else raw
        cfg = getattr(skill, "config", None)
        if isinstance(cfg, dict) and cfg.get("model_invocable") is False:
            continue
        if getattr(skill, "enabled", True) is False:
            continue
        if not match_skill_paths(skill, user_input):
            continue
        if quality_blocked(quality_lookup(name)) if quality_lookup is not None else False:
            continue
        active.append(name)
        unpacked[name] = skill

    if len(active) <= max_skills and not semantic_scores:
        return active

    q_ = str(user_input or "").lower()
    exact = [n for n in active if n.lower() and n.lower() in q_]
    rest = [n for n in active if n not in exact]
    semantic = semantic_scores or {}

    def _blend(name: str) -> float:
        score = score_skill_for_query(unpacked[name], user_input)
        cos = semantic.get(name)
        if cos is not None and cos >= _SEMANTIC_FLOOR:
            score += cos
        return score

    scored = sorted(
        ((n, _blend(n)) for n in rest),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if not exact and not any(s > 0 for _, s in scored):
        return active  # 零命中回退全量
    if len(active) <= max_skills:
        return active  # 未超预算：语义只影响排序不淘汰（全量给模型）
    picked = exact + [n for n, s in scored if s > 0]
    if len(picked) < max_skills:
        picked += [n for n, _ in scored[: max_skills - len(picked)]]
    return picked[:max_skills]


def routing_sanity_check(
    name: str,
    description: str,
    positive_queries: Optional[List[str]] = None,
    negative_queries: Optional[List[str]] = None,
) -> List[str]:
    """技能路由确定性自检。

    批准/进化提交前跑，零 LLM：
    - 描述为空 = 死技能种子（模型无信息判断何时使用）；
    - 名述自洽：技能名的可检索 token 必须出现在描述里（反之亦然），
      完全脱钩 = 按名召不回、按述也召不回的孤儿；
    - 显式正例（触发词）必须能召回自己；显式负例不得命中（过泛抢召回）。
    返回 issues 列表（空=通过）。
    """
    import types as _t

    issues: List[str] = []
    name = str(name or "")
    description = str(description or "")
    if not description.strip():
        issues.append("描述为空：模型无信息判断何时使用（死技能种子）")
        return issues

    _TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9\u4e00-\u9fa5_\-]+")
    name_tokens = [x for x in _TOKEN_SPLIT.split(name.lower()) if len(x) >= 2]
    desc_l = description.lower()
    desc_tokens = [x for x in _TOKEN_SPLIT.split(desc_l) if len(x) >= 2]
    coupled = any(t in desc_l for t in name_tokens) or any(t in name.lower() for t in desc_tokens)
    if not coupled:
        issues.append("名述脱钩：技能名与描述互不可召回，模型实际永远用不到该技能")

    stub = _t.SimpleNamespace(name=name, description=description, config={})
    for q in positive_queries or []:
        if score_skill_for_query(stub, str(q)) <= 0:
            issues.append(f"正例无法召回：'{q}' 打分为 0（触发词与名述无交集）")
    for q in negative_queries or []:
        if score_skill_for_query(stub, str(q)) > 0:
            issues.append(f"负例命中：'{q}' 会与本技能抢召回（描述过泛/越界）")
    return issues


def inject_skill_mentions(
    user_input: str,
    registry: Any,
    max_chars: int = _DEFAULT_DOC_BUDGET,
    allowed_names: Optional[set] = None,
) -> str:
    """入口：无 registry/无 mention/无命中时原样返回（零副作用）。

    allowed_names：Wave H-W2 可见集白名单（None=现状全量）。"""
    mentions = parse_skill_mentions(user_input or "")
    if not mentions or registry is None:
        return user_input or ""
    docs = collect_skill_mention_docs(
        registry, mentions, max_chars=max_chars, allowed_names=allowed_names
    )
    if not docs:
        return user_input or ""
    return f"{user_input}\n\n{docs}"
