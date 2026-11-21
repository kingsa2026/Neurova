# -*- coding: utf-8 -*-
"""C2：能力目录维度扩展——新维度声明、保守缺省、双闸校验与出口形态。

新增四维：``model_switch_in_session`` / ``conversation_rollback`` / ``steer`` /
``fork``（``handoff_inject`` 为 C5 已有维度，一并纳入布尔维度单源清单）。
纪律：缺省/缺失一律按不支持处理（fail-closed）；预设只写诚实值，不臆造——
未在对应执行链上验证的能力不得声明为真。
"""
import pytest

from neurova.agent.neuacp.catalog import (
    BOOLEAN_CAPABILITY_DIMS,
    CATALOG,
    _ACP_CAPABILITIES,
    _CONSERVATIVE_CAPABILITIES,
    _PLUGIN_CAPABILITIES,
    capabilitiesFor,
    decideProviderTransition,
    refuseExecutorSpec,
)

#: C2 新增的四个能力维度
NEW_DIMENSIONS = ("model_switch_in_session", "conversation_rollback", "steer", "fork")
#: 既有能力出口五键（管理面 JSON 契约，test_catalog.py 以整字典等值钉死）
BASE_EXPORT_KEYS = {"transports", "permission_modes", "streaming", "resume", "session_reuse"}


# ── 单源清单与保守缺省 ────────────────────────────────────────────────────


def test_booleanCapabilityDimsSingleSource():
    """布尔能力维度清单单源：决策、双闸、出口共用同一份，不得另造第二份。"""
    assert BOOLEAN_CAPABILITY_DIMS == (
        "streaming",
        "resume",
        "session_reuse",
        "handoff_inject",
        "model_switch_in_session",
        "conversation_rollback",
        "steer",
        "fork",
    )
    assert len(set(BOOLEAN_CAPABILITY_DIMS)) == len(BOOLEAN_CAPABILITY_DIMS), "维度清单不得重复"


def test_conservativeCapabilitiesDeclareAllNewDimensionsFalse():
    """保守档同步扩展：新维度显式 False（缺省/缺失同义=不支持，fail-closed）。"""
    for dim in NEW_DIMENSIONS:
        assert _CONSERVATIVE_CAPABILITIES.get(dim) is False, f"保守档 {dim} 须显式 False"
    # C5 维度 handoff_inject 在保守档同样不支持
    assert _CONSERVATIVE_CAPABILITIES.get("handoff_inject", False) is False


def test_familyProfilesClaimNoUnverifiedNewDimension():
    """家档（acp/plugin）不得给未验证维度声明真值：缺失或 False，绝不 True。"""
    for profile in (_ACP_CAPABILITIES, _PLUGIN_CAPABILITIES):
        for dim in NEW_DIMENSIONS + ("handoff_inject",):
            assert profile.get(dim, False) is False, f"家档 {dim} 未确证不得声明为真"


# ── 三家 P1 预设的诚实取值 ────────────────────────────────────────────────


@pytest.mark.parametrize("tool", ["gemini-cli", "claude-code", "codex"])
def test_p1PresetsDeclareNewDimensionsHonestFalse(tool):
    """三家预设补新维度诚实值：未经执行链验证一律保守 False，不臆造。

    依据：ACP v1 通用方法面只有 session/new + session/prompt；会话内换模型、
    会话回滚、运行中插话（steer）、会话 fork 均无确证口径。
    """
    caps = CATALOG[tool]["capabilities"]
    for dim in NEW_DIMENSIONS:
        assert caps.get(dim) is False, f"{tool}.{dim} 未确证前必须保守 False"
    # 既有家档口径不被新维度稀释
    assert caps["streaming"] is True
    assert caps["session_reuse"] is True
    assert caps["resume"] is False
    assert tuple(caps["transports"]) == tuple(_ACP_CAPABILITIES["transports"])
    assert tuple(caps["permission_modes"]) == tuple(_ACP_CAPABILITIES["permission_modes"])


# ── 能力出口形态：既有五键契约不破，真值维度才透出 ────────────────────────


def test_capabilitiesExportKeepsBaseShapeForConservativeDefaults():
    """False/缺失的新维度不透出：保守出口保持五键（管理面既有契约不破）。"""
    assert set(capabilitiesFor("not-a-tool")) == BASE_EXPORT_KEYS
    assert set(capabilitiesFor("opencode")) == BASE_EXPORT_KEYS
    assert set(capabilitiesFor("zcode")) == BASE_EXPORT_KEYS


def test_capabilitiesExportSurfacesTruthyNewDimensions(monkeypatch):
    """声明为真的维度才透出（取得验证证据后前端可见），且基键仍在。"""
    caps = CATALOG["opencode"]["capabilities"]
    monkeypatch.setitem(caps, "model_switch_in_session", True)
    exported = capabilitiesFor("opencode")
    assert exported["model_switch_in_session"] is True
    assert BASE_EXPORT_KEYS <= set(exported)


# ── refuseExecutorSpec 双闸按新维度校验 ───────────────────────────────────


_LEGAL_SPEC = {"kind": "acp", "tool": "opencode", "transport": "stdio", "permission_mode": "chain"}


def test_refuseExecutorSpecRejectsUndeclaredNewDimension():
    """索取未声明的新维度能力 → 结构化拒绝，原因点名该维度。"""
    reasons = refuseExecutorSpec({**_LEGAL_SPEC, "model_switch_in_session": True})
    assert reasons, "未声明的能力必须拒绝"
    assert "model_switch_in_session" in "; ".join(reasons)


def test_refuseExecutorSpecIgnoresAbsentAndFalseRequests():
    """未索取（键缺失）或显式索取 False → 不新增违规（与既有行为一致）。"""
    assert refuseExecutorSpec(dict(_LEGAL_SPEC)) == []
    assert refuseExecutorSpec({**_LEGAL_SPEC, "model_switch_in_session": False}) == []


def test_refuseExecutorSpecPassesDeclaredCapability():
    """索取已声明能力（opencode.streaming=True）→ 放行。"""
    assert refuseExecutorSpec({**_LEGAL_SPEC, "streaming": True}) == []


def test_refuseExecutorSpecRejectsUndeclaredLegacyCapability():
    """同一机制覆盖既有布尔维：opencode resume=False，索取即拒。"""
    reasons = refuseExecutorSpec({**_LEGAL_SPEC, "resume": True})
    assert reasons, "未声明的既有能力同样必须拒绝"
    assert "resume" in "; ".join(reasons)


def test_refuseExecutorSpecUnknownToolConservativeOnNewDims():
    """未知工具按保守档判定：索取任何新维度能力都拒。"""
    reasons = refuseExecutorSpec(
        {"kind": "acp", "tool": "not-a-tool", "transport": "stdio",
         "permission_mode": "chain", "fork": True}
    )
    assert reasons and "fork" in "; ".join(reasons)


# ── 决策消费新维度（其余路径不变） ────────────────────────────────────────


def test_decisionConsumesModelSwitchDimensionOnlyForSwitchResult():
    """switch_model_in_session 结果须目标显式声明该维度；其余决策路径不变。"""
    declared = dict(_ACP_CAPABILITIES, model_switch_in_session=True)
    # 声明 + 换模型 + 会话复用 → 会话内换模型
    assert (
        decideProviderTransition(declared, declared, same_executor=True, model_changed=True)
        == "switch_model_in_session"
    )
    # 缺声明（键缺失按 False 保守）→ reject
    assert (
        decideProviderTransition(_ACP_CAPABILITIES, _ACP_CAPABILITIES, same_executor=True, model_changed=True)
        == "reject"
    )
    # 不换模型 → 仍 reuse（路径不变）
    assert decideProviderTransition(declared, declared, same_executor=True) == "reuse"
    # plugin 家（session_reuse=False）换模型 → 仍 restart_and_resume（路径不变）
    assert (
        decideProviderTransition(_PLUGIN_CAPABILITIES, _PLUGIN_CAPABILITIES, same_executor=True, model_changed=True)
        == "restart_and_resume"
    )
