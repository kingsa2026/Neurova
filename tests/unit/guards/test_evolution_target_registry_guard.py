"""架构守卫：注册表禁改清单与计划书 §3.1 逐条一致（P0-1）。

禁改内核清单是"内核先于演化 / 裁判在演化集合之外"两原则的落点。
清单被静默缩水（删项、改路径）即守护失效——本守卫把计划书 §3.1
「禁改内核首批清单」文本里的路径逐条钉死，注册表与文档不一致即红。

注册表内容变更 = 改规则：只走人工 PR + 本守卫红绿，不进任何自动通道。
"""

import re
from pathlib import Path

import pytest

from neurova.evolution.rsi.target_registry import (
    MutableTargetError,
    get_target_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_DOC = (
    REPO_ROOT / "docs" / "04-plans"
    / "2026-11-21-recursive-self-evolution-plan.md"
)


def _docForbiddenPaths() -> set:
    """从计划书 §3.1「禁改内核首批清单」条目提取全部反引号路径令牌。"""
    hits = [
        line
        for line in PLAN_DOC.read_text(encoding="utf-8").splitlines()
        if "禁改内核首批清单" in line
    ]
    assert len(hits) == 1, (
        "计划书 §3.1 禁改清单条目应恰有一行；文档结构变更时同步改本守卫"
    )
    tokens = re.findall(r"`([^`]+)`", hits[0])
    return {token for token in tokens if "/" in token}


def test_registryForbiddenListMatchesPlanDoc():
    """注册表禁改 locator 集合 == 计划书 §3.1 清单集合。

    少一项 = 清单被静默缩水；多一项 = 未经人工门私改清单。两个方向都红。
    """
    registry = get_target_registry()
    registered = {t.locator for t in registry.forbiddenTargets()}
    assert registered == _docForbiddenPaths()


def test_everyForbiddenTargetIsLockedAndSurvivalCritical():
    """九项逐条：gateLevel=forbidden、survivalCritical、assertMutable 拒绝。"""
    registry = get_target_registry()
    forbidden = registry.forbiddenTargets()
    assert len(forbidden) == 9
    for target in forbidden:
        assert target.gateLevel == "forbidden", target.targetId
        assert target.survivalCritical is True, target.targetId
        with pytest.raises(MutableTargetError):
            registry.assertMutable(target.targetId)


def test_kernelLocatorPathsExistOnDisk():
    """禁改 locator 指向真实路径（survival_probe.py 已随 P0-2 落地，正式校验）。"""
    repo = REPO_ROOT
    missing = [
        target.locator
        for target in get_target_registry().forbiddenTargets()
        if not (repo / target.locator).exists()
    ]
    assert missing == [], f"禁改清单指向不存在的路径: {missing}"
