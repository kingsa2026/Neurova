# -*- coding: utf-8 -*-
"""沙箱根：成员资格与解析口径都收口到 `skills/sandbox_root.py`（Issue #271 M5 尾巴）。

## 根因（放大视角扫同契约消费方时逮到，本片新发现）

`file_operation` 的 `_base_dir` 注入此前是**一条事实、两处实现**：

    成员判定    sandbox_root.py:SANDBOX_ROOT_TOOLS = {"file_operation"}
                tool_executor.py:1013  `if skill_name == "file_operation":`   ← 第二处硬编码
    解析口径    helper：str(workspace_path)（**不校验**）
                咽喉：Path(...).is_dir() 校验，非真实目录回落 "."（含 Mock 泄漏防护）

后者是 2026-09-08 事故的修复产物，前者没有跟着升级。实测两条入口对同一输入给出
**不同答案**：

    workspace_path = "/nonexistent-dir-xyz"
      inject_sandbox_root(...)["_base_dir"] → "/nonexistent-dir-xyz"   ← 把伪造根发给执行体
      _workspace_base()                     → "."

`_base_dir` 是**服务端赋值**、用来覆盖 LLM 伪造的同名参数（防伪造防线）。一处入口
把未校验的路径当沙箱根发下去，防线就只在另一条路径上成立——而两条路径的差别
（谁先调了谁）对调用者不可见。

## 处置

两件都收口到同一模块：成员走 `SANDBOX_ROOT_TOOLS`（唯一），解析走同一个
`resolveWorkspaceRoot()`。咽喉不再自带成员判定与解析，改为调 helper。
本片是**等价迁移**：合法工作区下两处读数逐字相同，只把非法输入这条分叉合上。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

import pytest

from neurova.skills.sandbox_root import (
    SANDBOX_ROOT_TOOLS,
    inject_sandbox_root,
    resolveWorkspaceRoot,
)
from neurova.tool_executor import ToolExecutor

REPO_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = REPO_ROOT / "neurova"


class _Agent:
    def __init__(self, ws):
        self.workspace_path = ws


def _choke():
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = _Agent("/tmp")
    return inst


# ═══════════════════════════════════════════════════════════════
# 一、解析口径单源：两条入口对同一输入必须同答
# ═══════════════════════════════════════════════════════════════


class TestResolutionIsOneSource:
    """非法/缺失工作区是两处实现分叉的地方，逐档对照。"""

    @pytest.mark.parametrize(
        "workspace",
        [
            "/nonexistent-dir-xyz-123",   # 非真实目录（Mock 泄漏同型）
            "",                            # 空串
            None,                          # 未配置
        ],
    )
    def test_invalidWorkspaceFallsBackToDotOnBothEntries(self, workspace):
        agent = _Agent(workspace)
        via_helper = inject_sandbox_root(agent, "file_operation", {})["_base_dir"]
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = agent
        via_choke = inst._workspace_base()
        assert via_helper == via_choke == ".", (
            f"workspace={workspace!r} 下两条入口给出不同沙箱根："
            f"helper={via_helper!r}、咽喉={via_choke!r}——"
            "同一条事实两处实现，防伪造防线只在其中一条路径上成立"
        )

    def test_realWorkspaceAgreesOnBothEntries(self, tmp_path):
        agent = _Agent(str(tmp_path))
        via_helper = inject_sandbox_root(agent, "file_operation", {})["_base_dir"]
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = agent
        assert via_helper == inst._workspace_base() == str(tmp_path)

    def test_agentMissingAttributeFallsBack(self):
        class Bare:
            pass

        assert resolveWorkspaceRoot(Bare()) == "."
        assert inject_sandbox_root(Bare(), "file_operation", {})["_base_dir"] == "."

    def test_noneAgentFallsBack(self):
        assert resolveWorkspaceRoot(None) == "."
        assert inject_sandbox_root(None, "file_operation", {})["_base_dir"] == "."


# ═══════════════════════════════════════════════════════════════
# 二、成员资格单源：咽喉不得自带第二处判定
# ═══════════════════════════════════════════════════════════════


class TestMembershipIsOneSource:
    def test_membershipSetShape(self):
        assert isinstance(SANDBOX_ROOT_TOOLS, frozenset)
        assert SANDBOX_ROOT_TOOLS == {"file_operation"}

    def test_injectionHappensIffMember(self):
        agent = _Agent("/tmp")
        for name in ("file_operation", "memory_search", "file_read", "not_a_skill"):
            got = inject_sandbox_root(agent, name, {}) 
            assert ("_base_dir" in got) is (name in SANDBOX_ROOT_TOOLS), name

    def test_chokeDoesNotHoldItsOwnMembershipCheck(self):
        """AST 判据：咽喉里对 `_base_dir` 的注入不得自带成员比较。

        判定条件是「注入语句受一个**字符串字面量比较**控制」——那正是第二处硬编码
        的形态。咽喉必须调单源 helper（`inject_sandbox_root`）。
        """
        tree = ast.parse(
            (NEUROVA / "tool_executor.py").read_text(encoding="utf-8"),
            filename="tool_executor.py",
        )
        offenders: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # 收集本 if 体内出现的 "_base_dir" 字面量键（注入形态）
                injects = [
                    k.value
                    for sub in ast.walk(node)
                    for k in (sub.keys if isinstance(sub, ast.Dict) else [])
                    if isinstance(k, ast.Constant) and k.value == "_base_dir"
                ]
                if not injects:
                    continue
                compares_literal = any(
                    isinstance(c, ast.Compare)
                    and any(
                        isinstance(x, ast.Constant) and isinstance(x.value, str)
                        for x in [c.left, *c.comparators]
                    )
                    for c in ast.walk(node.test)
                )
                if compares_literal:
                    offenders.append(f"tool_executor.py:{node.lineno}")
        assert offenders == [], (
            "咽喉自带 `_base_dir` 成员判定（第二处硬编码，与 SANDBOX_ROOT_TOOLS 无对账）："
            f"{offenders}"
        )

    def test_chokeCallsTheSingleSource(self):
        """咽喉必须真的调单源 helper（否则上面的空判据只是"没写"，不是"收口了"）。"""
        src = (NEUROVA / "tool_executor.py").read_text(encoding="utf-8")
        assert "inject_sandbox_root(" in src, (
            "咽喉没有调 `inject_sandbox_root`——沙箱根注入的成员与解析仍在两处各写一份"
        )


# ═══════════════════════════════════════════════════════════════
# 三、等价迁移：合法工作区下行为逐字相同
# ═══════════════════════════════════════════════════════════════


class TestInjectionSemanticsUnchanged:
    def test_paramsAreNotMutatedInPlace(self):
        agent = _Agent("/tmp")
        original = {"operation": "read"}
        out = inject_sandbox_root(agent, "file_operation", original)
        assert out is not original and "_base_dir" not in original

    def test_injectedBaseDirOverridesCallerSupplied(self, tmp_path):
        """服务端赋值**覆盖** LLM 伪造的同名参数（防伪造语义不得回退）。"""
        agent = _Agent(str(tmp_path))
        out = inject_sandbox_root(agent, "file_operation", {"_base_dir": "/etc"})
        assert out["_base_dir"] == str(tmp_path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
