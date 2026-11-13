"""任务级执行档位（R3+R6，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）§10.2——档位此前是**部署级**静态
env（NEUROVA_EXEC_PROFILE），对所有任务一视同仁；HarnessPro 是**每任务**
一次分类调用选 profile 并联动预算。

本模块提供 turn 级档位通道与 rubric 分类器：

- **ContextVar**：`setTurnProfile/getTurnProfile`——一次请求任务内生效，
  门控装配（`loops/base._load_agent_limits`）、分段提醒
  （`agent/budget_stages`）、溢出阈值（`security/tool_offload_settings`）
  同轮读取；不设 = 回落部署档位（旧行为）。
- **覆盖**：`applyTurnProfileOverlay` 把档位键值覆盖到 limits 上
  （standard 档为空表 = 原样）。
- **分类器**：`classifyTaskProfile` 用小模型按 rubric 从任务文本选
  lite/standard/heavy，输出置信度；<0.6 回退 standard；LLM 失败/输出
  非法 fail-open standard（不阻断对话）。开关 `NEUROVA_TASK_PROFILE=1`
  灰度开（默认关——每任务多一次模型调用，成本由运营决定）。

优先级（由 `chat_pipeline._resolve_task_profile` 装配）：调用方显式
metadata.task_profile > agent 存储档位（R6，agent_profile_settings）>
任务分类器（本模块，灰度）> 部署 env 档位 > standard。
"""

from __future__ import annotations

import json
import os
import re
import threading
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 任务级档位的合法域（与部署档位同一张表，单一出处）
VALID_PROFILES = ("lite", "standard", "heavy")

_turn_profile_var: ContextVar = ContextVar("neurova_turn_profile", default=None)

_CLASSIFY_SYSTEM = (
    "你是 agent 运行档位分诊器。根据任务文本选择执行档位：\n"
    "- lite：简单查询、单点小修改、寒暄致谢、答案可直查的任务；\n"
    "- standard：常规多步骤任务（默认）；\n"
    "- heavy：大型重构、跨系统迁移、高不确定性或强推理诉求。\n"
    '只输出 JSON：{"profile": "lite|standard|heavy", "confidence": 0到1的小数,'
    ' "reason": "一句话依据"}。不要输出其它文字。'
)
_LOW_CONFIDENCE_THRESHOLD = 0.6


def setTurnProfile(name: str) -> Optional[Token]:
    """设置当前任务级档位（非法名忽略并返回 None——不静默改成 standard）。"""
    normalized = str(name or "").strip().lower()
    if normalized not in VALID_PROFILES:
        return None
    return _turn_profile_var.set(normalized)


def getTurnProfile() -> Optional[str]:
    """当前任务级档位；未设置返回 None（调用方回落部署档位）。"""
    value = _turn_profile_var.get()
    return value if isinstance(value, str) else None


def resetTurnProfile(token: Optional[Token]) -> None:
    if token is not None:
        try:
            _turn_profile_var.reset(token)
        except ValueError:  # 不同任务上下文复用同一 token 时忽略
            pass


def clearTurnProfile() -> None:
    """无条件清空任务级档位（回落部署档位）——测试/轮次收尾用。"""
    _turn_profile_var.set(None)


def taskProfileEnabled() -> bool:
    """任务分类器开关（R3 治理面单源）：设置项 env > 文件 > 默认关。

    env `NEUROVA_TASK_PROFILE` 保留灰度直开/应急关的最高优先级；
    常规运营经 governance 设置项（`security/task_profile_settings`）读写。
    """
    try:
        from neurova.security.task_profile_settings import classification_enabled

        return classification_enabled()
    except Exception:  # noqa: BLE001 - 设置面故障退回 env 直读（fail-open 同旧形态）
        return os.environ.get("NEUROVA_TASK_PROFILE", "").strip() == "1"


# ── N8：任务级档位分布计数（治理面 /task-profile 的 usage 读数源）────────
_USAGE_TALLY: Dict[str, int] = {}
_USAGE_TALLY_LOCK = threading.Lock()


def recordProfileUsage(profile: str, source: str) -> None:
    """记录一次任务级档位解析结果（分布/来源计数，灰度开启后的观察读数）。"""
    key = f"{str(profile or 'standard').strip().lower()}|{str(source or 'unknown').strip()}"
    with _USAGE_TALLY_LOCK:
        _USAGE_TALLY[key] = _USAGE_TALLY.get(key, 0) + 1


def usageTally() -> Dict[str, Any]:
    """档位解析分布读数：总量、按档位、按来源（explicit/agent_stored/classified/fallback_standard）。"""
    with _USAGE_TALLY_LOCK:
        snapshot = dict(_USAGE_TALLY)
    by_profile: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    total = 0
    for key, count in sorted(snapshot.items()):
        profile, source = key.split("|", 1)
        by_profile[profile] = by_profile.get(profile, 0) + count
        by_source[source] = by_source.get(source, 0) + count
        total += count
    return {"total": total, "by_profile": by_profile, "by_source": by_source}


def applyTurnProfileOverlay(settings: Dict[str, Any], name: str) -> Dict[str, Any]:
    """把指定档位的键值覆盖到 limits 上（standard/未知名 = 原样返回）。"""
    from neurova.security.agent_limits_settings import EXEC_PROFILES

    overlay = EXEC_PROFILES.get(str(name or "").strip().lower())
    if not overlay:
        return settings
    merged = dict(settings)
    merged.update(overlay)
    return merged


def _extractJson(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


async def classifyTaskProfile(text: str, *, llm_call: Any = None,
                              model: str = "") -> Tuple[str, str, float]:
    """rubric 分类器：任务文本 → (profile, source, confidence)。

    - source：classified / low_confidence / classifier_failed；
    - 置信度 < 0.6 ⇒ 回退 standard（low_confidence）；
    - LLM 失败/输出非法 ⇒ standard（classifier_failed）——fail-open，
      绝不因分诊器故障阻断或降级对话。
    """
    try:
        messages = [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": str(text or "")[:8000]},
        ]
        if llm_call is not None:
            result = await llm_call(messages, model)
        else:
            from neurova.llm.multi_model_client import get_multi_model_client

            result = await get_multi_model_client().chat(messages, model=model or None)
        if not result.get("success"):
            return ("standard", "classifier_failed", 0.0)
        parsed = _extractJson(str(result.get("response") or ""))
        if not parsed:
            return ("standard", "classifier_failed", 0.0)
        profile = str(parsed.get("profile", "")).strip().lower()
        if profile not in VALID_PROFILES:
            return ("standard", "classifier_failed", 0.0)
        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < _LOW_CONFIDENCE_THRESHOLD:
            return ("standard", "low_confidence", confidence)
        return (profile, "classified", confidence)
    except Exception as e:  # noqa: BLE001 - 分类器故障不阻断对话
        logger.debug("任务档位分类失败（回退 standard）: %s", e)
        return ("standard", "classifier_failed", 0.0)
