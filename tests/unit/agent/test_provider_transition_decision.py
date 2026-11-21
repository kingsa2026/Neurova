# -*- coding: utf-8 -*-
"""C5 provider 切换五结果决策测试——decideProviderTransition 纯函数判定。

五结果词表：reuse | switch_model_in_session | restart_and_resume | create_with_handoff | reject。
判定输入只来自 catalog 能力声明（_ACP_CAPABILITIES / _PLUGIN_CAPABILITIES /
_CONSERVATIVE_CAPABILITIES 同口径字段；handoff_inject 为 C5 新增维度，缺省 False 保守，
本卡不给任何 preset 加 handoff_inject=True）。fail-closed：能力缺失/未知一律保守分支。
"""
import pytest

from neurova.agent.neuacp.catalog import (
    CATALOG,
    TRANSITION_RESULTS,
    _ACP_CAPABILITIES,
    _CONSERVATIVE_CAPABILITIES,
    _PLUGIN_CAPABILITIES,
    capabilitiesFor,
    decideProviderTransition,
)


# ── 词表 ──────────────────────────────────────────────────────────────────


def test_transitionResultsIsExactlyFiveResults():
    assert TRANSITION_RESULTS == (
        "reuse",
        "switch_model_in_session",
        "restart_and_resume",
        "create_with_handoff",
        "reject",
    )
    assert len(set(TRANSITION_RESULTS)) == len(TRANSITION_RESULTS), "决策结果词表不得有重复值"


# ── 1. 未安装 → reject（fail-closed，优先于一切） ─────────────────────────


def test_targetNotInstalledRejects():
    assert (
        decideProviderTransition(
            _ACP_CAPABILITIES, _PLUGIN_CAPABILITIES, same_executor=True, target_installed=False
        )
        == "reject"
    )


def test_targetNotInstalledRejectsEvenWithHandoffEverywhere():
    both = dict(_ACP_CAPABILITIES, handoff_inject=True)
    assert decideProviderTransition(both, both, same_executor=False, target_installed=False) == "reject"


# ── 2. 跨 executor：handoff 双边具备才 create_with_handoff，否则 reject ───


def test_crossExecutorWithoutHandoffRejects():
    # 现状：目录无任何一家声明 handoff_inject → 跨 executor 一律保守 reject
    assert decideProviderTransition(_ACP_CAPABILITIES, _PLUGIN_CAPABILITIES, same_executor=False) == "reject"
    assert decideProviderTransition(_PLUGIN_CAPABILITIES, _ACP_CAPABILITIES, same_executor=False) == "reject"


def test_crossExecutorBothHandoffCreatesWithHandoff():
    current = dict(_ACP_CAPABILITIES, handoff_inject=True)
    target = dict(_PLUGIN_CAPABILITIES, handoff_inject=True)
    assert decideProviderTransition(current, target, same_executor=False) == "create_with_handoff"
    # 跨家换 executor 时即使换模型，也走新建+交接（交接工件天然带上下文）
    assert (
        decideProviderTransition(current, target, same_executor=False, model_changed=True)
        == "create_with_handoff"
    )


def test_crossExecutorOneSidedHandoffRejects():
    current_only = dict(_ACP_CAPABILITIES, handoff_inject=True)
    target_only = dict(_PLUGIN_CAPABILITIES, handoff_inject=True)
    assert decideProviderTransition(current_only, _PLUGIN_CAPABILITIES, same_executor=False) == "reject"
    assert decideProviderTransition(_ACP_CAPABILITIES, target_only, same_executor=False) == "reject"


# ── 3. 同 executor：换模型 / 复用 / 续跑 / 兜底 ───────────────────────────


def test_sameExecutorModelChangedSwitchesModelInSession():
    assert (
        decideProviderTransition(_ACP_CAPABILITIES, _ACP_CAPABILITIES, same_executor=True, model_changed=True)
        == "switch_model_in_session"
    )


def test_sameExecutorSessionReuseReuses():
    assert decideProviderTransition(_ACP_CAPABILITIES, _ACP_CAPABILITIES, same_executor=True) == "reuse"


def test_sameExecutorResumeOnlyRestartsAndResumes():
    # plugin 家：session_reuse=False、resume=True → 重启续跑
    assert (
        decideProviderTransition(_PLUGIN_CAPABILITIES, _PLUGIN_CAPABILITIES, same_executor=True)
        == "restart_and_resume"
    )
    # 换模型但目标不支持会话复用 → 不能会话内换，落到重启续跑档
    assert (
        decideProviderTransition(_PLUGIN_CAPABILITIES, _PLUGIN_CAPABILITIES, same_executor=True, model_changed=True)
        == "restart_and_resume"
    )


def test_sameExecutorNoReuseNoResumeRejects():
    assert (
        decideProviderTransition(_CONSERVATIVE_CAPABILITIES, _CONSERVATIVE_CAPABILITIES, same_executor=True)
        == "reject"
    )


# ── 4. 键缺失保守化（空 dict / None → 全 False → 兜底 reject） ────────────


def test_emptyCapsFallBackToReject():
    assert decideProviderTransition({}, {}, same_executor=True) == "reject"
    assert decideProviderTransition({}, {}, same_executor=True, model_changed=True) == "reject"
    assert decideProviderTransition({}, {}, same_executor=False) == "reject"


def test_noneCapsHandledConservatively():
    # None 与空 dict 同口径（保守缺省），不抛异常
    assert decideProviderTransition(None, None, same_executor=True) == "reject"
    assert decideProviderTransition(None, None, same_executor=False) == "reject"


# ── 5. 返回值恒属词表 ─────────────────────────────────────────────────────


def test_resultAlwaysInTransitionResults():
    cases = [
        ((_ACP_CAPABILITIES, _ACP_CAPABILITIES), {"same_executor": True}),
        ((_ACP_CAPABILITIES, _ACP_CAPABILITIES), {"same_executor": True, "model_changed": True}),
        ((_ACP_CAPABILITIES, _PLUGIN_CAPABILITIES), {"same_executor": False}),
        ((_PLUGIN_CAPABILITIES, _PLUGIN_CAPABILITIES), {"same_executor": True}),
        ((_PLUGIN_CAPABILITIES, _PLUGIN_CAPABILITIES), {"same_executor": True, "model_changed": True}),
        ((_CONSERVATIVE_CAPABILITIES, _CONSERVATIVE_CAPABILITIES), {"same_executor": True}),
        (({}, {}), {"same_executor": True}),
        (({}, {}), {"same_executor": False}),
        ((_ACP_CAPABILITIES, _ACP_CAPABILITIES), {"same_executor": True, "target_installed": False}),
    ]
    for args, kwargs in cases:
        result = decideProviderTransition(*args, **kwargs)
        assert result in TRANSITION_RESULTS, f"{args!r} {kwargs!r} → {result!r} 不在词表内"


# ── 6. 与目录声明一致性（改声明不改决策即红） ─────────────────────────────


@pytest.mark.parametrize(
    "caps,expectedSame,expectedModelChanged",
    [
        (_ACP_CAPABILITIES, "reuse", "switch_model_in_session"),
        (_PLUGIN_CAPABILITIES, "restart_and_resume", "restart_and_resume"),
        (_CONSERVATIVE_CAPABILITIES, "reject", "reject"),
    ],
    ids=["acp-profile", "plugin-profile", "conservative-profile"],
)
def test_catalogCapabilityProfilesDecideAsDeclared(caps, expectedSame, expectedModelChanged):
    assert decideProviderTransition(caps, caps, same_executor=True) == expectedSame
    assert decideProviderTransition(caps, caps, same_executor=True, model_changed=True) == expectedModelChanged


@pytest.mark.parametrize(
    "current,target",
    [(_ACP_CAPABILITIES, _PLUGIN_CAPABILITIES), (_PLUGIN_CAPABILITIES, _ACP_CAPABILITIES)],
    ids=["acp-to-plugin", "plugin-to-acp"],
)
def test_crossFamilyCatalogProfilesCurrentlyReject(current, target):
    # 本卡不给 preset 加 handoff_inject：目录两家声明均无该键，跨家决策必须保守 reject
    assert "handoff_inject" not in current
    assert "handoff_inject" not in target
    assert decideProviderTransition(current, target, same_executor=False) == "reject"


def test_everyCatalogEntryDecidesByItsEffectiveProfile():
    for tool in CATALOG:
        caps = capabilitiesFor(tool)  # 禁用工具（trae）收口为保守档
        if caps.get("session_reuse"):
            expected = "reuse"
        elif caps.get("resume"):
            expected = "restart_and_resume"
        else:
            expected = "reject"
        assert decideProviderTransition(caps, caps, same_executor=True) == expected, f"{tool} 决策与声明不符"
