"""执行入参指纹——批准对象=执行对象（P1-2）。

审批单创建时对 ``(tool_name, params)`` 计算规范 JSON 摘要，存入
``metadata.execution_fingerprint``；批准重放前必须复核，不一致即拒绝。

堵的窗口：审批单创建与批准重放之间，metadata.params 被改写/损坏/版本漂移，
导致"人批准看到的命令"与"实际重放的命令"不一致。

canonicalExecutionInput 是唯一规范：``{"tool": ..., "params": <规范 JSON>}``，
params 按 sort_keys + 紧凑分隔符序列化（键序无关、字节稳定）；
不可序列化参数经 ``default=repr`` 兜底，整体再不可序列化时退化为 repr。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

#: 审批 metadata 中指纹的键名（创建侧与复核侧共用同一常量）
EXECUTION_FINGERPRINT_KEY = "execution_fingerprint"


class ApprovalFingerprintMismatch(ValueError):
    """审批单指纹复核失败：metadata 在创建后被改写或损坏。"""


def canonicalExecutionInput(toolName: str, params: Any) -> str:
    """规范执行输入：键序无关、字节稳定，摘要与复核两侧共用同一实现。"""
    try:
        paramsCanonical = json.dumps(
            params,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
    except (TypeError, ValueError):
        paramsCanonical = repr(params)
    return json.dumps(
        {"tool": str(toolName), "params": paramsCanonical},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def executionFingerprint(toolName: str, params: Any) -> str:
    """执行入参指纹：sha256(canonicalExecutionInput(toolName, params))。"""
    return hashlib.sha256(canonicalExecutionInput(toolName, params).encode("utf-8")).hexdigest()


def verifyApprovalFingerprint(metadata: Dict[str, Any]) -> None:
    """复核审批单 metadata 的执行入参指纹；不一致抛 ApprovalFingerprintMismatch。

    旧审批单（无指纹键）直接放行——指纹是新增的完整性增强，不追溯存量单据。
    """
    stored = metadata.get(EXECUTION_FINGERPRINT_KEY)
    if not stored:
        return
    params = metadata.get("params") or {}
    toolName = str(metadata.get("tool_name") or "")
    current = executionFingerprint(toolName, params)
    if current != stored:
        raise ApprovalFingerprintMismatch(
            "审批单内容与批准对象不一致（执行入参指纹校验失败），已拒绝重放: "
            f"stored={str(stored)[:12]}… current={current[:12]}…"
        )
