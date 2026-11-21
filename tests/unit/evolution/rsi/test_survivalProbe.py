"""G0 存活探针单元测试（P0-2，计划书 §3.3 / §6 P0 批 P0-2）。

红灯先行的断言面（任务书四条验收）：
- 绿灯：健康环境（tmp 数据根 + 真实 ``create_app``）六项判据全 ``passed``；
- 注入故障（create_app 抛错 / 关键路由缺失 / 模型边界抛错 / 工具执行抛错）
  → 对应项 ``failed`` 且 reason 逐项点名，其余项不受牵连（探针逐项返回，
  短路语义在调用方 gate_chain）；
- ``unevidenced`` 场景：守卫子集文件缺失时报 unevidenced，不冒充 failed；
- 独立子进程语义：``runIsolated`` 起真子进程（隔离数据根注入 env）返回 JSON 结论。

探针基座与 tests/unit/agent/conftest.py 同一口径：Agent 走生产构造点，
替身只放在模型边界；写盘全部落 tmp 数据根，不碰仓库 data/。
"""

from pathlib import Path

import pytest

from neurova.evolution.rsi.gate_verdict import (
    STATE_FAILED,
    STATE_PASSED,
    STATE_UNEVIDENCED,
)

# 模块本体（红灯阶段不存在 → 本文件收集期 ImportError，即红灯）。
import neurova.evolution.rsi.survival_probe as survival_probe_module
from neurova.evolution.rsi.survival_probe import (
    CRITERION_ORDER,
    SurvivalProbe,
    runIsolated,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# 把知识库围栏的"生产目录"钉在**会话级数据根**（conftest 导入期注入的那一址）。
# 探针会在用例内把 NEUROVA_DATA_DIR 改指到本用例的隔离根；若围栏模块在那一刻
# 之后才首次导入，它的"生产目录"就会被误绑到隔离根上，启动窗里 chat 管线
# 接线将打出 2 条"测试会话禁止读写生产知识库"的 ERROR——那是围栏误伤，
# 不是被测系统跑不起来。提前导入 = 围栏的生产目录先于探针注入冻结。
import neurova.knowledge.foundation.storage_fence  # noqa: F401,E402


@pytest.fixture
def dataRoot(tmp_path):
    """隔离数据根：探针一切运行期落盘收在这里，绝不碰仓库 data/。"""
    root = tmp_path / "survivalDataRoot"
    root.mkdir(parents=True, exist_ok=True)
    return root


def byCriterion(verdicts):
    """按判据 ID 取结论（探针约定：evidence.criterion 必填）。"""
    return {v.evidence["criterion"]: v for v in verdicts}


@pytest.mark.timeout(900)
class TestHealthyEnvironment:
    def test_allSixCriteriaPassInIsolatedSubprocess(self, dataRoot):
        """绿灯判据本体：健康环境（tmp 数据根 + 真实 create_app）六项全 passed。

        走 ``runIsolated`` 子进程形态——计划书 §3.3 规定探针在独立子进程中
        运行（NEUROVA_DATA_DIR 注入隔离根，与跑测进程的测试围栏/会话级
        路径冻结解耦），这也是影子验证（P1-2）复用的唯一入口。同时验证
        子进程真实返回 JSON 结论。
        """
        result = runIsolated(dataRoot, workspace=REPO_ROOT)

        assert result["childReturnCode"] == 0
        # 子进程回读的生效数据根 = 注入的隔离根（证明 env 注入真实生效）。
        assert Path(result["dataRoot"]) == dataRoot.resolve()
        verdicts = result["verdicts"]
        assert len(verdicts) == len(CRITERION_ORDER)
        assert [v["evidence"]["criterion"] for v in verdicts] == list(CRITERION_ORDER)
        for verdict in verdicts:
            assert verdict["state"] == STATE_PASSED, (
                f"{verdict['evidence'].get('criterion')} 应通过，实际 "
                f"{verdict['state']}: {verdict['reason']}"
            )


@pytest.mark.timeout(600)
class TestInjectedFaults:
    """注入故障 → 对应项 failed 逐项点名，其余项不受牵连。"""

    def test_createAppCrashFailsBuildOnly(self, dataRoot, monkeypatch):
        """create_app 抛错：构建 failed；健康/启动诚实 unevidenced（无应用可探）；
        对话/工具/守卫走各自独立装配，不受牵连。"""
        import neurova.api.app as appModule

        def boom(*args, **kwargs):
            raise RuntimeError("装配爆炸")

        monkeypatch.setattr(appModule, "create_app", boom)
        verdicts = SurvivalProbe().probe(REPO_ROOT, dataRoot)
        byId = byCriterion(verdicts)

        # 逐项返回不短路：顺序与计划书 §3.3 一致。
        assert [v.evidence["criterion"] for v in verdicts] == list(CRITERION_ORDER)
        assert byId["build"].state == STATE_FAILED
        assert "构建" in byId["build"].reason and "装配爆炸" in byId["build"].reason
        assert byId["health"].state == STATE_UNEVIDENCED
        assert byId["startup"].state == STATE_UNEVIDENCED
        assert byId["minimalChat"].state == STATE_PASSED
        assert byId["toolExecution"].state == STATE_PASSED
        assert byId["guardSubset"].state == STATE_PASSED

    def test_missingKeyRouteFailsBuild(self, dataRoot, monkeypatch):
        """关键路由缺失：构建 failed 并点名缺哪些路由；工具/守卫不受牵连。"""
        from fastapi import FastAPI

        import neurova.api.app as appModule

        monkeypatch.setattr(appModule, "create_app", lambda *a, **k: FastAPI())
        verdicts = SurvivalProbe().probe(REPO_ROOT, dataRoot)
        byId = byCriterion(verdicts)

        assert byId["build"].state == STATE_FAILED
        assert "/v1/providers" in byId["build"].reason
        assert byId["toolExecution"].state == STATE_PASSED
        assert byId["guardSubset"].state == STATE_PASSED

    def test_modelBoundaryCrashFailsChatOnly(self, dataRoot, monkeypatch):
        """模型边界抛错：最小对话 failed 逐项点名；工具/构建/守卫不受牵连。"""

        class ExplodingModel:
            def __init__(self, *args, **kwargs):
                pass

            async def chat_stream(self, *args, **kwargs):
                raise RuntimeError("模型边界爆炸")
                yield  # pragma: no cover

            async def chat(self, *args, **kwargs):
                raise RuntimeError("模型边界爆炸")

        monkeypatch.setattr(survival_probe_module, "_StubChatModel", ExplodingModel)
        verdicts = SurvivalProbe().probe(REPO_ROOT, dataRoot)
        byId = byCriterion(verdicts)

        assert byId["minimalChat"].state == STATE_FAILED
        assert "最小对话" in byId["minimalChat"].reason
        assert "模型边界爆炸" in byId["minimalChat"].reason
        assert byId["toolExecution"].state == STATE_PASSED
        assert byId["build"].state == STATE_PASSED
        assert byId["guardSubset"].state == STATE_PASSED

    def test_toolExecutorCrashFailsToolOnly(self, dataRoot, monkeypatch):
        """工具执行抛错：工具执行 failed 逐项点名；最小对话/构建不受牵连。"""
        import neurova.tool_executor as toolExecutorModule

        class ExplodingExecutor:
            def __init__(self, agent_ref):
                pass

            async def execute(self, *args, **kwargs):
                raise RuntimeError("执行器爆炸")

        monkeypatch.setattr(toolExecutorModule, "ToolExecutor", ExplodingExecutor)
        verdicts = SurvivalProbe().probe(REPO_ROOT, dataRoot)
        byId = byCriterion(verdicts)

        assert byId["toolExecution"].state == STATE_FAILED
        assert "工具执行" in byId["toolExecution"].reason
        assert "执行器爆炸" in byId["toolExecution"].reason
        assert byId["minimalChat"].state == STATE_PASSED
        assert byId["build"].state == STATE_PASSED


@pytest.mark.timeout(300)
class TestGuardSubsetCriterion:
    def test_missingGuardFilesIsUnevidenced(self, dataRoot, monkeypatch):
        """守卫文件缺失 = 取不到证据：必须报 unevidenced，不得冒充 failed/passed。"""
        monkeypatch.setattr(
            survival_probe_module,
            "GUARD_SUBSET_FILES",
            ("tests/unit/evolution/rsi/__noSuchGuard__.py",),
        )
        verdict = SurvivalProbe()._probeGuardSubset(REPO_ROOT, dataRoot)

        assert verdict.state == STATE_UNEVIDENCED
        assert "守卫" in verdict.reason

    def test_failingGuardFileIsFailedAndNamed(self, dataRoot, tmp_path, monkeypatch):
        """反向锁：守卫子集真的在跑 pytest——注入一个必败文件，判据必须 failed
        且点名该文件，证明这一项不是恒绿。"""
        failing = tmp_path / "test_injectedFailingGuard.py"
        failing.write_text(
            "def test_injectedAlwaysFails():\n"
            "    assert False, '注入的必败守卫'\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            survival_probe_module, "GUARD_SUBSET_FILES", (str(failing),)
        )
        verdict = SurvivalProbe()._probeGuardSubset(REPO_ROOT, dataRoot)

        assert verdict.state == STATE_FAILED
        assert "test_injectedFailingGuard" in verdict.reason
