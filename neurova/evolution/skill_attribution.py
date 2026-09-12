"""失败归因器 — 把 SelfModelEngine 的工具级教训归因到具体技能。

对比启发（jiuwenswarm SkillSelfEvolution 的 reviewer feedback 归因模型，
置信度阈值 react.evolution.review_feedback_min_confidence=0.7）：

现状缺口：SelfModelEngine 五算子产出的教训全部是工具粒度
（subject=工具名），消费面只有默认关的调控门——教训从未落到技能层，
技能无法从失败中学习（"只生不死"的另一半根因）。

归因链路（全确定性，无 LLM）：
  MetaLedger 活跃 lesson（kind="lesson"）
    → "工具→技能"倒排索引（registry 各技能的 tool_sequence 结构归因）
    → 置信度 = 教训置信度 × 歧义惩罚(k) + 行为佐证(+0.05)
    → 过阈值（默认 0.7）→ 写技能经验库（applied 记录立即生效，攒够参与重建）
    → 低于阈值 → 仅上报（候选可见，不写入）

置信度模型：
- 歧义惩罚：k = 使用该失败工具的技能数。k=1（独占）→ 1.0；
  k>1 → max(0.6, 1 - 0.15×(k-1))——工具被越多技能共用，归因到其中
  任何一个越不确定（失败可能发生在技能外直调）。
- 行为佐证：该技能自身使用统计成功率 <0.5（≥3 次使用）时 +0.05——
  结构归因（工具∈序列）与行为数据（技能自己也确实在失败）相互印证。

内容归一化：经验文本按算子模板生成（含工具名、不含波动数字）——
同型教训每轮反思重复落台账，归一化让经验库的内容去重天然防刷屏。
"""

import datetime
import os
import threading
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# SelfModelEngine 五算子产出的教训算子集合（subject 均为工具名）
_KNOWN_OPERATORS = {"drift", "sequence", "contrast", "calibration", "budget"}

# 默认归因置信度阈值（对齐 jiuwenswarm review_feedback_min_confidence=0.7）
DEFAULT_MIN_CONFIDENCE = 0.7

# 行为佐证加成的门槛
_CORROBORATION_MIN_USES = 3
_CORROBORATION_MAX_RATE = 0.5
_CORROBORATION_BONUS = 0.05

# 归一化经验模板（{tool} 占位；不含波动数字 → 经验库去重可防同型教训刷屏）
_GUIDANCE_TEMPLATES = {
    "drift": "工具 {tool} 近期成功率显著下滑：调用前先确认其可用，失败时准备降级路径",
    "sequence": "工具 {tool} 曾出现连续失败：执行前检查其依赖（网络/凭据/参数）",
    "contrast": "工具 {tool} 在特定输入形态（代码块/链接）上成功率偏低：此类输入先做预处理",
    "calibration": "工具 {tool} 近期表现低于历史基线：失败概率升高，注意校验参数与输入",
    "budget": "工具 {tool} 近期耗时显著上涨：大批量任务建议分批执行",
}

_index_lock = threading.Lock()


def _guidance_content(tool: str, operator: str) -> str:
    template = _GUIDANCE_TEMPLATES.get(operator) or "工具 {tool} 近期表现异常：执行前先确认其可用"
    return template.format(tool=tool)


def _is_active(metadata: Dict[str, Any]) -> bool:
    """教训活跃期判断（24h TTL；expires_at 缺失视为活跃）。"""
    expires = metadata.get("expires_at")
    if not expires:
        return True
    try:
        return datetime.datetime.fromisoformat(str(expires)) > datetime.datetime.now(
            datetime.timezone.utc
        )
    except (ValueError, TypeError):
        return True


def _resolve_threshold(min_confidence: Optional[float]) -> float:
    if min_confidence is not None:
        return float(min_confidence)
    env = os.environ.get("NEUROVA_SKILL_ATTRIBUTION_MIN_CONFIDENCE")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return DEFAULT_MIN_CONFIDENCE


def build_tool_skill_index(registry: Any) -> Dict[str, List[str]]:
    """从 registry 构建"工具→技能"倒排索引。

    步进归一化与 ToolSequenceSkill.execute 同约定（str 步 = {"tool": str}）。
    无 tool_sequence 的技能（手写 Skill 等）不参与结构归因。
    """
    index: Dict[str, List[str]] = {}
    try:
        skills = dict(registry.skills)
    except Exception:  # noqa: BLE001 - registry 形态各异，fail-soft
        return index
    with _index_lock:
        for skill_name, skill in skills.items():
            config = getattr(skill, "config", None)
            if not isinstance(config, dict):
                continue
            sequence = config.get("tool_sequence")
            if not isinstance(sequence, list) or not sequence:
                continue
            for step in sequence:
                if isinstance(step, str):
                    tool = step
                elif isinstance(step, dict):
                    tool = step.get("tool")
                else:
                    continue
                tool = str(tool or "").strip()
                if tool:
                    index.setdefault(tool, []).append(str(skill_name))
    return index


def attribute_failures_to_skills(
    registry: Any,
    store: Optional[Any] = None,
    ledger: Optional[Any] = None,
    min_confidence: Optional[float] = None,
    agent_id: str = "default",
) -> Dict[str, Any]:
    """把台账活跃工具级教训归因到具体技能。

    Args:
        registry: SkillRegistry（倒排索引来源 + 经验写入时组合描述）
        store: SkillExperienceStore（缺省取单例）
        ledger: MetaLedger（缺省时归因跳过——无教训源，不产生副作用）
        min_confidence: 置信度阈值（缺省读 env / 默认 0.7）
        agent_id: 台账归属（ledger 按 agent 分库）

    Returns:
        {"attributed": [...], "below_threshold": [...], "lessons_read": n}
    """
    if store is None:
        from neurova.evolution.skill_experience import get_skill_experience_store

        store = get_skill_experience_store()

    result: Dict[str, Any] = {"attributed": [], "below_threshold": [], "lessons_read": 0}
    if ledger is None or registry is None:
        return result

    threshold = _resolve_threshold(min_confidence)
    try:
        page = ledger.list_records(agent_id=agent_id, page=1, size=50, kind="lesson")
        items = list((page or {}).get("items") or [])
    except Exception as e:  # noqa: BLE001 - 台账形态异常时归因跳过
        logger.debug("归因读取台账失败: %s", e)
        return result

    index = build_tool_skill_index(registry)

    for item in items:
        meta = item.get("metadata") or {}
        subject = str(meta.get("subject") or "").strip()
        operator = str(meta.get("operator") or "").strip()
        if not subject or operator not in _KNOWN_OPERATORS:
            continue
        if not _is_active(meta):
            continue
        result["lessons_read"] += 1

        candidates = index.get(subject, [])
        if not candidates:
            continue

        try:
            lesson_conf = float(
                meta.get("confidence") if meta.get("confidence") is not None else item.get("confidence") or 0.0
            )
        except (TypeError, ValueError):
            continue
        k = len(candidates)
        penalty = 1.0 if k == 1 else max(0.6, 1.0 - 0.15 * (k - 1))
        content = _guidance_content(subject, operator)

        for skill_id in candidates:
            confidence = lesson_conf * penalty
            usage = store.get_usage(skill_id)
            if usage["times_used"] >= _CORROBORATION_MIN_USES and (
                usage["positive"] / usage["times_used"]
            ) < _CORROBORATION_MAX_RATE:
                confidence += _CORROBORATION_BONUS
            confidence = round(min(1.0, max(0.0, confidence)), 2)

            entry = {
                "skill_id": skill_id,
                "tool": subject,
                "operator": operator,
                "confidence": confidence,
            }
            if confidence >= threshold:
                # 内容归一化 → 经验库同内容去重，重复反思不刷屏
                record = store.record_experience(
                    skill_id=skill_id,
                    content=content,
                    source="attribution",
                    context=f"lesson:{operator}:{subject}",
                    registry=registry,
                )
                if record is not None:
                    entry["written"] = True
                result["attributed"].append(entry)
            else:
                result["below_threshold"].append(entry)

    if result["attributed"]:
        logger.info(
            "失败归因: %d 条教训落到技能粒度（%s）",
            len(result["attributed"]),
            ", ".join(a["skill_id"] for a in result["attributed"][:5]),
        )
    return result
