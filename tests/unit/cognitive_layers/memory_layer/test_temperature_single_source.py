# -*- coding: utf-8 -*-
"""Issue #74 · 温度衰减实现收敛守卫（先红后绿）。

根因（不是形状）：仓库里并存两套温度衰减实现。

- **权威一套** `memory_layer/temperature.py::TemperatureEngine`（0–100 量纲）：
  被 `manager.run_decay_cycle` / `agent_core` / `mem_core` / `sleep` / `eval_harness`
  真实调用，带情感保护、饱和效应、重要性加权、关联保护、生命周期阶段、
  固化豁免 —— 多因子贝叶斯模型。
- **旁支一套** `memory_layer/modules/temperature_module.py::TemperatureModule`
  （0–1 量纲）：整文件零生产消费者，单因子 `exp(-rate*hours)`，没有情感/重要性/
  关联/生命周期任何一维。它既不是"更弱的同款"，也不是"更强的替代"——
  它是**第二份事实源**（教义第 6 条）。

本守卫锁三件事：

1. **单一事实源**：第二套实现不得存在，且不得被重新加回；
2. **取长补短真的落地**：权威实现吸收旁支的「连续衰减」特质——
   原 `_calculate_curve_factor` 是 4 段阶跃函数，在 1/7/30 天处有 **50% 相对跳变**
   （两名记忆 idle 时间相差 1 秒，衰减因子可差 2 倍），这既是建模缺陷，
   也是既有红灯 `tests/unit/memory/core/test_temperature.py::test_ebbinghaus_curve`
   （`assert 9.375 > 9.375`）的根因。收敛时一并根修。
3. **无残余引用**：已退役模块不得被生产代码或测试重新 import。

判据可证伪：把第二套实现加回、把曲线改回阶跃、或恢复任一引用，本守卫必红。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 权威实现（唯一允许的衰减模型载体）
CANONICAL_TEMPERATURE = "neurova/cognitive_layers/memory_layer/temperature.py"

# Issue #74 点名的旁支温度实现（退役目标）
RETIRED_TEMPERATURE_MODULE = "neurova/cognitive_layers/memory_layer/modules/temperature_module.py"

# 阶跃边界的允许跳变上限（相对变化）。连续曲线远低于此；原 4 段阶跃为 50%。
MAX_RELATIVE_STEP = 0.05


def _tracked_py() -> list:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "*.py"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    ).stdout.split()
    return [p for p in out if "__pycache__" not in p and (PROJECT_ROOT / p).is_file()]


def _imported_modules(path: str) -> set:
    tree = ast.parse(io.open(PROJECT_ROOT / path, encoding="utf-8", errors="replace").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


class TestSecondTemperatureImplementationIsRetired:
    """教义第 6 条：一份参数/口径只允许一处定义。"""

    def test_sidecar_module_file_gone(self):
        assert not (PROJECT_ROOT / RETIRED_TEMPERATURE_MODULE).exists(), (
            f"{RETIRED_TEMPERATURE_MODULE} 是第二套温度衰减实现（零生产消费者、"
            "单因子、0-1 量纲），已退役，不得重新加回。"
        )

    def test_no_duplicate_decay_curve_definition(self):
        """全仓只允许一处"衰减曲线/衰减率"计算函数。"""
        offenders = []
        for path in _tracked_py():
            tree = ast.parse(io.open(PROJECT_ROOT / path, encoding="utf-8", errors="replace").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                name = node.name
                if name in ("_calculate_curve_factor", "calculate_curve_factor"):
                    offenders.append(f"{path}::{name}")
        assert offenders == [f"{CANONICAL_TEMPERATURE}::_calculate_curve_factor"], (
            "衰减曲线算子在仓库内出现多份定义（第二份事实源）：\n"
            + "\n".join(f"  - {o}" for o in offenders)
            + f"\n权威载体应为 {CANONICAL_TEMPERATURE}。"
        )

    def test_no_code_imports_retired_module(self):
        offenders = []
        for path in _tracked_py():
            if path == RETIRED_TEMPERATURE_MODULE:
                continue
            for mod in _imported_modules(path):
                if "temperature_module" in mod:
                    offenders.append(f"{path}: {mod}")
        assert not offenders, (
            "仍有代码引用已退役的第二套温度实现：\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )


class TestDecayCurveIsContinuous:
    """取长补短：把旁支的"连续衰减"特质吸收进权威实现。

    原实现是 4 段阶跃（2.0 / 1.0 / 0.5 / 0.2），在 1 / 7 / 30 天处硬跳变。
    连续化后：同一 idle 天数的微小扰动不应对衰减因子造成跳变。
    """

    @staticmethod
    def _engine():
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        return TemperatureEngine

    @pytest.mark.parametrize("boundary", [1.0, 7.0, 30.0])
    def test_no_knife_edge_at_segment_boundary(self, boundary):
        engine = self._engine()
        before = engine._calculate_curve_factor(boundary - 1e-6)
        after = engine._calculate_curve_factor(boundary + 1e-6)
        rel = abs(after - before) / max(abs(before), 1e-12)
        assert rel <= MAX_RELATIVE_STEP, (
            f"衰减因子在 idle={boundary} 天处仍为阶跃："
            f"{before} → {after}（相对跳变 {rel:.1%}）。\n"
            "阶跃曲线会让相差 1 微秒的两条记忆衰减量相差成倍——这是建模缺陷，"
            "也是 test_ebbinghaus_curve 红灯的根因。"
        )

    def test_curve_is_monotone_non_increasing(self):
        engine = self._engine()
        days = [0.5, 1.0, 1.5, 3.0, 7.0, 12.0, 30.0, 45.0, 90.0, 200.0, 1000.0]
        factors = [engine._calculate_curve_factor(d) for d in days]
        for prev_d, prev_f, cur_d, cur_f in zip(days, factors, days[1:], factors[1:]):
            assert cur_f <= prev_f + 1e-12, (
                f"衰减因子必须随 idle 天数单调不增：{prev_d}天={prev_f} > {cur_d}天={cur_f}"
            )

    def test_curve_keeps_empirical_anchors(self):
        """取长补短不是推翻：原有经验锚点（1/7/30/90 天）必须原样保留。"""
        engine = self._engine()
        assert engine._calculate_curve_factor(0.5) == pytest.approx(2.0, abs=1e-6)
        assert engine._calculate_curve_factor(1.0) == pytest.approx(2.0, abs=1e-6)
        assert engine._calculate_curve_factor(7.0) == pytest.approx(1.0, abs=1e-6)
        assert engine._calculate_curve_factor(30.0) == pytest.approx(0.5, abs=1e-6)
        assert engine._calculate_curve_factor(90.0) == pytest.approx(0.2, abs=1e-6)
        assert engine._calculate_curve_factor(3650.0) == pytest.approx(0.2, abs=1e-6)

    def test_ebbinghaus_red_light_is_turned_green(self):
        """既有红灯的根因就在这条曲线上：idle 越长衰减量必须越大。

        `tests/unit/memory/core/test_temperature.py::test_ebbinghaus_curve`
        原为红：idle=1 天落在阶跃边界，因子取到 1.0（而非 2.0），
        与 idle=6 天同因子 → 两次 decay_amount 相等（9.375 == 9.375）。
        """
        engine = self._engine()
        one_day = engine().on_decay(current_temp=50.0, days_idle=1.000001)
        six_days = engine().on_decay(current_temp=50.0, days_idle=6.0)
        assert one_day["decay_amount"] > six_days["decay_amount"], (
            f"idle=1 天衰减量 {one_day['decay_amount']} 应大于 idle=6 天 "
            f"{six_days['decay_amount']}（阶跃边界仍在吞掉 1 天档的因子）"
        )


class TestOnlyOneDecayModelIsLoadable:
    """反向控制：守卫不得退化成"文件不存在即通过"。"""

    def test_canonical_engine_is_importable_and_used(self):
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        assert hasattr(TemperatureEngine, "on_decay")
        assert callable(TemperatureEngine._calculate_curve_factor)

    def test_scanner_really_walks_the_repo(self):
        files = _tracked_py()
        assert len(files) > 500, f"扫描到的 py 文件数异常（{len(files)}），守卫可能在空转"
        assert CANONICAL_TEMPERATURE in files


# ══════════════════════════════════════════════════════════════
# Issue #74 · 其余 5 组成建制死码的退役锁定（放大视角，教义第 5 条）
# ══════════════════════════════════════════════════════════════

# 逐条复核过生产/测试消费者的整文件死码。每项都给出「权威替代或退役理由」，
# 不留下"删了但说不清去向"的黑洞。
RETIRED_DEAD_MODULES = {
    "neurova/cognitive_layers/memory_layer/memory_layer.py":
        "AgentMemoryLayer 门面，全仓零引用；其 run_decay_cycle 调用"
        "TemperatureEngine 上不存在的同名方法（一旦被调必炸）。"
        "Agent 级记忆入口是 manager.MemoryManager。",
    "neurova/cognitive_layers/memory_layer/schema.py":
        "第二套 memories DDL + FTS5 + memory_relations + trigger_chains，"
        "全仓无人建表。记忆库唯一建表点在 manager.py 建库路径"
        "（db_migration.py 亦以之为基线）。",
    "neurova/cognitive_layers/memory_layer/bm25.py":
        "零消费者。检索侧 BM25 由 api/endpoints/semantic_search_api.py 与"
        "knowledge 域自持实现承载。",
    "neurova/cognitive_layers/memory_layer/enhanced_retrieval.py":
        "零消费者。检索唯一入口是 neurova_recall.NeurovaRecallEngine。",
    "neurova/cognitive_layers/memory_layer/unified_reasoning_engine.py":
        "零生产消费者（仅 ad-hoc 脚本与自身单测）。推理入口在"
        "cognitive_layers 的 causal_reasoning / temporal_reasoner。",
    "neurova/cognitive_layers/memory_layer/proactive_recall.py":
        "零生产消费者。主动行为入口是 proactive_question.py。",
    "neurova/cognitive_layers/memory_layer/deletion_state_manager.py":
        "零生产消费者。删除状态由 manager.forget（soft delete）承载。",
    "neurova/cognitive_layers/memory_layer/forgetting_recovery.py":
        "零消费者。遗忘恢复能力由 modules/forgetting_recovery_module.py 承载"
        "（manager 真实调用）。",
    "neurova/cognitive_layers/memory_layer/coreference_resolver.py":
        "零生产消费者（仅自身单测）。指代消解在生产链路由 LLM 会话上下文承载"
        "（chat_pipeline 带着历史轮次下发，不做独立规则式解析）。",
    "neurova/cognitive_layers/memory_layer/semantic_edge_filter.py":
        "零生产消费者（仅自身单测）。依赖图的边模型与筛选由"
        "dependency_graph.DependencyEdge（含 confidence）承载。",
    "neurova/cognitive_layers/memory_layer/memory_bus.py":
        "零消费者；模块注册/事件路由职责已由 manager 的 EventBus 承担。",
    "neurova/cognitive_layers/memory_layer/memory_field.py":
        "NeRF 记忆场（模块级 import torch，+176MB），运行时零消费方；"
        "包内惰性导出随之拆除。",
    "neurova/cognitive_layers/memory_layer/result_processor.py":
        "零生产消费者（仅 test_moe_router）。MoEMemoryRouter.retrieve 的"
        "真实消费方是 MoERetrieverAdapter。",
    "neurova/enhanced_context_builder.py":
        "旧上下文栈，仅测试引用。上下文入口是 context/ 与 agent/chat_pipeline。",
    "neurova/memory_rw_manager.py":
        "旧记忆读写栈，仅测试引用（且被已退役的 enhanced_context_builder 引用）。",
}


def _module_of(path: str) -> str:
    if path.endswith("/__init__.py"):
        return path[: -len("/__init__.py")].replace("/", ".")
    return path[: -len(".py")].replace("/", ".")


class TestOtherDeadCodeGroupsAreRetired:
    """Issue #74 点名的其余死码组：文件不在、且无人 import 回来。"""

    @pytest.mark.parametrize("rel_path", sorted(RETIRED_DEAD_MODULES))
    def test_retired_file_is_gone(self, rel_path):
        assert not (PROJECT_ROOT / rel_path).exists(), (
            f"{rel_path} 已退役（{RETIRED_DEAD_MODULES[rel_path]}），不得重新加回。"
        )

    def test_no_code_imports_any_retired_module(self):
        retired = {_module_of(p) for p in RETIRED_DEAD_MODULES}
        offenders = []
        for path in _tracked_py():
            if path in RETIRED_DEAD_MODULES:
                continue
            for mod in _imported_modules(path):
                if mod in retired:
                    offenders.append(f"{path}: {mod}")
        assert not offenders, (
            "仍有代码 import 已退役模块（删文件没删引用，属静默遗留）：\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )

    def test_every_retirement_has_a_stated_destination(self):
        """每个退役项都要说清去向——不留"删了但没人知道为什么"。"""
        for path, reason in RETIRED_DEAD_MODULES.items():
            assert len(reason) >= 20, f"{path} 的退役理由过于含糊：{reason!r}"

    def test_guard_would_catch_a_reintroduction(self, tmp_path):
        """负向控制：把一个退役模块名写进文件，扫描器必须能识别。"""
        sample = tmp_path / "reintroduced.py"
        sample.write_text(
            "from neurova.cognitive_layers.memory_layer.bm25 import Bm25Index\n",
            encoding="utf-8",
        )
        retired = {_module_of(p) for p in RETIRED_DEAD_MODULES}
        tree = ast.parse(sample.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        assert retired & found, "扫描器未能识别退役模块的重新引入"
