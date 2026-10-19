# -*- coding: utf-8 -*-
"""§6-312 乙案第一刀：`neurova/collaborate/` 的死岛不再挂在每次进程启动路径上。

取证在 `audit-reports/collaborate-island-archive-2026-10-18.md`（C1/C2/C3/C5 四格）：
三档死码（`models.py` 150／`template.py` 373／`workflow/orchestrator.py` 340）自 2026-06-03
`1832a12b` 起**引入即未接线**，而两个包门面把它们无条件再导出——Python 导入子包必先执行父包
`__init__`，于是**只 import 活的 scheduler 也会执行这 863 行死码的模块体**。
这不是"占地方"：它是每次启动的真实成本，还向下一个人暗示"这里有协作实现"。

本格钉三件事：
① 前提——活符号（scheduler 那一条链）仍能从门面取到；
② 行为——干净子进程里只 import scheduler 时，死档不得进 `sys.modules`；
③ 面自证——那趟子进程真跑起来并交出可解析的读数（否则"零死档"分不开"没跑成"，形态集 283）。

现役替代（验过实质，不看存在）：`CollaborationTemplate`/`TemplateManager` 的同名实现
在 `neurova/agent/templates/collaboration_template.py` 已**被真消费**（`agent/team.py:25` 取 `AgentRole`），
且与死档 350 行里 346 行相同（95.7%）——活支是死支的超集，所以"取长补短"无事可做，合并动作＝删除。
"""

import dataclasses
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import ast_scan  # 导入通道判据的共享取数口（四形都认，含相对形与父包取名形）

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 死档＝本批退役对象。按**模块名**判，不按符号名（`AgentRole`/`WorkflowDefinition`
#: 在 `agent/templates/` 另有活实现，按名判会把活的读成死的——形态集里"同名词不同物"那一类）。
DEAD_MODULES = (
    "neurova.collaborate.models",
    "neurova.collaborate.template",
    "neurova.collaborate.workflow.orchestrator",
)

#: 活面＝端点真在用的那一条链（`api/endpoints/scheduler.py`、`api/endpoints/agent_package.py`）。
LIVE_SYMBOLS_ON_FACADE = ("AgentScheduler", "get_scheduler", "ScheduledTask", "FlowContext")

_PROBE = (
    "import sys, json\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import neurova.collaborate.workflow.scheduler\n"
    "print(json.dumps(sorted(m for m in sys.modules if m.startswith('neurova.collaborate'))))\n"
)


def _loadedCollaborateModules():
    """在**干净子进程**里只 import scheduler，交出落进 `sys.modules` 的 collaborate 模块名。

    必须起子进程：本跑测进程早就 import 过整座岛，在进程内量 `sys.modules` 恒真。
    两侧编码一起钉（形态集 248：只钉父端会读到 mojibake，只按 None 那种现象圈命中面会漏格）。
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(PROJECT_ROOT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(PROJECT_ROOT), timeout=120,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    tail = (proc.stdout or "").strip().splitlines()
    assert tail, (
        "探针没交出读数（退码 %s，stderr 前 200 字：%s）——「死档不在 sys.modules」这个零"
        "必须由一趟真跑起来的扫描给出，不能由一次没跑成冒充" % (proc.returncode, (proc.stderr or "")[:200])
    )
    loaded = json.loads(tail[-1])
    assert isinstance(loaded, list) and loaded, (
        "探针读数解析成空集，说明那条 import 腿没产生任何模块——本格就成了恒真空守卫"
    )
    return loaded


class TestCollaborateIslandRetirement:
    def test_liveFacadeSymbolsStillReachable(self):
        """正控：门面收口后，活的那条链必须照样从门面取得到（收口不许把活面一起关掉）。"""
        import neurova.collaborate.workflow as workflow
        from neurova.collaborate.workflow import get_scheduler

        missing = [name for name in LIVE_SYMBOLS_ON_FACADE if not hasattr(workflow, name)]
        assert not missing, "门面不再导出现役符号：%s（端点就是从这条路取的）" % ", ".join(missing)
        assert callable(get_scheduler)

    def test_probeFaceIsNotVacuous(self):
        """面自证：探针这一趟至少要把**活的** scheduler 报进读数——否则它没跑到那一步。"""
        loaded = _loadedCollaborateModules()
        assert "neurova.collaborate.workflow.scheduler" in loaded, (
            "探针没量到 scheduler（读数=%s）＝这条腿不产生非零，后面那条「死档缺席」的断言不作数" % loaded
        )

    def test_deadIslandNotDraggedOntoStartupPath(self):
        """只 import 活的 scheduler 时，三档死码不得进 `sys.modules`。"""
        loaded = set(_loadedCollaborateModules())
        dragged = sorted(mod for mod in DEAD_MODULES if mod in loaded)
        assert not dragged, (
            "包门面把死岛挂在每次进程启动路径上（§6-312 的 D19）：只 import scheduler 却执行了 "
            "%s。门面只该再导出活符号——这些档本体在本批一并删除。" % ", ".join(dragged)
        )

    def test_deadModulesAreGoneFromTheTree(self):
        """死档本体已随本批退役（不留"实现还在、只是没人导出"那种半成品——教义 7 的闭环判据）。"""
        stillThere = [
            str((PROJECT_ROOT / "neurova" / "collaborate" / rel).as_posix())
            for rel in ("models.py", "template.py", "workflow/orchestrator.py")
            if (PROJECT_ROOT / "neurova" / "collaborate" / rel).is_file()
        ]
        assert not stillThere, "以下死档仍在树里：%s" % ", ".join(stillThere)

    def test_importScannerFaceIsNotNarrowed(self):
        """面自证：同一个取数口对**活**模块必须报出引用——否则上面那句"零命中"不作数。

        根被改窄、路径写错、`importersOfModule` 被换实现，三种坏法都只会让 offender 读数变 0，
        看起来正是"退役干净"。这一格先证这条腿能产生非零（形态集 283：每个零都要先证它能红）。
        """
        live = ast_scan.importersOfModule(PROJECT_ROOT / "neurova", "neurova.collaborate.workflow.scheduler")
        assert len(live) >= 2, (
            "同一个取数口对现役 scheduler 只报 %d 处引用（应为 ≥2：包门面＋两个端点）——"
            "扫描面自己坏了，此时『死档零引用』是假绿" % len(live))

    def test_noProductionImporterOfDeadModules(self):
        """退役后不许留悬空引用：生产侧不得再有任何一档 import 这三条路径。"""
        offenders = []
        for mod in DEAD_MODULES:
            for path, lineno, kind in ast_scan.importersOfModule(PROJECT_ROOT / "neurova", mod):
                offenders.append("%s → %s:%s（取法 %s）" % (mod, path, lineno, kind))
        assert not offenders, (
            "死档已删却还有人 import 它（ImportError 会在运行时才现形）：\n  " + "\n  ".join(offenders)
        )

    # ── 第②刀：C4 `workflow/models.py` 按符号切半区（§6-312 裁乙的"改现役符号"那一半） ──────
    def test_orchestrationEnumsAreGoneFromLiveModel(self):
        """`FlowPhase`／`FlowEvent` 随编排方法群一起退。

        只按 collaborate 这条路径判：`neurova/core/flow_orchestrator.py` 里也有一对同名者，
        那是**不同物**（第③刀的对象）——按符号名全仓判会把它误伤（同名词不同物那一类伪命中）。
        """
        from neurova.collaborate.workflow import models
        leftover = [name for name in ("FlowPhase", "FlowEvent") if hasattr(models, name)]
        assert not leftover, (
            "`workflow/models.py` 仍导出 %s——两者的唯一读者是已退役的 orchestrator 本体"
            % "／".join(leftover))

    def test_flowContextCarriesNoOrchestrationBehaviour(self):
        """`FlowContext` 只剩字段袋：那 13 个编排方法（add_event／set_phase／to_dict…）无人调用。

        依据不是"grep 不到"而是 §6-315 那七格：handler 侧对 ctx 零读、调度器交付前零写，
        而全仓唯一的构造点就是 `scheduler.py:260`。本格钉的是行为面（方法确实不在类上）。
        """
        from neurova.collaborate.workflow import FlowContext

        methods = [name for name, value in inspect.getmembers(FlowContext, inspect.isfunction)
                   if not name.startswith("__")]
        assert not methods, (
            "FlowContext 上仍挂着编排方法：%s——这些方法的唯一写侧（add_event 的调用者）随 "
            "orchestrator 一起删了，留着就是「实现还在、只是没人调」" % ", ".join(sorted(methods)))

    def test_fieldFaceSurvivesAndMethodOnlyFieldsAreGone(self):
        """面自证＋下限：字段袋本身不许空掉（handler 的签名契约还在），只退"只为死方法存在"的两个位。"""
        from neurova.collaborate.workflow import FlowContext

        names = {f.name for f in dataclasses.fields(FlowContext)}
        assert len(names) >= 10, f"字段面缩水到 {len(names)} 个，handler 契约被动过：{sorted(names)}"
        assert "shared_data" in names and "step_outputs" in names, sorted(names)
        leftovers = {"current_phase", "event_history"} & names
        assert not leftovers, (
            "这两个位只被 add_event／set_phase／to_dict 读写（全仓零外部读者），"
            "方法群退净后它们就是第二个事实源：%s" % sorted(leftovers))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
