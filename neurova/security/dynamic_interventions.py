"""U6 动态干预审计注册表 —— 声明式规则（工具名 + 参数谓词 + 干预动作）。

## 定位

治理预检（`security/governance`）裁决的是**内容**（命令/路径/代码文本）；
本注册表裁决的是**工具调用本身**——某些工具/参数组合无论内容如何都必须
过一道人工确认。ToolExecutor 在治理预检之后、执行之前查本注册表，
命中即转审批链（复用 `_awaitApprovalVerdict` 的待审批/阻塞等待/带外重放通路）。

## 规则形状

`DynamicInterventionRule` = 工具名集合 + 参数谓词 `(tool_name, params, ctx) -> bool`
+ 干预动作（`ask` = 转审批链）+ 级别（L1 = 必问）。谓词只读参数与上下文，
不做任何 I/O 之外的事；ctx 携带 agent_id / user_id / ssh_host_store 等取数口。

## 首批两条（L1 必问）

- `file_permanent_delete`：`file_delete` 恒命中（删除即永久，无回收站）；
  `file_edit` 在 `new_str` 为空时命中（把匹配文本永久删掉）。
- `ssh_host_first_seen`：`computer_ssh_exec` 的目标 host 在 SSH 主机确认库
  （U1 的 SshHostStore）无已确认记录时命中——授权在人（审批链），
  密码学确认在 U1 主机卡，两道门衔接不互替。

## 审计

命中即写治理审计（`_audit_governance`，decision=ask），审批单本身落
ApprovalManager（SQLite + 通知）；批准/拒绝经既有审批链留痕。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DynamicInterventionRule:
    """一条动态干预规则（声明式，只描述"什么情况必问"）。"""

    name: str
    description: str
    tool_names: frozenset
    level: str  # "L1" = 必问
    action: str  # "ask" = 转审批链
    reason_template: str
    predicate: Callable[[str, Dict[str, Any], Dict[str, Any]], bool]  # (tool, params, ctx) -> bool


def _filePermanentDeletion(tool_name: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """永久删除形态：file_delete 恒命中（删除即永久，无回收站）；
    file_edit 在 new_str 为空时命中（把匹配文本永久删掉）。"""
    if tool_name == "file_delete":
        return True
    if tool_name == "file_edit":
        return bool(str(params.get("old_str") or "")) and not str(params.get("new_str") or "")
    return False


def _sshHostFirstSeen(tool_name: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """目标 host 在 SSH 主机确认库无已确认记录 → 首次出现。"""
    host = str(params.get("host") or "").strip()
    if not host:
        return False
    store = ctx.get("ssh_host_store")
    if store is None:
        from neurova.security.ssh_host_store import get_ssh_host_store

        store = get_ssh_host_store()
    agent_id = str(ctx.get("agent_id") or "")
    try:
        port = int(params.get("port") or 22)
    except (TypeError, ValueError):
        port = 22
    try:
        return store.lookup(agent_id, host, port) is None
    except Exception:  # noqa: BLE001 - 确认库不可用按"首见"处置（fail-closed）
        return True


def _buildFirstBatchRules() -> Tuple[DynamicInterventionRule, ...]:
    return (
        DynamicInterventionRule(
            name="file_permanent_delete",
            description="文件永久删除必问（删除无回收站；file_edit 的清空文本同口径）",
            tool_names=frozenset({"file_delete", "file_edit"}),
            level="L1",
            action="ask",
            reason_template="永久删除文件（无回收站语义），须人工确认",
            predicate=_filePermanentDeletion,
        ),
        DynamicInterventionRule(
            name="ssh_host_first_seen",
            description="SSH 目标主机首次出现必问（与 U1 主机确认卡衔接）",
            tool_names=frozenset({"computer_ssh_exec"}),
            level="L1",
            action="ask",
            reason_template="SSH 目标主机 {host} 首次出现，须人工确认后连接",
            predicate=_sshHostFirstSeen,
        ),
    )


class DynamicInterventionRegistry:
    """动态干预规则注册表（不可变规则集 + 只读评估口）。"""

    #: 注册面锁（register 极低频，类级 RLock 足够；评估口无锁——规则集不可变）
    _lock = threading.RLock()

    def __init__(self, rules: Optional[Tuple[DynamicInterventionRule, ...]] = None):
        self._rules: Tuple[DynamicInterventionRule, ...] = tuple(
            rules if rules is not None else _buildFirstBatchRules()
        )

    @property
    def rules(self) -> Tuple[DynamicInterventionRule, ...]:
        """规则集只读视图（调用方不得增删——注册走 register 单点）。"""
        return self._rules

    def register(self, rule: DynamicInterventionRule) -> None:
        """注册一条新规则（替换同名旧规则）。"""
        with self._lock:
            kept = tuple(r for r in self._rules if r.name != rule.name)
            self._rules = kept + (rule,)
        logger.info("动态干预规则已注册: %s（tools=%s, level=%s）",
                    rule.name, sorted(rule.tool_names), rule.level)

    def evaluate(self, tool_name: str, params: Dict[str, Any],
                 ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """评估一次工具调用，返回命中的干预清单（可能为空）。

        命中项形状：{"rule", "level", "action", "reason"}——执行器据此转审批链。
        """
        if not isinstance(params, dict):
            params = {}
        context = ctx or {}
        hits: List[Dict[str, Any]] = []
        for rule in self._rules:
            if tool_name not in rule.tool_names:
                continue
            try:
                matched = bool(rule.predicate(tool_name, params, context))
            except Exception as e:  # noqa: BLE001 - 谓词故障按未命中处置并留痕
                logger.warning("动态干预谓词故障（按未命中）: rule=%s, err=%s", rule.name, e)
                continue
            if matched:
                reason = rule.reason_template.format(**{
                    **{str(k): v for k, v in params.items()},
                    "tool": tool_name,
                })
                hits.append({
                    "rule": rule.name,
                    "level": rule.level,
                    "action": rule.action,
                    "reason": reason,
                })
        return hits


# 模块级单例（DCL + RLock，代码规约口径）
_registry_instance: Optional[DynamicInterventionRegistry] = None
_registry_singleton_lock = threading.RLock()


def getDynamicInterventionRegistry() -> DynamicInterventionRegistry:
    """取动态干预注册表单例（DCL + RLock）。"""
    global _registry_instance
    if _registry_instance is None:
        with _registry_singleton_lock:
            if _registry_instance is None:
                _registry_instance = DynamicInterventionRegistry()
    return _registry_instance


def resetDynamicInterventionRegistry() -> None:
    """仅测试/重装配用：清空单例。"""
    global _registry_instance
    with _registry_singleton_lock:
        _registry_instance = None


def evaluateDynamicInterventions(tool_name: str, params: Dict[str, Any],
                                 ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """便捷评估口：对单例注册表做一次命中评估。"""
    return getDynamicInterventionRegistry().evaluate(tool_name, params, ctx)
