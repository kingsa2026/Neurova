"""P3-4 · 遗传种群持久化（先红后绿）。

现状：ToolGeneticEngine 种群纯内存——重启归零，只能靠 post_chat 的
pattern_mining / genetic_evolution 两步用"新挖模式"重播种（新种子
reuse_count=0、generation=1，演化史清零）。本卡把种群纳入
bootstrap_evolution_persistence 的挂载清单，落
`<数据根>/evolution/genetic_population.json`。

锁定契约：
- 挂载后 add_to_population / record_reuse / evolve → 新实例 load：
  种群（工具序列、成功率、世代）与复用计数、validated_count 保留；
- 损坏文件回退空态不阻断；缺失文件 no-op；
- 未挂载时零 IO（不产生文件）；
- bootstrap_evolution_persistence 把 genetic_engine 挂进清单并从文件恢复；
- 关停 flush 把种群强制落盘。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype


def _population_view(engine: ToolGeneticEngine):
    """种群 → {工具序列元组: (成功率, 复用数, 世代)} 的可比视图。"""
    return {
        tuple(g.tools): (g.success_rate, g.reuse_count, g.generation)
        for g in engine.population
    }


class TestGeneticPopulationPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "genetic_population.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _seeded_engine(self) -> ToolGeneticEngine:
        engine = ToolGeneticEngine(seed=7)
        engine.attach_persistence(self.path, save_interval=0.0)
        engine.add_to_population(
            ToolGenotype(tool_sequence=["alpha", "beta"], success_rate=0.9))
        engine.add_to_population(
            ToolGenotype(tool_sequence=["gamma", "delta"], success_rate=0.85))
        return engine

    def test_roundtrip_preserves_population_reuse_and_generation(self):
        """挂载后 evolve → 重启（新实例 load）→ 种群与复用计数保留。"""
        engine = self._seeded_engine()
        engine.record_reuse(["alpha", "beta"])
        engine.record_reuse(["alpha", "beta"])
        engine.record_reuse(["gamma", "delta"])
        engine.evolve()
        expected = _population_view(engine)
        expected_validated = engine.validated_count
        self.assertTrue(expected, "前置失效：种子种群为空，本用例不成立")

        restored = ToolGeneticEngine(seed=7)
        self.assertTrue(restored.load(self.path))

        self.assertEqual(_population_view(restored), expected)
        self.assertEqual(restored.validated_count, expected_validated)

    def test_reuse_counter_survives_reload_without_reseeding(self):
        """复用计数是演化史：重启后不得从 0 重算。"""
        engine = self._seeded_engine()
        engine.record_reuse(["alpha", "beta"])
        engine.record_reuse(["alpha", "beta"])
        engine.record_reuse(["alpha", "beta"])

        restored = ToolGeneticEngine(seed=7)
        restored.load(self.path)

        view = _population_view(restored)
        self.assertEqual(view[("alpha", "beta")][1], 3)

    def test_load_missing_file_is_noop(self):
        engine = ToolGeneticEngine(seed=7)
        self.assertFalse(engine.load(Path(self.tmp.name) / "nope.json"))
        self.assertEqual(engine.population, [])

    def test_load_corrupted_file_falls_back_empty_without_blocking(self):
        self.path.write_text("{not json!!", encoding="utf-8")
        engine = ToolGeneticEngine(seed=7)
        engine.attach_persistence(self.path, save_interval=0.0)

        self.assertFalse(engine.load(self.path))
        self.assertEqual(engine.population, [])

    def test_load_truncates_oversized_population_to_configured_capacity(self):
        """恢复按当前配置的种群容量截断（容量是配置，不随文件漂移）。"""
        engine = ToolGeneticEngine(population_size=2, seed=7)
        engine.attach_persistence(self.path, save_interval=0.0)
        for i in range(5):
            engine.add_to_population(
                ToolGenotype(tool_sequence=["t1", f"t{i}"], success_rate=0.9))

        restored = ToolGeneticEngine(population_size=2, seed=7)
        restored.load(self.path)

        self.assertEqual(len(restored.population), 2)

    def test_unattached_engine_never_writes(self):
        """未挂载持久化（单例默认态）零 IO——测试/嵌入场景零污染。"""
        engine = ToolGeneticEngine(seed=7)
        engine.add_to_population(
            ToolGenotype(tool_sequence=["alpha", "beta"], success_rate=0.9))
        engine.record_reuse(["alpha", "beta"])
        engine.evolve()

        self.assertFalse(self.path.exists())

    def test_throttled_writes_coalesce_within_interval(self):
        """默认节流间隔内的连续变更不逐次落盘（与权重/模式序列同款节流）。"""
        engine = ToolGeneticEngine(seed=7)
        engine.attach_persistence(self.path)  # 默认间隔
        engine.add_to_population(
            ToolGenotype(tool_sequence=["alpha", "beta"], success_rate=0.9))
        self.assertTrue(self.path.exists())  # 首次变更立即落盘（_last_save_at=0）
        first_mtime = self.path.stat().st_mtime_ns
        engine.record_reuse(["alpha", "beta"])  # 间隔内：不写
        self.assertEqual(first_mtime, self.path.stat().st_mtime_ns)
        engine.evolve()  # 间隔内：仍不写
        self.assertEqual(first_mtime, self.path.stat().st_mtime_ns)


class TestBootstrapMountsGeneticPopulation(unittest.TestCase):
    """bootstrap_evolution_persistence 把 genetic_engine 挂进清单。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "genetic_population.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_population_file(self):
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "validated_count": 2,
                    "population": [
                        {
                            "tools": ["alpha", "beta"],
                            "success_rate": 0.9,
                            "reuse_count": 4,
                            "generation": 3,
                        },
                        {
                            "tools": ["gamma", "delta"],
                            "success_rate": 0.85,
                            "reuse_count": 1,
                            "generation": 2,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_bootstrap_mounts_and_restores_genetic_population(self):
        from neurova.evolution import closed_loop

        self._seed_population_file()
        with patch.dict(
            os.environ, {"NEUROVA_EVOLUTION_GENETIC_POPULATION": str(self.path)}
        ):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                orchestrator = closed_loop.get_evolution_orchestrator()
                self.assertEqual(orchestrator.genetic_engine._persist_path, self.path)
                view = _population_view(orchestrator.genetic_engine)
                self.assertEqual(view[("alpha", "beta")], (0.9, 4, 3))
                self.assertEqual(view[("gamma", "delta")], (0.85, 1, 2))
                self.assertEqual(orchestrator.genetic_engine.validated_count, 2)
            finally:
                closed_loop.reset_evolution_orchestrator()

    def test_flush_persists_genetic_population(self):
        """关停 flush 绕过节流，把种群强制落盘。"""
        from neurova.evolution import closed_loop

        with patch.dict(
            os.environ, {"NEUROVA_EVOLUTION_GENETIC_POPULATION": str(self.path)}
        ):
            closed_loop.reset_evolution_orchestrator()
            try:
                closed_loop.bootstrap_evolution_persistence()
                orchestrator = closed_loop.get_evolution_orchestrator()
                orchestrator.genetic_engine.add_to_population(
                    ToolGenotype(tool_sequence=["alpha", "beta"], success_rate=0.9))

                result = closed_loop.flush_evolution_persistence()

                self.assertTrue(result["genetic_engine"])
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(
                    data["population"][0]["tools"], ["alpha", "beta"])
            finally:
                closed_loop.reset_evolution_orchestrator()


if __name__ == "__main__":
    unittest.main()
