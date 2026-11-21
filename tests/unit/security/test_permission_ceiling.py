"""D2 权限天花板 rank 序（纯函数面）：组织封顶 + 派活链单入口 + 旧审批档映射。

- orgCeiling：NEUROVA_PERMISSION_CEILING 注入的组织天花板，未设/非法不封顶；
- applyOrgCeiling：按既有 _STRICTNESS 序封顶，只收紧不放宽；
- delegateMode：先 inheritPermissionMode 收窄，再套组织天花板；
- approvalModeToPermission / neuacpPermissionToPermission：旧档映射进 PermissionMode，
  不启用未实现的 AUTO 档，未知一律保守 GUARDED。
"""

import os
from unittest.mock import patch

import pytest

from neurova.security.permission_mode import (
    ORG_CEILING_ENV,
    VALID_MODE_VALUES,
    PermissionMode,
    applyOrgCeiling,
    approvalModeToPermission,
    delegateMode,
    inheritPermissionMode,
    neuacpPermissionToPermission,
    orgCeiling,
)
from neurova.security.permission_mode import _STRICTNESS  # 单一序事实源，测试直读校验

IMPLEMENTED_MODES = [m for m in PermissionMode if m is not PermissionMode.AUTO]


class TestOrgCeiling:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("plan", PermissionMode.PLAN),
            ("build", PermissionMode.BUILD),
            ("edit", PermissionMode.EDIT),
            ("yolo", PermissionMode.YOLO),
            ("guarded", PermissionMode.GUARDED),
            ("GUARDED", PermissionMode.GUARDED),  # 大小写容忍
            ("  guarded  ", PermissionMode.GUARDED),  # 空白容忍
            # "auto" 是预留档：按其既定语义（"按 BUILD 走"）落 BUILD 封顶，
            # 不返回未实现的 AUTO 档，也不因写了 auto 就静默放弃封顶。
            ("auto", PermissionMode.BUILD),
        ],
    )
    def test_validValuesParseToModes(self, raw, expected):
        assert orgCeiling({ORG_CEILING_ENV: raw}) is expected

    @pytest.mark.parametrize("raw", ["", "   ", "bogus", "full_access", "0", "None"])
    def test_invalidValuesMeanNoCeiling(self, raw):
        assert orgCeiling({ORG_CEILING_ENV: raw}) is None

    def test_missingKeyMeansNoCeiling(self):
        assert orgCeiling({}) is None

    def test_readsOsEnvironByDefault(self):
        with patch.dict(os.environ, {ORG_CEILING_ENV: "plan"}):
            assert orgCeiling() is PermissionMode.PLAN

    def test_unsetOsEnvironMeansNoCeiling(self):
        clean = {k: v for k, v in os.environ.items() if k != ORG_CEILING_ENV}
        with patch.dict(os.environ, clean, clear=True):
            assert orgCeiling() is None


class TestApplyOrgCeiling:
    def test_yoloClampedToGuardedCeiling(self):
        assert (
            applyOrgCeiling(PermissionMode.YOLO, PermissionMode.GUARDED)
            is PermissionMode.GUARDED
        )

    @pytest.mark.parametrize("mode", IMPLEMENTED_MODES)
    def test_noneCeilingKeepsMode(self, mode):
        assert applyOrgCeiling(mode, None) is mode

    @pytest.mark.parametrize("ceiling", IMPLEMENTED_MODES)
    @pytest.mark.parametrize("mode", IMPLEMENTED_MODES)
    def test_capOnlyTightens(self, mode, ceiling):
        # 封顶语义：结果 = max(strictness(mode), strictness(ceiling))，绝不放宽
        result = applyOrgCeiling(mode, ceiling)
        expected = ceiling if _STRICTNESS[mode] < _STRICTNESS[ceiling] else mode
        assert result is expected

    def test_alreadyStricterThanCeilingUnchanged(self):
        assert (
            applyOrgCeiling(PermissionMode.GUARDED, PermissionMode.BUILD)
            is PermissionMode.GUARDED
        )
        assert (
            applyOrgCeiling(PermissionMode.PLAN, PermissionMode.GUARDED)
            is PermissionMode.PLAN
        )

    def test_autoCeilingLandsOnBuild(self):
        # ceiling=AUTO 不启用未实现档位，按其既定语义落 BUILD
        assert (
            applyOrgCeiling(PermissionMode.YOLO, PermissionMode.AUTO)
            is PermissionMode.BUILD
        )

    def test_autoModeComparedAsBuildButReturnedAsIs(self):
        # mode=AUTO 按 BUILD 参与比较；比天花板严时按契约「原样」返回
        assert (
            applyOrgCeiling(PermissionMode.AUTO, PermissionMode.YOLO)
            is PermissionMode.AUTO
        )
        assert (
            applyOrgCeiling(PermissionMode.AUTO, PermissionMode.GUARDED)
            is PermissionMode.GUARDED
        )


class TestDelegateMode:
    def test_inheritThenCap_guardedParentClampsChild(self):
        # 父 GUARDED 压住子的 YOLO → GUARDED；GUARDED 已严于 BUILD 天花板 → 保持 GUARDED
        # （封顶只收紧不放宽：BUILD 天花板不可能把 GUARDED 放宽成 BUILD）
        assert (
            delegateMode(
                PermissionMode.GUARDED, PermissionMode.YOLO,
                ceiling=PermissionMode.BUILD,
            )
            is PermissionMode.GUARDED
        )

    def test_orgCeilingClampsYoloChildToBuild(self):
        # 宽松父（build）不追紧子 → 子保持 YOLO；组织天花板把 YOLO 压回 BUILD
        assert (
            delegateMode(
                PermissionMode.BUILD, PermissionMode.YOLO,
                ceiling=PermissionMode.BUILD,
            )
            is PermissionMode.BUILD
        )

    def test_orgCeilingTightensBelowParentGrant(self):
        assert (
            delegateMode(
                PermissionMode.BUILD, PermissionMode.YOLO,
                ceiling=PermissionMode.GUARDED,
            )
            is PermissionMode.GUARDED
        )

    def test_noCeilingSameAsInherit(self):
        for parent in IMPLEMENTED_MODES:
            for child in IMPLEMENTED_MODES:
                assert delegateMode(parent, child) is inheritPermissionMode(parent, child)


class TestApprovalModeToPermission:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("interactive", PermissionMode.GUARDED),  # 要人审 = 严
            ("INTERACTIVE", PermissionMode.GUARDED),
            ("auto_approve", PermissionMode.BUILD),  # 自动放行例行操作
            ("Auto_Approve", PermissionMode.BUILD),
            ("", PermissionMode.GUARDED),  # 空 → 保守
            ("   ", PermissionMode.GUARDED),
            ("unknown", PermissionMode.GUARDED),  # 未知 → 保守
            ("yolo", PermissionMode.GUARDED),  # 非既定档位一律保守
        ],
    )
    def test_mapping(self, raw, expected):
        assert approvalModeToPermission(raw) is expected


class TestNeuacpPermissionToPermission:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("chain", PermissionMode.GUARDED),  # 审批链 = 要人审
            ("CHAIN", PermissionMode.GUARDED),
            ("auto", PermissionMode.BUILD),  # 仅 L0 自动放行 → BUILD（不启用 AUTO 档）
            ("Auto", PermissionMode.BUILD),
            ("", PermissionMode.GUARDED),  # 未知/空 → 保守
            ("yolo", PermissionMode.GUARDED),
            ("full_access", PermissionMode.GUARDED),
        ],
    )
    def test_mapping(self, raw, expected):
        assert neuacpPermissionToPermission(raw) is expected


class TestResultsAreLegalModes:
    @pytest.mark.parametrize(
        "raw", ["interactive", "auto_approve", "chain", "auto", "", "x", None]
    )
    def test_mappingResultsAreImplementedPermissionModes(self, raw):
        for result in (approvalModeToPermission(raw), neuacpPermissionToPermission(raw)):
            assert isinstance(result, PermissionMode)
            assert result.value in VALID_MODE_VALUES
            assert result is not PermissionMode.AUTO  # 未实现档位不启用


class TestResolveEffectiveModeClampedByCeiling:
    """D2 收尾（跨环境请求入口 + MCP 工具/子任务两层收窄的共同根）：

    resolveEffectivePermissionMode 是治理预检（tool_executor 治理预检与
    _applyPermissionMode 均裸调本函数）的唯一模式解析口——组织天花板必须
    在解析口生效，否则请求体传 yolo 即可越过
    NEUROVA_PERMISSION_CEILING=guarded（勘察实证的越权路径）。
    """

    @staticmethod
    def _agent(agent_id="agent-ceiling-1"):
        from types import SimpleNamespace

        return SimpleNamespace(config=SimpleNamespace(agent_id=agent_id))

    def test_requestModeAboveCeilingClamped(self, monkeypatch):
        from neurova.security.permission_mode import (
            clearRequestPermissionMode,
            resolveEffectivePermissionMode,
            setRequestPermissionMode,
        )

        monkeypatch.setenv(ORG_CEILING_ENV, "guarded")
        setRequestPermissionMode(PermissionMode.YOLO)
        try:
            assert (
                resolveEffectivePermissionMode(self._agent())
                is PermissionMode.GUARDED
            )
        finally:
            clearRequestPermissionMode()

    def test_noCeilingKeepsRequestMode(self, monkeypatch):
        from neurova.security.permission_mode import (
            clearRequestPermissionMode,
            resolveEffectivePermissionMode,
            setRequestPermissionMode,
        )

        clean = {k: v for k, v in os.environ.items() if k != ORG_CEILING_ENV}
        monkeypatch.setattr(os, "environ", clean)
        setRequestPermissionMode(PermissionMode.YOLO)
        try:
            assert (
                resolveEffectivePermissionMode(self._agent()) is PermissionMode.YOLO
            )
        finally:
            clearRequestPermissionMode()

    def test_inheritedModeAboveCeilingClamped(self, monkeypatch):
        from neurova.security.permission_mode import (
            inheritedModeScope,
            resolveEffectivePermissionMode,
        )

        monkeypatch.setenv(ORG_CEILING_ENV, "guarded")
        with inheritedModeScope(PermissionMode.YOLO):
            assert (
                resolveEffectivePermissionMode(self._agent()) is PermissionMode.GUARDED
            )
