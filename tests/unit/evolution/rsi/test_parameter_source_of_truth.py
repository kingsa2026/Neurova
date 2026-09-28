"""参数事实源一致性守卫（工单 002）。

RSI 的可优化参数表横跨四处定义，任一处漏登记就会退化成静默错误行为：

| 角色 | 位置 |
|---|---|
| 参数清单 | `rsi/integration_manager.py:31-51` `OPTIMIZABLE_PARAMETERS` |
| 优化目标 | `rsi/system_performance.py:17` `SYSTEM_SETPOINTS` |
| 硬边界 | `rsi/integration_manager.py:158-165` `PARAMETER_BOUNDS` |
| 装配起点 | 各真实子系统签名默认（`agent_core.py` 显式传入者例外） |

漏登记 setpoint → `_generate_candidates_for_param` 的 `get_setpoint` 返回 None → 该参数永不产生候选
（静默不进化）；漏登记 BOUND → 走 `_PARAM_BOUND_DEFAULT = (0, 100)`（`integration_manager.py:166`）
→ 阈值/比率类参数可被复利漂移出语义域（`apply_optimization:211-213` 的夹紧形同虚设）。
"""

from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS


def _all_param_keys():
    for system_name, params in RSIIntegrationManager.OPTIMIZABLE_PARAMETERS.items():
        for param in params:
            yield system_name, param["name"]


def test_every_optimizable_param_has_a_setpoint():
    """参数清单里的每一项都必须有优化目标，否则 RSI 对它永不动作（静默死参数）。"""
    missing = [
        f"{system}.{name}"
        for system, name in _all_param_keys()
        if name not in SYSTEM_SETPOINTS.get(system, {})
    ]
    assert not missing, f"以下可优化参数未登记 SYSTEM_SETPOINTS，RSI 将静默跳过：{missing}"


def test_every_optimizable_param_has_an_explicit_bound():
    """参数清单里的每一项都必须有显式硬边界，不得依赖 (0,100) 兜底。

    兜底对 `muscle_memory_threshold`（置信度语义域 (0,1]）、三个比率参数、
    `pattern_min_support`（计数语义域）都过松：`apply_optimization` 的夹紧
    只在越界时生效，边界取 (0,100) 等于不夹紧。
    """
    defaults = RSIIntegrationManager._PARAM_BOUND_DEFAULT
    unregistered = []
    for system, name in _all_param_keys():
        bound = RSIIntegrationManager._parameter_bounds(system, name)
        if bound == defaults:
            unregistered.append(f"{system}.{name}")
    assert not unregistered, (
        f"以下参数落进 _PARAM_BOUND_DEFAULT={defaults} 兜底，边界形同虚设：{unregistered}"
    )


def test_bounds_are_tighter_than_the_default_fallback():
    """显式登记的边界必须真的比兜底窄，否则登记只是装饰。"""
    defaults = RSIIntegrationManager._PARAM_BOUND_DEFAULT
    too_loose = [
        f"{system}.{name}"
        for (system, name), bound in RSIIntegrationManager.PARAMETER_BOUNDS.items()
        if bound[0] <= defaults[0] and bound[1] >= defaults[1]
    ]
    assert not too_loose, f"以下登记的边界不比兜底窄：{too_loose}"


def test_no_phantom_parameter_lingers_in_the_registry():
    """OPTIMIZABLE_PARAMETERS 里不得有"零消费方别名"。

    治理先例（integration_manager.py:28-30 注释）：`sleep.merge_threshold` 是
    `similarity_threshold` 的别名幻影，已从清单移除。清单与 setpoint 两侧必须同步，
    不得出现只在一侧存在的键。
    """
    declared = {
        (system, name) for system, name in _all_param_keys()
    }
    targeted = {
        (system, name) for system, params in SYSTEM_SETPOINTS.items() for name in params
    }
    only_in_setpoint = targeted - declared
    assert not only_in_setpoint, (
        f"以下 setpoint 在参数清单里没有对应项（幻影或漏登记）：{sorted(only_in_setpoint)}"
    )


def test_null_fallback_system_does_not_smuggle_a_fourth_default_table(rsi_probe_factory,
                                                                      null_systems):
    """闭环系统缺席时，RSI 不得把"替身对象上的镜像默认值"当成真实性能去优化。

    实测（2026-09-19 工单 002 期间）：四系统全部由 `_NullSystem` 顶替时，
    `run_iteration()` 仍报 ``applied_count=6`` 且每条 ``applied=True``，
    并给出 ``gain=+0.111`` —— 因为增益来自
    `eval_harness._param()` 回读 `get_optimizable_parameters()`，
    读到的正是刚写进替身对象的那个值，棘轮因此"奖励自己编辑了一个空对象"。
    修法见工单 018。
    """
    probe = rsi_probe_factory(rsi_phase=2, systems=null_systems)

    result = probe.orchestrator.run_iteration()

    assert not result["applied_results"], (
        "RSI 对不存在的闭环系统回执了参数应用成功，且伪造出正增益："
        f" applied={result['applied_count']} gain={result['gain']} "
        f"细节={[r['parameter'] for r in result['applied_results']]}"
    )


def test_placeholder_system_exposes_no_optimizable_parameters(rsi_probe_factory, null_systems):
    """占位系统必须**不暴露任何参数**，从源头断掉候选生成。

    比在 apply 端拒绝更靠根因：`orchestrator.py:444` 见 current_value 为 None 即跳过候选，
    参数看不见就不会有"优化成功"的回执，也不会再有假增益。

    口径收窄（Issue #289 · 004 M2）：断言对象是**占位系统**，而不是"表里所有键"。
    `context` 族是纯参数宿主（不入 `_systems`，不产反馈信号），四闭环全缺席
    不代表上下文预算对象不存在 —— 把它一起要求为空，是拿"四闭环缺席"去否定
    一个独立的宿主，与判据本意无关，且会掩盖 context 族的真实状态。
    """
    orchestrator = rsi_probe_factory(rsi_phase=2, systems=null_systems).orchestrator
    integration_manager = orchestrator.integration_manager

    placeholders = set(integration_manager.get_placeholder_system_names())
    assert placeholders == {"sleep", "emotion", "experience", "tool_memory"}, placeholders

    optimizable = integration_manager.get_optimizable_parameters()

    leaked = {
        name: [p.name for p in optimizable.get(name, [])]
        for name in placeholders
        if optimizable.get(name)
    }
    assert not leaked, f"占位系统仍在暴露参数面：{leaked}"


def test_apply_optimization_refuses_placeholder_system(rsi_probe_factory, null_systems):
    """直接调用也必须被拒，且不得写下"成功"的回执（第二道防线）。"""
    manager = rsi_probe_factory(rsi_phase=2, systems=null_systems).orchestrator.integration_manager

    applied = manager.apply_optimization("sleep.similarity_threshold", 0.5)

    assert applied is False, "占位系统上的参数写入不得回执成功"
    assert not hasattr(manager._systems["sleep"], "similarity_threshold"), (
        "被拒的写入不得改动占位对象的状态（工单 017 A 后占位镜像已删，写入被拒即属性不被创造）")


def test_real_system_still_optimizable_beside_a_placeholder(rsi_probe_factory,
                                                           probe_tool_memory_system):
    """放大视角的反向要求：解耦不能把真实系统一起关掉。

    tool_memory 为探针桩且偏离 setpoint（0.85 vs 0.8）时，
    即使 sleep/emotion/experience 全是占位，仍须看得见它的参数面。
    """
    from neurova.agent_core import _NullSystem

    probe = rsi_probe_factory(
        rsi_phase=2,
        systems={
            "sleep": _NullSystem(),
            "emotion": _NullSystem(),
            "experience": _NullSystem(),
            "tool_memory": probe_tool_memory_system,
        },
    )

    optimizable = probe.orchestrator.integration_manager.get_optimizable_parameters()

    assert [p.name for p in optimizable["tool_memory"]], "真实系统的参数面不得被误伤"
    assert optimizable["sleep"] == [], "占位系统不得暴露参数"


def test_placeholder_signal_must_not_get_an_estimated_performance():
    """占位系统的性能分不得由"镜像属性离 setpoint 有多近"倒推出来。

    `collect_feedback_signals` 对未自报 performance_score 的系统用
    `estimate_system_performance(名称, 信号, 参数)` 补一个分 —— 对真实系统是估算，
    对替身系统就是**凭空造数**：参数面来自它自己的镜像默认值，
    分数越高只代表"这个空对象离目标越像"，这正是假链路能自持的原因。
    """
    from neurova.agent_core import _NullSystem

    class _MirrorOnly:
        """无 get_feedback 的裸替身：只有镜像属性可被回读。"""

        rsi_placeholder = True
        similarity_threshold = 0.8

    manager = RSIIntegrationManager(
        sleep_system=_MirrorOnly(), emotion_system=_NullSystem(),
        experience_system=_NullSystem(), tool_memory_system=_NullSystem(),
    )

    signals = manager.collect_feedback_signals()

    assert "performance_score" not in signals["sleep"], (
        f"替身系统被倒推出性能分：{signals['sleep']}")


def test_real_system_still_gets_its_estimated_performance(rsi_probe_factory):
    """反向锁：不得为了封替身而把真实系统的估算分一起砍掉。

    `SleepConsolidation.get_feedback()` 不自报 performance_score（集成器 docstring 里
    写明这一点，也正是当年加估算分支的理由），所以它走的是同一条注入路径。
    """
    from neurova.agent_core import _NullSystem
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    orchestrator = rsi_probe_factory(
        rsi_phase=2,
        systems={
            "sleep": SleepConsolidation(),
            "emotion": _NullSystem(),
            "experience": _NullSystem(),
            "tool_memory": _NullSystem(),
        },
    ).orchestrator

    signals = orchestrator.collect_feedback_signals()

    assert isinstance(signals["sleep"].get("performance_score"), (int, float)), (
        f"真实 sleep 系统的估算分被误伤：{signals['sleep']}")
    assert signals["sleep"].get("verdict") is None, "真实系统不得被标成无证据"


def test_placeholder_system_is_absent_from_the_escalation_channel(rsi_probe_factory):
    """人工评审通道也不许收到"请改进一个不存在的系统"的提案。

    升级判据看的是 performance < 0.5；替身今天恰好是 0.5 才没咬到，
    那是运气不是契约 —— 契约是"无证据的信号不参与判据"。
    """
    from neurova.evolution.rsi.gate_verdict import GateVerdict

    probe = rsi_probe_factory(rsi_phase=2)
    signals = {
        "sleep": {"performance_score": 0.2,
                  "verdict": GateVerdict.unevidenced("sleep 是占位替身").to_dict()},
    }

    # 工单 009 把返回形态从裸 List[str]  widening 成 {verdict, proposals, skipped}：
    # 断言不减，另加严一条——被挡下的替身系统必须点名，不得静默
    outcome = probe.orchestrator._escalate_to_proposer_if_needed(
        {"status": "diverging", "metrics": {"trend_slope": -0.1}}, signals
    )

    assert outcome["proposals"] == [], f"替身系统被升级成人工提案了：{outcome}"
    assert [s["system"] for s in outcome["skipped"]] == ["sleep"], outcome
    assert "占位替身" in outcome["skipped"][0]["reason"], outcome


def test_placeholder_marker_requires_explicit_true(rsi_probe_factory):
    """占位判定必须认显式 `rsi_placeholder = True`，不接受 truthy 嗅探。

    `MagicMock().rsi_placeholder` 恒为真值：若判定用 truthiness，
    所有拿 MagicMock 冒充闭环系统的既有测试都会被误判成占位而全线空转
    （实现期真实踩过：一次改动波及 10 条用例）。
    """
    from unittest.mock import MagicMock

    mocks = {name: MagicMock() for name in ("sleep", "emotion", "experience", "tool_memory")}
    orchestrator = rsi_probe_factory(rsi_phase=2, systems=mocks).orchestrator

    optimizable = orchestrator.integration_manager.get_optimizable_parameters()

    assert all(optimizable[name] for name in mocks), (
        "Mock 系统不应被当成占位替身："
        f" { {k: [p.name for p in v] for k, v in optimizable.items()} }"
    )


def test_run_iteration_and_summary_report_placeholder_systems(rsi_probe_factory, null_systems):
    """缺席名单要进返回值与摘要面：`applied=0` 必须区分"没对象"与"没候选"。

    工单 018 第 4 项的落点 —— 只把替身惰化还不够，看不见缺席就等于
    运维侧仍要把"这套系统根本没装配"读成"进化跑过了但没找到改进空间"。
    """
    from neurova.evolution.rsi.result_summary import summarize_rsi_result

    probe = rsi_probe_factory(rsi_phase=2, systems=null_systems)

    result = probe.orchestrator.run_iteration()

    assert sorted(result["placeholder_systems"]) == [
        "emotion", "experience", "sleep", "tool_memory",
    ], result["placeholder_systems"]
    summary = summarize_rsi_result(result)
    assert summary["placeholder_systems"] == sorted(result["placeholder_systems"]), (
        f"缺席名单没进摘要面：{summary}")


def test_phantom_systems_are_excluded_from_the_signal_fallback_reading(rsi_probe_factory,
                                                                      null_systems):
    """兜底读数也不许把替身算进去（同一根因的另一处读点，grep 出来一并收）。

    `_measure_performance_from_signals` 对四系统各估一次 setpoint 贴近度再取均值 ——
    替身那份是对着空对象的镜像默认值算出来的，正是审计里"+0.111 假增益"的读数来源。
    四系统全为替身时应当**没有读数**（返回 0.0 = 没得测），
    而不是 0.5×4 的均值冒充"系统整体性能平庸"。
    """
    orchestrator = rsi_probe_factory(rsi_phase=2, systems=null_systems).orchestrator

    assert orchestrator._measure_performance_from_signals() == 0.0, (
        "对不存在的系统估出了性能读数")


def test_fully_assembled_reports_no_placeholder(rsi_probe_factory):
    """反向锁：四系统齐备时名单为空，不得把真实系统误列进缺席面。"""
    result = rsi_probe_factory(rsi_phase=2).orchestrator.run_iteration()

    assert result["placeholder_systems"] == []
