"""架构守卫：首批 L2 代码白名单（P2-3，计划书 §6 P2-3 / §8-3 拍板）。

2026-11-21 拍板：首批 L2 白名单 = prompt 编译器 + 技能卡目录——两者都有现成
测试面且不在启动链路上。本守卫把登记逐条钉死：

- 两个对象在位，属性与拍板一致（L2 / module / approval / global）；
- L2 approval 白名单**恰为**这两项——多一项即未经人工门私扩面，少一项即缩水；
- 其余 neurova/ 模块不在白名单（白名单外 patch 一律拒的判据基础）；
- 禁改内核不受影响（forbidden 仍 fail-closed）；
- 白名单 locator 指向真实存在的文件。

注册表内容变更 = 改规则：只走人工 PR + 本守卫红绿，不进任何自动通道。
"""

from pathlib import Path

import pytest

from neurova.evolution.rsi.target_registry import (
    MutableTargetError,
    get_target_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

FIRST_BATCH_L2 = {
    "l2.promptCompiler": "neurova/context/rules_sections.py",
    "l2.skillCardCatalog": "neurova/skills/skill_service.py",
}


def test_firstBatchL2TargetsAreRegisteredWithPinnedAttributes():
    registry = get_target_registry()
    for targetId, locator in FIRST_BATCH_L2.items():
        target = registry.get(targetId)
        assert target.layer == "L2", targetId
        assert target.kind == "module", targetId
        assert target.gateLevel == "approval", targetId
        assert target.scope == "global", targetId
        assert target.locator == locator, targetId


def test_l2ApprovalWhitelistIsExactlyTheFirstBatch():
    """白名单多一项 = 私扩面，少一项 = 缩水——两个方向都红。"""
    registry = get_target_registry()
    approval = [
        target for target in registry.listByLayer("L2")
        if target.gateLevel == "approval"
    ]
    assert {target.targetId for target in approval} == set(FIRST_BATCH_L2)


def test_otherNeurovaModulesAreNotWhitelisted():
    """白名单外模块：既不在 approval 集合里，也未以任何 L2 登记项存在。"""
    registry = get_target_registry()
    approvedLocators = {
        target.locator for target in registry.listByLayer("L2")
        if target.gateLevel == "approval"
    }
    assert approvedLocators == set(FIRST_BATCH_L2.values())
    registeredL2Locators = {
        target.locator for target in registry.listByLayer("L2")
    }
    for module in (
        "neurova/agent_core.py",
        "neurova/agent/orchestrator.py",
        "neurova/api/app.py",
        "neurova/evolution/rsi/orchestrator.py",
        "neurova/evolution/rsi/pr_patch_channel.py",
    ):
        assert module not in approvedLocators, module
        assert module not in registeredL2Locators or module in (
            "neurova/agent_core.py",  # 禁改内核项本身不是白名单
        ), module


def test_forbiddenKernelRemainsFailClosed():
    registry = get_target_registry()
    with pytest.raises(MutableTargetError):
        registry.assertMutable("kernel.agentCore")
    with pytest.raises(MutableTargetError):
        registry.assertMutable("kernel.toolExecutor")


def test_whitelistedL2FilesExistOnDisk():
    registry = get_target_registry()
    missing = [
        locator for locator in FIRST_BATCH_L2.values()
        if not (REPO_ROOT / locator).exists()
    ]
    assert missing == [], f"L2 白名单指向不存在的路径: {missing}"
