"""回滚留痕与无回滚天数起算（工单 004）。

三角死锁的三个边在这里同时被拆：

    can_auto_execute("low") 需 phase>=2    deployment_controller.py:47
    phase 1→2 需 days_without_rollback>=7   deployment_controller.py:111
    days_without_rollback 空历史返回 0.0     orchestrator.py:176-184
         ↑                                          │
         └── 回滚历史只由 execute_rollback 写入 ──────┘
             而 run_iteration 的 gain<0 分支走 _restore_optimizable()（:228）
             直接改内存，从不记历史

三条锁死基线的断言在 `test_rsi_loop_baseline.py` 里仍是红的 ——
解锁还需 006 的真 roi 与 007/008 的真收敛态。
本文件只管两件事：**回滚是否留痕**、**无回滚天数从哪里起算**。

阶段一律经工单 001 的 `rsi_probe_factory` 由治理设置注入，不私赋 `_current_phase`。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

# 唯一真实梯度所在（ADR 0016 第 5 条：起点 0.85 / 目标 0.8）
GRADIENT_PARAM = "muscle_memory_threshold"


# ── 1. 真回滚必须留痕 ─────────────────────────────────────────────


def test_harmful_adjustment_records_a_rollback_entry(rsi_probe_factory, monkeypatch):
    """实测增益为负、参数被回滚时，必须在回滚历史里留下一条记录。

    这是阶段晋升判据唯一的真实数据来源。现状 `_restore_optimizable()`
    只改内存、从不写历史，于是"7 天无回滚"永远算不出非零值。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    readings = iter([1.0, 0.2])  # 应用前满分，应用后暴跌 → gain < 0
    monkeypatch.setattr(probe.orchestrator, "_measure_performance", lambda: next(readings))

    result = probe.orchestrator.run_iteration()

    assert result["applied_count"] == 0, (
        f"有害调整应被回滚使 applied_count 归零，实际 {result['applied_count']}")
    history = probe.orchestrator.rollback_manager.get_rollback_history()
    assert len(history) == 1, (
        f"回滚必须留痕（判据数据与执行动作不得两分），实际历史 {len(history)} 条")
    assert "timestamp" in history[0] and "system_state" in history[0]


def test_harmful_adjustment_restores_parameter_values(rsi_probe_factory, monkeypatch):
    """留痕的同时，参数确实回到应用前的值（原有语义不得退化）。"""
    probe = rsi_probe_factory(rsi_phase=2)
    tool_memory = probe.systems["tool_memory"]
    before = getattr(tool_memory, GRADIENT_PARAM)
    readings = iter([1.0, 0.2])
    monkeypatch.setattr(probe.orchestrator, "_measure_performance", lambda: next(readings))

    probe.orchestrator.run_iteration()

    assert getattr(tool_memory, GRADIENT_PARAM) == pytest.approx(before), (
        "回滚必须把参数还原到应用前快照")


def test_benign_adjustment_records_no_rollback(rsi_probe_factory, monkeypatch):
    """无回滚时不得伪造历史条目 —— 否则晋升判据会被假证据污染。"""
    probe = rsi_probe_factory(rsi_phase=2)
    readings = iter([0.5, 0.8])  # gain > 0
    monkeypatch.setattr(probe.orchestrator, "_measure_performance", lambda: next(readings))

    result = probe.orchestrator.run_iteration()

    assert result["applied_count"] > 0, "前置：本轮确有参数被应用"
    assert probe.orchestrator.rollback_manager.get_rollback_history() == []


# ── 2. 无回滚天数从哪里起算 ───────────────────────────────────────


def test_days_counts_from_install_when_history_is_empty(tmp_path):
    """从未回滚时，天数应距装配时刻起算而不是恒 0。

    现状 `orchestrator.py:176-184` 空历史返回 0.0，其文档串称
    "1→2 的 7 天从首次运行起算的语义由 metrics 记录承接" ——
    而 metrics 里那个键从没人写过，`orchestrator._started_at` 也因此成了
    零消费方死字段（本单把它换成可持久化的 `installed_at`）。
    """
    manager = RSIRollbackManager()
    manager.attach_persistence(tmp_path / "rsi_rollback.json")
    manager.installed_at = datetime.now(timezone.utc) - timedelta(days=9)

    assert manager.days_since_last_rollback() == pytest.approx(9, abs=0.2), (
        "无回滚记录时必须从装配时刻起算，否则 phase 1→2 永不可达")


def test_days_count_from_last_rollback_when_history_exists(tmp_path):
    manager = RSIRollbackManager()
    manager.attach_persistence(tmp_path / "rsi_rollback.json")
    snapshot_id = manager.create_snapshot(
        {GRADIENT_PARAM: {"system": "tool_memory", "value": 0.85}})
    assert manager.execute_rollback(snapshot_id) is True
    manager._rollback_history[-1]["timestamp"] = (
        datetime.now(timezone.utc) - timedelta(days=4)).isoformat()

    assert manager.days_since_last_rollback() == pytest.approx(4, abs=0.2)


def test_days_is_none_when_no_evidence_exists_at_all():
    """既无回滚历史又无装配时刻 → None（无证据），不得编造 0。

    None 之后由编排器决定"不把这个键交给判据"，
    控制器随即判 `unevidenced`（工单 003 的三态契约）。
    """
    manager = RSIRollbackManager()
    manager.installed_at = None

    assert manager.days_since_last_rollback() is None


# ── 3. 跨重启存活 ────────────────────────────────────────────────


def test_rollback_state_survives_restart(tmp_path):
    """回滚历史与装配时刻必须落盘并在重启后读回 —— 晋升判据看的是真实日历时间。"""
    path = tmp_path / "rsi_rollback.json"
    first = RSIRollbackManager()
    first.attach_persistence(path)
    install = datetime.now(timezone.utc) - timedelta(days=10)
    first.installed_at = install
    snapshot_id = first.create_snapshot({"similarity_threshold": {"system": "sleep", "value": 0.7}})
    first.execute_rollback(snapshot_id)
    assert first.save(path) is True

    restarted = RSIRollbackManager()
    restarted.attach_persistence(path)
    assert restarted.load(path) is True

    assert len(restarted.get_rollback_history()) == 1, "回滚历史重启即丢"
    assert restarted.installed_at is not None
    assert restarted.installed_at.date() == install.date()
    assert restarted.days_since_last_rollback() == pytest.approx(0, abs=0.2), (
        "刚回滚过 → 距最近一次回滚应为 0 天（而不是回到装配时刻）")


def test_execute_rollback_persists_without_explicit_save(tmp_path):
    """记账路径应自动节流落盘，与其余进化组件同协议。"""
    path = tmp_path / "rsi_rollback.json"
    manager = RSIRollbackManager()
    manager.attach_persistence(path, save_interval=0)

    manager.execute_rollback(manager.create_snapshot({"x": {"system": "sleep", "value": 0.7}}))

    assert path.exists(), "execute_rollback 未触发落盘"


def test_unattached_manager_stays_in_memory(tmp_path):
    """未挂载持久化时零 IO 副作用（与 PersistedStateMixin 的测试语义一致）。"""
    manager = RSIRollbackManager()
    assert manager.save() is False
    manager.execute_rollback(manager.create_snapshot({"x": {"system": "sleep", "value": 0.7}}))
    assert not list(tmp_path.glob("rsi_rollback.json"))


# ── 4. 编排器侧接线 ──────────────────────────────────────────────


def test_run_iteration_omits_days_key_when_unevidenced(rsi_probe_factory, monkeypatch):
    """编排器不得再把"没有读数"伪装成 0 天喂给判据。"""
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator.rollback_manager,
                        "days_since_last_rollback", lambda: None)

    captured = {}

    def _spy(metrics):
        captured.update(metrics)
        return False

    monkeypatch.setattr(probe.orchestrator.deployment_controller,
                        "evaluate_phase_transition", _spy)

    probe.orchestrator.run_iteration()

    assert "days_without_rollback" not in captured, (
        f"无证据时不得注入 days 读数，实际传入 {captured.get('days_without_rollback')!r}")


def test_run_iteration_exposes_phase_verdict(rsi_probe_factory):
    """晋升结论必须可观测：为什么没晋升、缺哪样证据。"""
    probe = rsi_probe_factory(rsi_phase=0)

    result = probe.orchestrator.run_iteration()

    assert "phase_verdict" in result, "run_iteration 未暴露晋升判据结论"
    verdict = result["phase_verdict"]
    assert verdict["state"] in {"passed", "failed", "unevidenced"}
    assert verdict["reason"], "非通过态必须写明理由"
    assert (verdict["state"] == "passed") == bool(result["phase_advanced"])


def test_orchestrator_self_attaches_rollback_persistence(rsi_probe_factory, tmp_path, monkeypatch):
    """装配时刻与回滚历史必须跨重启存活，否则晋升判据永远从 0 天起算。

    挂载点在 rsi 包内（`RSIOrchestrator.__init__`），不放 `agent_core`：
    后者受尺寸棘轮锁死；也不放 `bootstrap_evolution_persistence`：
    bootstrap 早于 per-agent 构造，覆盖不到注入进来的那个实例。
    路径仅在 `NEUROVA_EVOLUTION_ROLLBACK` 显式设置时启用 ——
    与 `NEUROVA_RSI_RECEIPTS` 同款的"未设即零 IO"约定，
    避免几十个单测各自往仓库 `data/` 里写。
    """
    from neurova.evolution.rsi.rollback_manager import resolve_rollback_state_path

    rollback_path = tmp_path / "rsi_rollback.json"

    assert resolve_rollback_state_path() is None, "未设 env 时不得隐式落盘"

    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(rollback_path))
    assert resolve_rollback_state_path() == rollback_path

    probe = rsi_probe_factory(rsi_phase=2)
    manager = probe.orchestrator.rollback_manager
    assert manager._persist_path == rollback_path, "编排器未自装配回滚持久化"

    manager.execute_rollback(manager.create_snapshot({"x": {"system": "sleep", "value": 0.7}}))
    assert rollback_path.exists(), "挂载后回滚留痕未落盘"

    restarted = RSIRollbackManager()
    restarted.attach_persistence(rollback_path)
    assert restarted.load(rollback_path) is True
    assert len(restarted.get_rollback_history()) == 1, "回滚历史跨重启丢失"


def test_first_run_pins_install_time_to_disk(tmp_path, monkeypatch):
    """从未回滚时，装配时刻必须在首次构造就落盘钉死。

    否则每次重启都把起算点重置成"现在"，"7 天无回滚"这条判据在
    任何跨重启的真实部署里都永远累计不满 —— 而这恰好是它唯一要考察的场景。
    """
    from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

    path = tmp_path / "rsi_rollback.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(path))

    first = _build_bare_orchestrator()
    install = first.rollback_manager.installed_at
    assert install is not None
    assert path.exists(), "首次构造未落盘 —— 装配时刻会在重启后丢失"

    restarted = _build_bare_orchestrator()
    assert restarted.rollback_manager.installed_at == install, (
        f"装配时刻跨重启漂移：{install} → {restarted.rollback_manager.installed_at}")

    fresh = RSIRollbackManager()
    fresh.attach_persistence(path)
    fresh.load(path)
    assert fresh.get_rollback_history() == [], "钉装配时刻不得顺手伪造回滚记录"


def test_days_guard_is_satisfied_once_install_time_ages(rsi_probe_factory, tmp_path, monkeypatch):
    """集成：装配时刻满 8 天后，phase 1→2 的"7 天无回滚"这条边不再卡住判据。

    只断言 days 这一条边 —— 晋升整体还要求真 roi（工单 006）与真收敛态
    （007/008），那两条在 `test_rsi_loop_baseline.py` 里仍是红的。
    把"死锁已解"与"链路已通"混为一句断言，就是又一次表面抹除。
    """
    rollback_path = tmp_path / "rsi_rollback.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(rollback_path))

    rsi_probe_factory(rsi_phase=1)
    # 模拟 8 个真实日历日：改写已落盘的装配时刻，再按重启语义读回
    stored = json.loads(rollback_path.read_text(encoding="utf-8"))
    stored["installed_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    rollback_path.write_text(json.dumps(stored), encoding="utf-8")

    restarted = rsi_probe_factory(rsi_phase=1)
    assert restarted.phase == 1, "前置：阶段应由治理设置注入，而非私赋"
    days = restarted.orchestrator._compute_days_without_rollback()
    assert days == pytest.approx(8, abs=0.3)

    verdict = restarted.orchestrator.deployment_controller.evaluate_phase_transition({
        "convergence_status": "converging",
        "roi": 0.1,
        "days_without_rollback": days,
    })

    assert bool(verdict) is True, (
        f"三角死锁未解：days=8 天仍被否决 —— {verdict.state} / {verdict.reason}")
    assert "days_without_rollback" not in verdict.reason


def test_days_zero_still_blocks_promotion_from_phase_one():
    """反向保护：刚回滚过（真 0 天）时不得放行 —— 修复起算点不能把否决也一并抹掉。"""
    verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition({
        "convergence_status": "converging", "roi": 0.1, "days_without_rollback": 0.0,
    })

    assert bool(verdict) is False
    assert verdict.state == "failed"


def test_two_orchestrators_do_not_share_one_rollback_timeline(rsi_probe_factory, monkeypatch):
    """回滚时间线属于各自的编排器实例，不得被并发写混成一锅。"""
    monkeypatch.delenv("NEUROVA_EVOLUTION_ROLLBACK", raising=False)
    first = rsi_probe_factory(rsi_phase=2).orchestrator
    second = rsi_probe_factory(rsi_phase=2).orchestrator

    assert first.rollback_manager is not second.rollback_manager


class _SignalOnlySystem:
    """只供反馈信号、不暴露任何可优化参数的闭环系统桩。"""

    def get_feedback(self):
        return {"success_rate": 0.5}


def _build_bare_orchestrator():
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    stubs = {name: _SignalOnlySystem() for name in
             ("sleep", "emotion", "experience", "tool_memory")}
    return RSIOrchestrator(**{f"{name}_system": system for name, system in stubs.items()})


# ── 3. 回滚判据单一事实源（工单 011）───────────────────────────


def test_should_rollback_is_the_single_decision_source(rsi_probe_factory, monkeypatch):
    """棘轮回滚必须问 `should_rollback`，不得在编排器里内联第二套判据。

    此前 `orchestrator.run_iteration` 自己写 `if gain < 0:` —— 与
    `RSIRollbackManager.should_rollback`（看 convergence / roi）判据不同。两套
    口径并存的后果是"系统认为该回滚"与"实际回滚了"会分叉：人在治理面看到
    `should_rollback` 说不用回滚，而棘轮已经悄悄把参数还原了。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    readings = iter([1.0, 0.2])  # 应用后暴跌 ⇒ 有害调整
    monkeypatch.setattr(probe.orchestrator, "_measure_performance", lambda: next(readings))

    seen: list = []
    original = probe.orchestrator.rollback_manager.should_rollback

    def _spy(metrics):
        seen.append(dict(metrics))
        return original(metrics)

    monkeypatch.setattr(probe.orchestrator.rollback_manager, "should_rollback", _spy)

    probe.orchestrator.run_iteration()

    assert seen, (
        "编排器没有问 should_rollback —— 回滚判据是内联的第二套实现"
    )
    assert any("gain" in m or "roi" in m or "convergence_status" in m for m in seen), (
        f"喂给判据的读数里没有任何回滚依据：{seen}"
    )


def test_no_inline_second_rollback_decision(rsi_probe_factory):
    """守卫：`gain < 0` 这类回滚决策不得在 `should_rollback` 之外出现第二处。"""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "neurova"
    allowed = {"neurova/evolution/rsi/rollback_manager.py"}
    offenders: list = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root.parent).as_posix()
        if rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not isinstance(node.left, ast.Name) or node.left.id != "gain":
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Lt, ast.LtE)) and (
                    isinstance(comparator, ast.Constant) and comparator.value == 0
                ):
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], (
        f"回滚判据出现第二处实现（应统一到 should_rollback）：{offenders}"
    )
