"""演化对象注册表 —— 可演化集合与禁改内核的单一事实源（计划书 §3.1 / P0-1）。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md §2.1 三原则、
§3.1 target_registry 完整设计、§1.7 缺口 5、§6 P0 批 P0-1。

三原则里与本模块直接相关的两条：
- **内核先于演化**：可演化集合由本注册表显式圈定，核心运行时从一出生就是
  ``forbidden``，"agent 跑不起来"这一事故类别从结构上排除；
- **裁判在演化集合之外**：本注册表自身、存活探针、守卫测试目录一律
  ``forbidden``——自动演化碰不到评分标准与准入规则。

纪律约定：
- 注册表内容变更 = 改规则：只走人工 PR + 守卫测试红绿
  （tests/unit/guards/test_evolution_target_registry_guard.py 把 §3.1 清单
  逐条钉死），不进任何自动通道；
- ``assertMutable`` fail-closed：forbidden 抛 ``MutableTargetError``，
  未注册名抛 ``UnknownTargetError``——查无此物不等于可改。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = [
    "EvolutionTarget",
    "EvolutionTargetRegistry",
    "MutableTargetError",
    "UnknownTargetError",
    "get_target_registry",
    "VALID_LAYERS",
    "VALID_KINDS",
    "VALID_SCOPES",
    "VALID_GATE_LEVELS",
]

#: 层级封闭集：L1 配置态 / L2 代码态 / L3 元层（§3.1）。
VALID_LAYERS = frozenset({"L1", "L2", "L3"})
#: 对象种类封闭集（§3.1）。
VALID_KINDS = frozenset(
    {"promptTemplate", "agentDef", "toolWeight", "skillCard", "module", "policyParam"}
)
#: 作用域封闭集（§10 多租户影响面）。
VALID_SCOPES = frozenset({"global", "tenant", "agent"})
#: 门禁级别封闭集：auto 全自动 / approval 人工审批 / forbidden 禁改。
VALID_GATE_LEVELS = frozenset({"auto", "approval", "forbidden"})


class MutableTargetError(Exception):
    """对 forbidden 对象发起演化变更时抛出（fail-closed，绝不静默放行）。"""

    def __init__(self, targetId: str, message: str = ""):
        self.targetId = targetId
        super().__init__(
            message
            or f"禁改内核对象不可变更: {targetId}（gateLevel=forbidden，fail-closed）"
        )


class UnknownTargetError(KeyError):
    """查询/变更未注册的演化对象时抛出（KeyError 子类，兼容 dict 语义直觉）。"""

    def __init__(self, targetId: str):
        self.targetId = targetId
        super().__init__(f"未注册的演化对象: {targetId}")


@dataclass(frozen=True)
class EvolutionTarget:
    """一个可演化（或禁改）对象的登记项（§3.1 字面设计，frozen 不可变）。"""

    targetId: str  # 稳定 ID，如 "prompt.chatSystem"
    layer: str  # "L1" 配置态 / "L2" 代码态 / "L3" 元层
    kind: str  # promptTemplate|agentDef|toolWeight|skillCard|module|policyParam
    locator: str  # 物理定位（路径/参数路径/技能ID）
    scope: str  # "global" | "tenant" | "agent"
    gateLevel: str  # "auto" | "approval" | "forbidden"
    survivalCritical: bool = False  # 是否计入 G0 判据面
    fallbackRef: Optional[str] = None  # 降级兜底（L1 必填：默认值出处）
    verdictSuite: str = ""  # 绑定的判据套件名（forbidden 项不参与判据，留空）

    def __post_init__(self):
        if not isinstance(self.targetId, str) or not self.targetId:
            raise ValueError("targetId 必须是非空字符串")
        if not isinstance(self.locator, str) or not self.locator:
            raise ValueError("locator 必须是非空字符串")
        if self.layer not in VALID_LAYERS:
            raise ValueError(
                f"layer 非法: {self.layer!r}（合法值 {sorted(VALID_LAYERS)}）"
            )
        if self.kind not in VALID_KINDS:
            raise ValueError(f"kind 非法: {self.kind!r}（合法值 {sorted(VALID_KINDS)}）")
        if self.scope not in VALID_SCOPES:
            raise ValueError(
                f"scope 非法: {self.scope!r}（合法值 {sorted(VALID_SCOPES)}）"
            )
        if self.gateLevel not in VALID_GATE_LEVELS:
            raise ValueError(
                f"gateLevel 非法: {self.gateLevel!r}（合法值 {sorted(VALID_GATE_LEVELS)}）"
            )
        if self.layer == "L1" and not self.fallbackRef:
            # §3.1：fallbackRef 是 L1 必填的降级兜底（默认值出处），缺了就是半登记。
            raise ValueError(f"L1 对象必填 fallbackRef: {self.targetId}")


# ---------------------------------------------------------------------------
# 内置登记：禁改内核九项（§3.1 首批清单，与守卫测试逐条咬合）。
# locator 全部为仓库相对真实路径；survival_probe.py 由 P0-2 落地，先行占位。
# kernel 项不参与任何演化判据，verdictSuite 留空（空串≠缺失，是"无判据"的诚实态）。
# ---------------------------------------------------------------------------

_FORBIDDEN_KERNEL_TARGETS = (
    EvolutionTarget(
        targetId="kernel.agentCore",
        layer="L2",
        kind="module",
        locator="neurova/agent_core.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.toolExecutor",
        layer="L2",
        kind="module",
        locator="neurova/tool_executor.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.llmClient",
        layer="L2",
        kind="module",
        locator="neurova/llm_client.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.contextPool",
        layer="L2",
        kind="module",
        locator="neurova/context_pool.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.identityContext",
        layer="L2",
        kind="module",
        locator="neurova/core/identity_context.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.dbMigration",
        layer="L2",
        kind="module",
        locator="neurova/core/db_migration.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.rsi.targetRegistry",
        layer="L2",
        kind="module",
        locator="neurova/evolution/rsi/target_registry.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.rsi.survivalProbe",
        layer="L2",
        kind="module",
        locator="neurova/evolution/rsi/survival_probe.py",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
    EvolutionTarget(
        targetId="kernel.tests.unitGuards",
        layer="L2",
        kind="module",
        locator="tests/unit/guards/",
        scope="global",
        gateLevel="forbidden",
        survivalCritical=True,
    ),
)

# ---------------------------------------------------------------------------
# 内置登记：首批可演化对象（approval 档起步，scope=global，layer=L1）。
# 判据宿主对齐 §3.1：RSI 参数族=eval_harness 决策档；工具权重=task_yardstick
# 端到端标尺；swarm 编排参数=multi_agent 评测（R3 建跑批入口）；文本面=suite_eval
# 的 EvalCase（validateCaseFirst / assertCaseRedGreen）。
# fallbackRef 一律指向各对象安全默认值的真实出处（L1 必填）。
# ---------------------------------------------------------------------------

_FIRST_BATCH_TARGETS = (
    EvolutionTarget(
        targetId="rsi.parameterFamily",
        layer="L1",
        kind="policyParam",
        locator=(
            "neurova/evolution/rsi/integration_manager.py:"
            "RSIIntegrationManager.OPTIMIZABLE_PARAMETERS"
        ),
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/evolution/evolution_settings.py:_defaults",
        verdictSuite="rsi.eval.decision",
    ),
    EvolutionTarget(
        targetId="tool.weights",
        layer="L1",
        kind="toolWeight",
        locator="neurova/evolution/closed_loop.py",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/evolution/closed_loop.py:register_tool(base_weight=1.0)",
        verdictSuite="rsi.eval.taskYardstick",
    ),
    EvolutionTarget(
        targetId="swarm.orchestrationParams",
        layer="L1",
        kind="policyParam",
        locator="neurova/security/agent_limits_settings.py:DEFAULTS",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/security/agent_limits_settings.py:DEFAULTS",
        verdictSuite="benchmark.multiAgent",
    ),
    EvolutionTarget(
        targetId="text.soul",
        layer="L1",
        kind="promptTemplate",
        locator="neurova/core/agent_workspaces.py:get_agent_soul_path",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/core/agent_workspaces.py:get_agent_soul_path",
        verdictSuite="suite_eval.chat",
    ),
    EvolutionTarget(
        targetId="text.constitution",
        layer="L1",
        kind="promptTemplate",
        locator="neurova/api/endpoints/constitution_persistence.py",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/api/endpoints/constitution_persistence.py",
        verdictSuite="suite_eval.chat",
    ),
    EvolutionTarget(
        targetId="text.behaviorRules",
        layer="L1",
        kind="promptTemplate",
        locator="neurova/cognitive_layers/dreaming.py:behavior_rules",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/cognitive_layers/dreaming.py:behavior_rules",
        verdictSuite="suite_eval.chat",
    ),
    EvolutionTarget(
        targetId="text.rulesSections",
        layer="L1",
        kind="promptTemplate",
        locator="neurova/context/rules_sections.py:build_all_sections",
        scope="global",
        gateLevel="approval",
        survivalCritical=False,
        fallbackRef="neurova/context/rules_sections.py:build_all_sections",
        verdictSuite="suite_eval.chat",
    ),
)


class EvolutionTargetRegistry:
    """演化对象注册表：register / get / listByLayer / listByGateLevel /
    assertMutable / forbiddenTargets（§3.1 接口面）。

    实例创建即装配内置清单（禁改内核九项 + 首批可演化对象）；
    多线程访问经 ``threading.RLock`` 串行化（AGENTS.md §3 SQLite/单例同款纪律）。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._targets: Dict[str, EvolutionTarget] = {}
        for target in _FORBIDDEN_KERNEL_TARGETS:
            self.register(target)
        for target in _FIRST_BATCH_TARGETS:
            self.register(target)

    def register(self, target: EvolutionTarget) -> None:
        """登记一个演化对象；同 id 重注册拒绝（单一事实源，不静默覆盖）。"""
        with self._lock:
            if target.targetId in self._targets:
                raise ValueError(
                    f"演化对象重复注册: {target.targetId}"
                    "（注册表是单一事实源，重注册一律拒绝）"
                )
            self._targets[target.targetId] = target

    def get(self, targetId: str) -> EvolutionTarget:
        """按稳定 ID 取登记项；未知名抛 ``UnknownTargetError``。"""
        with self._lock:
            try:
                return self._targets[targetId]
            except KeyError:
                raise UnknownTargetError(targetId) from None

    def listByLayer(self, layer: str) -> List[EvolutionTarget]:
        """按层级列出登记项；层级非法直接拒（与构造期同一封闭集）。"""
        if layer not in VALID_LAYERS:
            raise ValueError(f"layer 非法: {layer!r}（合法值 {sorted(VALID_LAYERS)}）")
        with self._lock:
            return [t for t in self._targets.values() if t.layer == layer]

    def listByGateLevel(self, gateLevel: str) -> List[EvolutionTarget]:
        """按门禁级别列出登记项；级别非法直接拒。"""
        if gateLevel not in VALID_GATE_LEVELS:
            raise ValueError(
                f"gateLevel 非法: {gateLevel!r}（合法值 {sorted(VALID_GATE_LEVELS)}）"
            )
        with self._lock:
            return [t for t in self._targets.values() if t.gateLevel == gateLevel]

    def assertMutable(self, targetId: str) -> None:
        """断言对象可被演化变更；forbidden 即抛 ``MutableTargetError``（fail-closed）。

        未注册名同样拒绝（``UnknownTargetError``）——查无此物不等于可改。
        """
        target = self.get(targetId)
        if target.gateLevel == "forbidden":
            raise MutableTargetError(targetId)

    def forbiddenTargets(self) -> List[EvolutionTarget]:
        """全部禁改对象（供守卫测试逐条钉死，防清单被静默缩水）。"""
        return self.listByGateLevel("forbidden")


# ---------------------------------------------------------------------------
# 模块级默认注册表：懒创建 + DCL（double-checked locking）+ threading.RLock
# （AGENTS.md §3 单例纪律）。进程内全局共享同一份登记。
# ---------------------------------------------------------------------------

_default_registry: Optional[EvolutionTargetRegistry] = None
_default_registry_lock = threading.RLock()


def get_target_registry() -> EvolutionTargetRegistry:
    """取模块级默认注册表（懒创建，线程安全；内置清单随实例装配）。"""
    global _default_registry
    if _default_registry is None:
        with _default_registry_lock:
            if _default_registry is None:
                _default_registry = EvolutionTargetRegistry()
    return _default_registry
