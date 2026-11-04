"""认知安全门——cognitive_security 三件套的生产接线（候选 C1）。

断点（对比报告 2026-11-05 N1）：PromptInjectionDetector/CognitiveSafetyChecker/
MemorySecurityGuard 与组合器 CognitiveSecuritySystem 此前生产侧零消费——
有码未接。本模块是其唯一装配与读数出口：

- 输入门 ``runInputSafetyGate``：chat Step 0.5 调用，观察态只记读数不阻断；
- 记忆写入咽喉 ``runMemoryWriteGuard``：``MemoryManager.remember`` 单点调用
  （``remember_with_trace`` 委托 remember，全部生产方一轮覆盖）。

模式三态，默认 observe：
- ``off``：门整体旁路（零开销）；
- ``observe``：只记读数（warning），不改任何内容——默认态，零行为漂移；
- ``enforce``：输入面置阻断标记（早退诚实拒答）、记忆面 sanitize 后落库。

误拦不可逆，enforce 必须显式开启：系统设置 security 分区
（``cognitive_security_mode``）或 env ``NEUROVA_COGNITIVE_SECURITY``
（运维逃生门，显式值最优先）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.security.cognitive_security import CognitiveSecuritySystem

logger = get_logger(__name__)

_VALID_MODES = ("off", "observe", "enforce")
#: 读数里逐条发现的收录上限（超出只记总数，防 metadata 膨胀）
_FINDINGS_CAP = 10

_LOCK = threading.RLock()
_SYSTEM: Optional[CognitiveSecuritySystem] = None


def getCognitiveSecurityConfig(path: "Optional[Path]" = None) -> Dict[str, Any]:
    """读门配置：系统设置 security 分区；env ``NEUROVA_COGNITIVE_SECURITY``
    显式值最优先（运维逃生门）。未知值一律回落 observe（宁观察勿阻断）。"""
    try:
        from neurova.core.app_settings import load_app_settings

        section = load_app_settings(path).get("security") or {}
        mode = str(section.get("cognitive_security_mode") or "observe").strip().lower()
    except Exception:  # noqa: BLE001 - 读设置失败回落默认观察态
        mode = "observe"
    env = (os.environ.get("NEUROVA_COGNITIVE_SECURITY") or "").strip().lower()
    if env in _VALID_MODES:
        mode = env
    if mode not in _VALID_MODES:
        mode = "observe"
    return {"mode": mode}


def _getSystem() -> CognitiveSecuritySystem:
    """DCL 懒创建单例（代码规约：懒创建型单例必须走 DCL + threading.RLock）。"""
    global _SYSTEM
    if _SYSTEM is None:
        with _LOCK:
            if _SYSTEM is None:
                _SYSTEM = CognitiveSecuritySystem()
    return _SYSTEM


def _readingFrom(result: Any, mode: str) -> Dict[str, Any]:
    """SafetyCheckResult → 紧凑读数 dict（发现逐条收录，超上限只记总数）。"""
    findings = result.findings or []
    return {
        "mode": mode,
        "is_safe": bool(result.is_safe),
        "finding_count": len(findings),
        "highest_severity": (
            result.highest_severity.value if result.highest_severity else None
        ),
        "findings": [f.to_dict() for f in findings[:_FINDINGS_CAP]],
    }


def runInputSafetyGate(user_input: str) -> Optional[Dict[str, Any]]:
    """输入面安全门。off/空输入返回 None（不记读数）；否则返回读数 dict，
    并在不安全时记 warning（唯一日志出口，调用方不再自行记录）。"""
    mode = getCognitiveSecurityConfig()["mode"]
    if mode == "off" or not user_input:
        return None
    result = _getSystem().check_input_safety(user_input)
    reading = _readingFrom(result, mode)
    if not result.is_safe:
        logger.warning(
            "认知安全门读数：输入面 %d 项发现 mode=%s highest=%s",
            reading["finding_count"],
            mode,
            reading["highest_severity"],
        )
    return reading


def runMemoryWriteGuard(content: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """记忆写入咽喉。返回 ``(落库内容, 读数)``；无发现/off 返回 ``(原文, None)``。
    observe：记 warning、原文原样；enforce：sanitize 后落库并 warning。
    门自身故障由调用方 fail-open 放行原文（不在这里吞）。"""
    mode = getCognitiveSecurityConfig()["mode"]
    if mode == "off" or not content:
        return content, None
    result = _getSystem().check_memory_safety(content)
    if result.is_safe:
        return content, None
    reading = _readingFrom(result, mode)
    if mode == "enforce":
        sanitized = _getSystem().sanitize_memory(content)
        logger.warning(
            "认知安全门 enforce：记忆内容已脱敏（%d 项发现 highest=%s）",
            reading["finding_count"],
            reading["highest_severity"],
        )
        return sanitized, reading
    logger.warning(
        "认知安全门读数：记忆写入 %d 项发现 mode=observe highest=%s",
        reading["finding_count"],
        reading["highest_severity"],
    )
    return content, reading


__all__ = [
    "getCognitiveSecurityConfig",
    "runInputSafetyGate",
    "runMemoryWriteGuard",
]
