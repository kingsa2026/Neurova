"""三套零接线编排器的退役守卫（§6-166；比对与「取长补短」见 §6-157）。

判据口径来自 §6-157 的逐格比对，不是"引用计数＝0 就删"：
- 六格（任务分解／拓扑调度／取消断点／元认知／认知周期／状态持久化）服务路上都有更强对应物，
  其中"计划"这一格有**三处**现役（`neurflow/nl_designer.py` 生成图、`planning/planning_tool.py`
  工具面、`plan_mode/` 审批-执行链）——所以这三套不是"全仓唯一实装"。
- 唯二真缺的两格（层内并发上限、节点级重试幂等门）已并入活路（`f060c2f4`），
  因此它们也不再是保留理由。
- 候选侧的实测形态：`decompose_intent("写一份报告并保存到文件")` 得 **1 步**、名 `simple_task`；
  `execute_plan` 返回体带 `simulated: true`（`set_executor` 全仓零调用 ⇒ `_executor` 恒 None）；
  `process_thought_cycle` 产出「输入包含 1 个词」＋「推理完成」＋「反思完成」却 `success=True`；
  `save_state` 裸 `open(path)` 不碰数据根。这些不是"弱"，是**把编造标成成功**。

反向断言（`test_mergedCellsAndLivePlanningFacesRemain` / `test_facadeMustNotClaimRetiredMembers`）
拦两种买绿路径：把顶替那条活路一起删掉；把已退成员继续写在包门面的成员清单里
（§6-115 的"文档声称有、代码没有"形态）。
"""

import importlib
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]

# 按段拼：本档是"证明它们不在位"的守卫，不该同时成为一条"引用退役路径"的命中点（§6-151 的自伤）
TARGETS = (
    ("neurova", "core", "cognition_orchestrator.py"),
    ("neurova", "core", "plan_orchestrator.py"),
    ("neurova", "execution_engine", "plan_orchestrator.py"),
)
MODULES = (
    ".".join(("neurova", "core", "cognition_orchestrator")),
    ".".join(("neurova", "core", "plan_orchestrator")),
    ".".join(("neurova", "execution_engine", "plan_orchestrator")),
)


def _needles() -> tuple[str, ...]:
    out: list[str] = []
    for parts in TARGETS:
        posix = "/".join(parts)
        out.append(posix)
        out.append(posix[: -len(".py")].replace("/", "."))
    return tuple(out)


class TestUnwiredOrchestratorsRetired:
    def test_filesGoneAndNotImportable(self):
        for parts in TARGETS:
            path = REPO.joinpath(*parts)
            assert not path.exists(), f"未接线的编排器仍在位：{path.relative_to(REPO)}"
        for module in MODULES:
            sys.modules.pop(module, None)
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module)

    def test_noCodeCitesRetiredModules(self):
        """生产/测试/脚本里不得再有任何一处按路径或模块名引用它们（含清单条目与模板注释）。

        `test_singleton_convergence.py` 的 BENIGN_SINGLETONS 曾留着一条指向已退实现的条目——
        同档另一格因此红了 18 天（§6-116 记着）。这一格就是把那种"条目没跟"钉住。
        """
        needles = _needles()
        hits = []
        for root in ("neurova", "tests", "scripts"):
            for path in (REPO / root).rglob("*.py"):
                if "__pycache__" in path.parts or path == pathlib.Path(__file__).resolve():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                found = [n for n in needles if n in text]
                if found:
                    hits.append(f"{path.relative_to(REPO).as_posix()} → {found}")
        assert hits == [], "退役模块仍被引用：" + "; ".join(sorted(hits))


class TestMergedCellsAndLivePlanningFacesRemain:
    def test_mergedCellsAndLivePlanningFacesRemain(self):
        """顶替方与 §6-157 并进去的两格都必须在位——否则本档的"退役"就是删掉了能力。"""
        engine = (REPO / "neurova" / "collaboration" / "neurflow" / "execution_engine.py").read_text(
            encoding="utf-8"
        )
        assert "asyncio.Semaphore" in engine, "层内并发上限被拆回裸 gather"
        assert "maxConcurrentNodes" in engine, "并发上限的单点入口没了"
        assert "_executeNodeWithRetry" in engine, "节点级重试没了"
        assert "NODE_RETRY" in engine, "重试事件面没了"

        models = (REPO / "neurova" / "collaboration" / "neurflow" / "models.py").read_text(encoding="utf-8")
        assert "idempotent" in models, "幂等声明格没了"

        for face in (
            ("neurova", "plan_mode", "plan_session.py"),
            ("neurova", "planning", "planning_tool.py"),
            ("neurova", "collaboration", "neurflow", "nl_designer.py"),
        ):
            assert REPO.joinpath(*face).is_file(), f"现役规划面消失：{face}"

        eps = (REPO / "neurova" / "api" / "endpoints" / "__init__.py").read_text(encoding="utf-8")
        assert "plan_mode" in eps or "/v1/plans" in eps, "HTTP 规划面的挂载点不见了"

    def test_facadeMustNotClaimRetiredMembers(self):
        """包门面的**核心模块清单**不得把已退成员列为在役模块（§6-115 的名实分离形态）。

        判的是清单条目那个形状（`- plan_orchestrator: ...`），不是"文件里出现这个名字"——
        退役说明本身要提它，按字符串包含判就会把交代历史的那句一起咬掉（两头失真）。
        """
        facade = (REPO / "neurova" / "execution_engine" / "__init__.py").read_text(encoding="utf-8")
        claimed = re.search(r"^\s*-\s*plan_orchestrator\s*[:：]", facade, re.MULTILINE)
        assert claimed is None, f"门面把已退的编排器仍列作在役成员：{claimed and claimed.group(0)!r}"
