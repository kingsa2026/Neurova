"""演化对象注册表单元测试（P0-1，计划书 §3.1）。

红灯先行的断言面：
- 对任一禁改内核 targetId 调 ``assertMutable`` 必抛 ``MutableTargetError``
  （fail-closed：未知对象同样拒绝，绝不默认放行）；
- ``forbiddenTargets()`` 九项逐条在位且 gateLevel=forbidden；
- register 同 id 拒重、get 未知名报错、layer/scope/gateLevel 非法值拒收；
- 默认注册表懒创建 + 线程安全，首批可演化对象（approval 档）逐条在位。

禁改清单与计划书文本的一致性由 tests/unit/guards/ 下的架构守卫钉死，
本文件只钉注册表自身的行为契约。
"""

import threading

import pytest

from neurova.evolution.rsi.target_registry import (
    EvolutionTarget,
    EvolutionTargetRegistry,
    MutableTargetError,
    UnknownTargetError,
    get_target_registry,
)

#: 禁改内核九项的稳定 targetId（与计划书 §3.1 清单一一对应）。
FORBIDDEN_TARGET_IDS = [
    "kernel.agentCore",
    "kernel.toolExecutor",
    "kernel.llmClient",
    "kernel.contextPool",
    "kernel.identityContext",
    "kernel.dbMigration",
    "kernel.rsi.targetRegistry",
    "kernel.rsi.survivalProbe",
    "kernel.tests.unitGuards",
]

FORBIDDEN_LOCATORS = {
    "neurova/agent_core.py",
    "neurova/tool_executor.py",
    "neurova/llm_client.py",
    "neurova/context_pool.py",
    "neurova/core/identity_context.py",
    "neurova/core/db_migration.py",
    "neurova/evolution/rsi/target_registry.py",
    "neurova/evolution/rsi/survival_probe.py",
    "tests/unit/guards/",
}

#: 首批可演化对象（approval 档、scope=global、layer=L1）。
FIRST_BATCH_TARGET_IDS = [
    "rsi.parameterFamily",
    "tool.weights",
    "swarm.orchestrationParams",
    "text.soul",
    "text.constitution",
    "text.behaviorRules",
    "text.rulesSections",
]


def _freshRegistry() -> EvolutionTargetRegistry:
    """每个用例独立实例，避免共享默认单例造成计数互相污染。"""
    return EvolutionTargetRegistry()


class TestForbiddenKernel:
    """禁改内核：assertMutable fail-closed。"""

    def test_forbiddenKernelAssertMutableRaises(self):
        """对任一禁改内核 targetId 发起变更请求必被拒——红灯判据本体。"""
        registry = get_target_registry()
        for target_id in FORBIDDEN_TARGET_IDS:
            target = registry.get(target_id)
            assert target.gateLevel == "forbidden", target_id
            with pytest.raises(MutableTargetError):
                registry.assertMutable(target_id)

    def test_forbiddenTargetsNineItemsAllPresent(self):
        """forbiddenTargets() 九项逐条在位、locator 与计划书 §3.1 一致。"""
        registry = _freshRegistry()
        forbidden = registry.forbiddenTargets()
        assert len(forbidden) == 9
        assert {t.targetId for t in forbidden} == set(FORBIDDEN_TARGET_IDS)
        assert {t.locator for t in forbidden} == FORBIDDEN_LOCATORS
        assert all(t.gateLevel == "forbidden" for t in forbidden)
        assert all(t.survivalCritical is True for t in forbidden)

    def test_assertMutableUnknownTargetAlsoRejected(self):
        """未知名同样拒——fail-closed 的另一面：查无此物不等于可改。"""
        registry = _freshRegistry()
        with pytest.raises(UnknownTargetError):
            registry.assertMutable("no.such.target")

    def test_mutableTargetPassesAssertion(self):
        """approval 档对象 assertMutable 放行——守卫只拦禁改面。"""
        registry = get_target_registry()
        registry.assertMutable("rsi.parameterFamily")


class TestRegistryContract:
    """register/get/list 契约。"""

    def _target(self, targetId="demo.target", **overrides):
        fields = dict(
            targetId=targetId,
            layer="L1",
            kind="policyParam",
            locator="neurova/demo.py",
            scope="global",
            gateLevel="approval",
            survivalCritical=False,
            fallbackRef="neurova/demo.py:DEFAULTS",
            verdictSuite="rsi.eval.decision",
        )
        fields.update(overrides)
        return EvolutionTarget(**fields)

    def test_registerDuplicateIdRejected(self):
        registry = _freshRegistry()
        registry.register(self._target())
        with pytest.raises(ValueError):
            registry.register(self._target())

    def test_getUnknownRaises(self):
        registry = _freshRegistry()
        with pytest.raises(UnknownTargetError):
            registry.get("no.such.target")

    def test_getReturnsRegisteredTarget(self):
        registry = _freshRegistry()
        target = self._target()
        registry.register(target)
        assert registry.get("demo.target") is target

    def test_invalidLayerRejected(self):
        with pytest.raises(ValueError):
            self._target(layer="L4")

    def test_invalidScopeRejected(self):
        with pytest.raises(ValueError):
            self._target(scope="org")

    def test_invalidGateLevelRejected(self):
        with pytest.raises(ValueError):
            self._target(gateLevel="maybe")

    def test_invalidKindRejected(self):
        with pytest.raises(ValueError):
            self._target(kind="widget")

    def test_layerOneRequiresFallbackRef(self):
        """L1 必填 fallbackRef（默认值出处）——缺了就是半登记。"""
        with pytest.raises(ValueError):
            self._target(fallbackRef=None)

    def test_listByLayerAndGateLevel(self):
        registry = _freshRegistry()
        registry.register(self._target())
        l1 = registry.listByLayer("L1")
        assert "demo.target" in {t.targetId for t in l1}
        assert "kernel.agentCore" not in {t.targetId for t in l1}
        forbidden = registry.listByGateLevel("forbidden")
        assert {t.targetId for t in forbidden} == set(FORBIDDEN_TARGET_IDS)
        approval = registry.listByGateLevel("approval")
        assert "demo.target" in {t.targetId for t in approval}
        with pytest.raises(ValueError):
            registry.listByLayer("L9")
        with pytest.raises(ValueError):
            registry.listByGateLevel("maybe")

    def test_frozenTargetIsImmutable(self):
        target = self._target()
        with pytest.raises(Exception):
            target.gateLevel = "auto"


class TestDefaultRegistrySingleton:
    """get_target_registry()：懒创建 + 线程安全 + 内置装配。"""

    def test_lazyThreadSafeSingleton(self, monkeypatch):
        import neurova.evolution.rsi.target_registry as mod

        monkeypatch.setattr(mod, "_default_registry", None)
        results = []

        def worker():
            results.append(mod.get_target_registry())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 8
        assert len({id(r) for r in results}) == 1
        assert mod.get_target_registry() is results[0]
        # 内置禁改内核随默认实例装配，无需调用方补种。
        assert len(results[0].forbiddenTargets()) == 9

    def test_firstBatchEvolvableTargetsRegistered(self):
        """首批可演化对象：approval 档、scope=global、L1、判据与兜底齐备。"""
        registry = get_target_registry()
        for target_id in FIRST_BATCH_TARGET_IDS:
            target = registry.get(target_id)
            assert target.gateLevel == "approval", target_id
            assert target.scope == "global", target_id
            assert target.layer == "L1", target_id
            assert target.survivalCritical is False, target_id
            assert target.fallbackRef, target_id
            assert target.verdictSuite, target_id
        # 文本面 verdictSuite 指向 suite_eval；RSI 参数族指向 eval_harness 决策档。
        assert registry.get("rsi.parameterFamily").verdictSuite == "rsi.eval.decision"
        assert registry.get("text.soul").verdictSuite.startswith("suite_eval")
        # RSI 参数族 locator 指向 integration_manager 的参数表；swarm 指向 agent_limits_settings。
        assert "OPTIMIZABLE_PARAMETERS" in registry.get("rsi.parameterFamily").locator
        assert "agent_limits_settings" in registry.get("swarm.orchestrationParams").locator
        assert "closed_loop" in registry.get("tool.weights").locator
