# -*- coding: utf-8 -*-
"""§6-311 裁乙第③刀：core 那份 870 行 `FlowOrchestrator` 连同它的 1005 行专用测试一起退。

取证在 `audit-reports/flow-orchestrator-comparison-2026-10-18.md`（§6-311）与
`audit-reports/execution-engine-subtree-archive-2026-10-17.md`（§6-301 的 A3 那一格）。
三条决定性事实，本批**全部按现读重取过**（297：档案读数不是事实源）：

1. **两份实现都不在生产路上**。`neurova/core/flow_orchestrator.py` 的生产侧引用为 0，
   唯一读者是它自己的测试（同一笔 `53875590` 把 shim 与契约测试一起入库＝自产自销）；
   collaborate 那份在第①刀已退（探针实测：17 条 workflow/neurflow 路由跑完 `get_orchestrator` 计数 0）。
2. **现役替代是真的**：流程编排在仓内由 `neurflow/execution_engine.py:162 WorkflowExecutor` 承担，
   对外经 17+ 条路由可达——所以本刀不是"删掉一种能力"，是删掉一份从未接线的仿真实现。
3. **随它消失的东西只有它自己的假象**。台账 line 263 早判这一族"自嗨模型"
   （`MemoryCoordinator` 的存取是全内存 list、`ContextMemoryBridge` 缓存自己的 deepcopy、
   `ToolFeedbackLoop` 注册表无人填），接线等于重写每个相位。
   它名义上的"梦境报告读侧"（`get_dream_reports`）读的是自己那个 list——
   `dream_reports` 表由 `memory/scripts/init_db.py:330` 建表却**从无写侧也无人读**，
   那条断点不随本刀消失，登记在 §6-346 的"仍开"里（表要删得走 `db_migration` 注册表，属数据动作，需人裁）。

本格钉四件事，全部按代码形态判，不钉词（241/268 那一族）：两份档本体不在树里、
三条根上零悬空导入、面自证（同一个取数口对活模块必须报出引用）、
且"同一功能只剩一处实现被消费"——`class FlowOrchestrator` 这个形态在 `neurova/` 下必须归零。
"""

import ast
from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SHIM = PROJECT_ROOT / "neurova" / "core" / "flow_orchestrator.py"
CONTRACT_TEST = PROJECT_ROOT / "tests" / "unit" / "core" / "test_flow_orchestrator.py"

#: 替代实装——它活着，才说明本刀删的是重复而不是能力。
REPLACEMENT_MODULE = "neurova.collaboration.neurflow.execution_engine"


def _classDefsNamed(name: str, root: Path) -> list:
    """`root` 子树里 `class <name>` 的落点（先按文本预筛再解析，成本随命中面走不随代码总量走）。"""
    hits = []
    for ref in ast_scan.sourceRefsUnder(root, hints=(name,)):
        for node in ast.walk(ast_scan.transientTree(ref.path)):
            if isinstance(node, ast.ClassDef) and node.name == name:
                hits.append(f"{ref.path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}")
    return sorted(set(hits))


class TestFlowOrchestratorShimRetirement:
    def test_bothShimFilesAreGone(self):
        """shim 与它自己的契约测试同批退（留一半就是"实现没删、测试先没了"那种半成品）。"""
        left = [str(p.relative_to(PROJECT_ROOT).as_posix()) for p in (SHIM, CONTRACT_TEST) if p.exists()]
        assert not left, (
            "以下两份仍留在树里：%s——`53875590` 那笔把 shim 与它的契约测试一起入库，"
            "退役也必须一起（教义 7：接通与退役同批完成）" % ", ".join(left))

    def test_noDanglingImportAnywhere(self):
        """三条根上不许还有人 import 它（悬空 import 只在运行时才现形）。"""
        offenders = []
        for sub in ("neurova", "tests", "scripts"):
            for path, lineno, kind in ast_scan.importersOfModule(PROJECT_ROOT / sub,
                                                                 "neurova.core.flow_orchestrator"):
                offenders.append(f"{sub}/{path}:{lineno}（取法 {kind}）")
        assert not offenders, (
            "shim 已删却仍有引用点：\n  " + "\n  ".join(offenders))

    def test_scannerFaceProducesNonZero(self):
        """面自证：同一个取数口对**现役**替代实装必须报出引用——否则上一条那个零不作数。

        `WorkflowExecutor` 是 neurflow 的执行咽喉，真被路由取用；若这条报 0，
        说明 `importersOfModule` 或根被改坏，此时"零悬空导入"是探测器失效的形状（283）。
        """
        live = ast_scan.importersOfModule(PROJECT_ROOT / "neurova", REPLACEMENT_MODULE)
        assert len(live) >= 1, (
            f"取数口对 {REPLACEMENT_MODULE} 报 0 处引用＝这条腿不产生非零，"
            "上一条『零悬空』不能当结论用")

    def test_noSecondOrchestrationClassRemains(self):
        """教义 7 的闭环判据：同一功能在仓内只剩一处实现——`class FlowOrchestrator` 归零。

        留着第二份，下一场"补全项目结构"式批量事件就会拿它当现役（§6-311 六、事件分组那条）。
        """
        found = _classDefsNamed("FlowOrchestrator", PROJECT_ROOT / "neurova")
        assert not found, (
            "生产树里仍有 `class FlowOrchestrator`：%s——两份同名编排器并存正是 D5 的原始病形"
            % ", ".join(found))

    def test_replacementExecutorIsImportable(self):
        """替代面可取（正控）：删 shim 之后，流程编排仍有一个真入口在服。"""
        module = __import__(REPLACEMENT_MODULE, fromlist=["WorkflowExecutor"])
        assert hasattr(module, "WorkflowExecutor"), "现役编排名取不到——本刀把能力一起删了"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
