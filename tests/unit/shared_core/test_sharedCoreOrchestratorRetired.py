# -*- coding: utf-8 -*-
"""`shared_core/plan_orchestrator.py`(453) 已退役，且门面不许再声称它（§6-114；§9 序 5 批 D）。

复算依据（台账 §3-A 与 §9 序 5 原把三套 plan_orchestrator 当"同职三套、删其二"，实测不是）：

- **现役规划面不是这三套中的任何一套**：agent 回合走 `neurova/planning/planning_tool.py`
  （`tool_executor.py:5325` 装配），HTTP 走 `neurova/plan_mode/` → `api/endpoints/__init__.py:219`
  挂的 `/v1/plans`。三套的生产 import 复算**全为 0**（含相对导入与门面再导出这一跳）。
- 本批摘的是三套里唯一的**纯桩**：`_handle_action:431`/`_handle_llm_call:434`/
  `_handle_tool_call:437`/`_handle_condition:440` 只回 `{"llm_call": 名字}` 一类字典，
  **一次 LLM/工具调用都不发**；`_execute_node:429` 对无 handler 的节点直接标 skipped。
  全仓**零测试**引用它（另两套至少有真行为测试：`tests/unit/core/test_plan_orchestrator.py`
  与 `tests/execution_engine/test_execution_*.py`）。
- 另两套**不在本批**：`core/plan_orchestrator.py`(654) 唯一实装 `RetryPolicy` + `adjust_plan`
  反馈改策略，`execution_engine/plan_orchestrator.py`(633) 唯一实装完整步骤状态机与真重试
  （`:397`）——各有一格"全仓唯一"，按教义第 7 条须先裁再动（§6-114 末列着）。

为什么要单独钉**门面陈述**：`shared_core/__init__.py` 的 docstring 把
`SharedPlanOrchestrator` 列为"共用任务编排器（小脑）"，而它**并不导入也不导出**任何东西
（门面正文只剩一句 `# shared_core imports` 空注释）。这种"文档声称有、代码没有"的名实分离
比空文件更坏——按 docstring 去找的人会以为这套能力在线。故本批判据里有一格专管它。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PKG_ROOT = REPO / "neurova"
TESTS_ROOT = REPO / "tests"
RETIRED = "neurova.shared_core.plan_orchestrator"

pytestmark = pytest.mark.timeout(60)


def _importedNames(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                out.append(node.module)
                out += [f"{node.module}.{a.name}" for a in node.names]
            elif node.level and node.module:
                out.append(f"__REL__.{node.module}")
    return out


def _hits(root: Path) -> list[str]:
    found = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if any(n == RETIRED or n.startswith(RETIRED + ".") or n == "__REL__.plan_orchestrator"
               for n in _importedNames(p)):
            try:
                shown = p.relative_to(REPO).as_posix()
            except ValueError:
                shown = p.relative_to(root).as_posix()   # 注入探针在 tmp 下（§6-107 的坑）
            found.append(shown)
    return found


def test_noImportOfRetiredOrchestrator():
    found = _hits(PKG_ROOT) + _hits(TESTS_ROOT)
    assert not found, f"已退役的桩编排器又被人引用了：{found}"


def test_retiredFileIsGone():
    assert not (PKG_ROOT / "shared_core" / "plan_orchestrator.py").is_file(), \
        "shared_core/plan_orchestrator.py 又回到包树里"


def test_facadeDoesNotClaimItAnymore():
    """门面 docstring 不许继续声称一个不存在的能力（名实分离比空文件更坏）。"""
    init = (PKG_ROOT / "shared_core" / "__init__.py").read_text(encoding="utf-8")
    assert "SharedPlanOrchestrator" not in init, (
        "`shared_core/__init__.py` 仍把 SharedPlanOrchestrator 列为在役组件，"
        "而它既不导入也不导出任何东西——按 docstring 找的人会以为这套能力在线")


def test_livePlanningFacesUntouched():
    """反向对照（防删过头）：现役那两条规划面必须还在位。"""
    assert (PKG_ROOT / "planning" / "planning_tool.py").is_file(), "agent 侧规划工具面不见了"
    eps = (PKG_ROOT / "api" / "endpoints" / "__init__.py").read_text(encoding="utf-8")
    assert "plans" in eps, "HTTP 规划面（/v1/plans）的挂载点不见了"
    # 另两套属"需人裁"，未裁之前不许被本批顺手带走
    assert (PKG_ROOT / "core" / "plan_orchestrator.py").is_file()
    assert (PKG_ROOT / "execution_engine" / "plan_orchestrator.py").is_file()


def test_scannerCatchesARevival(tmp_path):
    bad = tmp_path / "revival.py"
    bad.write_text(f"from {RETIRED} import SharedPlanOrchestrator\n", encoding="utf-8")
    assert _hits(tmp_path) == ["revival.py"]
    ok = tmp_path / "live.py"
    ok.write_text("from neurova.planning.planning_tool import PlanningTool\n", encoding="utf-8")
    bad.unlink()
    assert not _hits(tmp_path), f"误伤了现役规划面：{_hits(tmp_path)}"


def test_scanRootActuallyCoversTheTree():
    mods = [p for p in PKG_ROOT.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(mods) > 500, f"扫描根只覆盖 {len(mods)} 个 .py，层级写错了"
