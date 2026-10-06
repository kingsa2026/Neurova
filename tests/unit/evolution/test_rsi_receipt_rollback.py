"""RSI 回执落盘失败必须真回滚（审计 §6-2）。

判据只有一句：`apply_optimization` 的注释承诺"撤销本次优化并拒回执成功"，
而承诺所在的那条支路里写着一个类内根本不存在的名字——`self._logger`。
NameError 在 `except Exception` 之前抛出，回滚那行 `setattr` 于是永远不执行，
调用方拿到 `False`（"这次没优化"），系统上却留着新值（"其实优化了"）。
"""

from __future__ import annotations

import ast
import io
import os

import pytest

from neurova.evolution.rsi.debt_ledger import RsiDebtLedger
from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
from tests.unit.evolution.conftest import ProbeSystem

TOOL_MEMORY_PARAMS = {
    "success_bonus": 0.1,
    "failure_penalty": 0.05,
    "decay_rate": 0.01,
    "muscle_memory_threshold": 0.85,
}


def _managerWithToolMemory(toolMemory: ProbeSystem) -> RSIIntegrationManager:
    """走真构造装配四系统，不用 MagicMock 冒充业务对象。"""
    return RSIIntegrationManager(
        sleep_system=ProbeSystem("sleep"),
        emotion_system=ProbeSystem("emotion"),
        experience_system=ProbeSystem("experience"),
        tool_memory_system=toolMemory,
    )


def testReceiptWriteFailureRollsBackAppliedParameter(tmp_path, monkeypatch):
    """账本丢行时，已写进系统的优化必须被撤回去。"""
    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    toolMemory = ProbeSystem(
        "tool_memory",
        feedback={"total_usages": 50, "success_rate": 0.5},
        params=dict(TOOL_MEMORY_PARAMS),
    )
    manager = _managerWithToolMemory(toolMemory)
    ledger = RsiDebtLedger(receipts)
    ledger.force_write_failure_for_test(True)

    applied = manager.apply_optimization(
        "tool_memory.decay_rate", 0.05, debt_ledger=ledger, cost=40, repayment=0
    )

    assert applied is False, "回执没落盘却向调用方报成功"
    assert toolMemory.decay_rate == 0.01, (
        "回执落盘失败后优化仍留在系统上（decay_rate=%r）——`self._logger` 幻影引用把"
        "回滚那行 setattr 短路成了永远到不了的死码，与 :381 注释承诺相反。"
        % (toolMemory.decay_rate,)
    )


def testLegacyReceiptFailureIsReportedAsWriteFailure(tmp_path, monkeypatch, caplog):
    """遗产分支（无账本）写失败时，归因必须是"回执写入失败"，不是"优化失败"。

    同一条幻影引用在这里换了个死法：它在 `except` 处理器内部抛出，于是外层
    `except Exception` 把 NameError 记成 `Failed to apply optimization`——
    把"审计没落地"误报成"优化没做成"，调用方据此归因会追错方向。
    """
    blocked = tmp_path / "blocked"
    blocked.write_text("占位文件，使 receipts 的父目录无法建立", encoding="utf-8")
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(blocked / "rsi_receipts.jsonl"))

    toolMemory = ProbeSystem("tool_memory", params=dict(TOOL_MEMORY_PARAMS))
    manager = _managerWithToolMemory(toolMemory)

    with caplog.at_level("WARNING"):
        manager.apply_optimization("tool_memory.decay_rate", 0.05)

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "优化回执写入失败" in messages, (
        "回执写失败没有被点名（现被幻影引用折成了另一条错误）：%s" % messages
    )
    assert "Failed to apply optimization" not in messages, (
        "回执写入失败被误归因成优化失败：%s" % messages
    )


def _phantomLoggerSites(repoRoot: str):
    """全仓扫 `self._logger` 取用点，返回"所在类未定义（含沿继承链）"的位置。"""
    defines, assigns, usages = {}, set(), []

    for root, dirs, files in os.walk(repoRoot):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "node_modules")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read())
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                defines[node.name] = [ast.unparse(b).split(".")[-1] for b in node.bases]
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Attribute) and sub.attr == "_logger"
                            and isinstance(sub.value, ast.Name) and sub.value.id == "self"):
                        if isinstance(sub.ctx, ast.Store):
                            assigns.add(node.name)
                        else:
                            usages.append((path, sub.lineno, node.name))

    def definedInChain(className, seen):
        if className in seen:
            return False
        seen.add(className)
        if className in assigns:
            return True
        return any(definedInChain(base, seen) for base in defines.get(className, []))

    return [u for u in usages if not definedInChain(u[2], set())]


def testNoPhantomLoggerAnywhereInRepository():
    """`self._logger` 只允许出现在定义了它的类（或其基类）里。

    这条不是给 §6-2 单独打的补丁，而是把"同一根因全命中点"钉成判据：
    复扫现值 151 处取用，只有 `RSIIntegrationManager` 两处是幻影——修完应为 0，
    此后任何新增的同形写法都会在这里红，而不是等到某条安全支路被短路。
    """
    repoRoot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    sites = _phantomLoggerSites(os.path.join(repoRoot, "neurova"))
    assert sites == [], "幻影 self._logger 取用点：%s" % [
        "%s:%d (%s)" % s for s in sites
    ]
