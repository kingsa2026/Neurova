"""影子验证执行器单元测试（P1-2，计划书 §3.5 / §6 P1 批 P1-2）。

验收判据（任务书 + 红灯纪律）：
- 红灯：模块本体不存在时，本文件收集期 ImportError 即红；
- 绿灯：恒等候选在隔离子进程（tmp 数据根）跑通，六判据全绿，
  注入的业务判据回调结论入账、整体 passed；
- 注入必败变更：可注入变更执行器把 create_app 换成必炸桩（不真改仓库
  文件）→ 构建判据 failed 并点名注入原因，健康/启动诚实 unevidenced，
  整体 failed；
- L2 路径：非法 patch 在 git apply --check 即 failed 并点名目标文件
  （临时 git 仓验证，不碰本仓 git 状态），且短路——不起探针子进程；
- 隔离证明：验证前后生产数据根（含仓库 data/）无新增文件，影子数据根
  与生产根物理不同；默认未注入业务回调时 G2 落 unevidenced。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from neurova.core.data_root import get_data_root
from neurova.evolution.rsi.gate_verdict import (
    STATE_FAILED,
    STATE_PASSED,
    STATE_UNEVIDENCED,
    GateVerdict,
)
# 模块本体（红灯阶段不存在 → 本文件收集期 ImportError，即红灯）。
import neurova.evolution.rsi.shadow_verify as shadow_verify_module
from neurova.evolution.rsi.shadow_verify import (
    ShadowChange,
    ShadowRunResult,
    ShadowVerify,
    aggregateOverall,
)
from neurova.evolution.rsi.survival_probe import CRITERION_ORDER

REPO_ROOT = Path(__file__).resolve().parents[4]


def _treeSnapshot(root: Path) -> set:
    """目录树快照（相对路径集合）：隔离判据用「无新增文件」而非逐字节比对。"""
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _cleanupShadowRoot(result: ShadowRunResult) -> None:
    """用毕回收影子数据根（生产上由世代编排器归档证据后负责清理）。"""
    shutil.rmtree(Path(result.dataRoot), ignore_errors=True)


class TestAggregateOverall:
    """整体结论聚合：三态词汇不降级（unevidenced 永不冒充 passed）。"""

    def test_moduleExportsPublicApi(self):
        """模块公共面齐备（同时让红灯期的本体导入有实质断言）。"""
        for name in (
            "ShadowChange",
            "ShadowRunResult",
            "ShadowVerify",
            "aggregateOverall",
            "SHADOW_CHANGE_KINDS",
        ):
            assert hasattr(shadow_verify_module, name), f"缺少公共导出 {name}"

    def test_allPassedIsPassed(self):
        verdicts = {
            "a": GateVerdict.passed("ok"),
            "b": GateVerdict.passed("ok"),
        }
        assert aggregateOverall(verdicts) == STATE_PASSED

    def test_anyFailedDominates(self):
        verdicts = {
            "a": GateVerdict.passed("ok"),
            "b": GateVerdict.failed("坏了"),
        }
        assert aggregateOverall(verdicts) == STATE_FAILED

    def test_unevidencedWithoutFailureIsUnevidenced(self):
        verdicts = {
            "a": GateVerdict.passed("ok"),
            "b": GateVerdict.unevidenced("没证据"),
        }
        assert aggregateOverall(verdicts) == STATE_UNEVIDENCED


class TestParameterOverride:
    def test_parameterOverridesLandOnHostClassInstances(self):
        """L1 机制证明：参数覆盖按词表钉到宿主类构造路径，实例携带候选值；
        词表外的族逐条点名进未应用名单，不静默丢弃。"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights
        from neurova.evolution.rsi.shadow_verify import _applyParameterOverrides

        originalInit = AdaptiveToolWeights.__init__
        try:
            applied, unapplied = _applyParameterOverrides(
                {"tool_memory": {"success_bonus": 0.9}}
            )
            assert applied == ["tool_memory.success_bonus"]
            assert unapplied == []
            # 覆盖落在构造路径上：显式传参也压不过候选值（与 setattr 语义一致）
            assert AdaptiveToolWeights(success_bonus=0.1).success_bonus == 0.9
            assert AdaptiveToolWeights().failure_penalty != 0.9

            appliedBad, unappliedBad = _applyParameterOverrides(
                {"noSuchFamily": {"x": 1}, "tool_memory": {"not_a_param": 1}}
            )
            assert appliedBad == []
            assert any("noSuchFamily.x" in item for item in unappliedBad)
            assert any(
                "tool_memory.not_a_param" in item and "词表" in item
                for item in unappliedBad
            )
        finally:
            AdaptiveToolWeights.__init__ = originalInit
            if hasattr(AdaptiveToolWeights, "_shadowOverridesApplied"):
                del AdaptiveToolWeights._shadowOverridesApplied


@pytest.mark.timeout(900)
class TestIdentityCandidate:
    def test_identityCandidateRunsFullProbeInIsolatedSubprocess(self, tmp_path):
        """绿灯判据本体：恒等候选在隔离子进程跑通，六判据全绿，整体 passed。

        走真实子进程（survival_probe.runIsolated 既有入口）+ 临时数据根；
        注入的业务判据回调作为 G2 结论入账。
        """
        productionRoot = get_data_root()
        before = _treeSnapshot(productionRoot)

        def businessCallback(change, verdicts):
            assert change.changeId == "shadow-identity-1"
            return GateVerdict.passed("测试判据：恒等候选业务面通过")

        result = ShadowVerify(businessCriteria=businessCallback).verify(
            ShadowChange(changeId="shadow-identity-1", kind="identity")
        )
        try:
            assert isinstance(result, ShadowRunResult)
            # 六判据逐项全绿
            for name in CRITERION_ORDER:
                assert name in result.verdicts, f"缺少判据 {name}"
                assert result.verdicts[name].state == STATE_PASSED, (
                    f"{name} 应通过，实际 {result.verdicts[name].state}: "
                    f"{result.verdicts[name].reason}"
                )
            # 注入的业务判据回调入账
            assert result.verdicts["g2Business"].state == STATE_PASSED
            assert result.overall == STATE_PASSED
            assert result.durationMs >= 0
            # 影子数据根与生产数据根物理不同
            assert Path(result.dataRoot) != productionRoot
            assert _treeSnapshot(productionRoot) == before
        finally:
            _cleanupShadowRoot(result)


@pytest.mark.timeout(900)
class TestInjectedFault:
    def test_poisonedCreateAppFailsBuildAndNamesIt(self, tmp_path):
        """注入必败变更（可注入执行器把 create_app 换成必炸桩）→ 构建 failed
        且点名注入原因；健康/启动无应用可探 → 诚实 unevidenced；整体 failed。
        不真改仓库文件——桩只存在于影子子进程内。
        """
        helperDir = tmp_path / "shadowExecutors"
        helperDir.mkdir(parents=True)
        (helperDir / "shadowPoisonExecutor.py").write_text(
            "def apply(change):\n"
            "    import neurova.api.app as appModule\n"
            "    def boom(*args, **kwargs):\n"
            "        raise RuntimeError('影子注入：装配爆炸')\n"
            "    appModule.create_app = boom\n",
            encoding="utf-8",
        )
        change = ShadowChange(
            changeId="shadow-poison-1",
            kind="identity",
            executorRef="shadowPoisonExecutor:apply",
        )
        result = ShadowVerify(extraSysPath=[str(helperDir)]).verify(change)
        try:
            byId = result.verdicts
            assert byId["build"].state == STATE_FAILED
            assert "装配爆炸" in byId["build"].reason
            assert byId["health"].state == STATE_UNEVIDENCED
            assert byId["startup"].state == STATE_UNEVIDENCED
            assert result.overall == STATE_FAILED
        finally:
            _cleanupShadowRoot(result)


class TestPatchCandidate:
    def test_illegalPatchFailsAtGitApplyCheck(self, tmp_path):
        """L2 路径：非法 patch 在 git apply --check 即 failed 并点名目标文件。

        临时 git 仓验证，不碰本仓 git 状态；补丁进不了隔离工作区即短路，
        不起探针子进程（无六判据结论）。
        """
        repo = tmp_path / "patchRepo"
        (repo / "neurova").mkdir(parents=True)
        (repo / "neurova" / "demo.py").write_text("value = 1\n", encoding="utf-8")
        git = lambda *args: subprocess.run(  # noqa: E731
            ["git", *args], cwd=str(repo), capture_output=True,
            encoding="utf-8", errors="replace",
        )
        assert git("init", "-q").returncode == 0
        assert git("add", ".").returncode == 0

        change = ShadowChange(
            changeId="shadow-patch-1",
            kind="patch",
            targetFile="neurova/demo.py",
            patch="这不是一个合法的 unified diff",
        )
        result = ShadowVerify(workspace=repo).verify(change)

        assert "patchApply" in result.verdicts
        assert result.verdicts["patchApply"].state == STATE_FAILED
        assert "neurova/demo.py" in result.verdicts["patchApply"].reason
        assert result.overall == STATE_FAILED
        # 短路证明：补丁没进隔离工作区，探针判据一项都不该出现
        for name in CRITERION_ORDER:
            assert name not in result.verdicts


@pytest.mark.timeout(900)
class TestIsolation:
    def test_productionDataRootUntouchedByVerification(self, tmp_path):
        """隔离证明：验证前后生产数据根（含仓库 data/）无新增文件，
        影子数据根与生产根物理不同；默认未注入业务回调时 G2 落 unevidenced。
        """
        productionRoot = get_data_root()
        before = _treeSnapshot(productionRoot)
        repoData = REPO_ROOT / "data"
        repoBefore = _treeSnapshot(repoData)

        result = ShadowVerify().verify(
            ShadowChange(changeId="shadow-iso-1", kind="identity")
        )
        try:
            assert _treeSnapshot(productionRoot) == before
            assert _treeSnapshot(repoData) == repoBefore
            assert Path(result.dataRoot) != productionRoot
            assert productionRoot not in Path(result.dataRoot).parents
            # 默认无业务回调：G2 诚实 unevidenced，整体随之 unevidenced
            assert result.verdicts["g2Business"].state == STATE_UNEVIDENCED
            assert result.overall == STATE_UNEVIDENCED
        finally:
            _cleanupShadowRoot(result)
