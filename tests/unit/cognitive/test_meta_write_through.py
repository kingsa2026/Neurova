"""B/C 写穿透防回归测试（V3 融合）

锁定：负荷快照与认知事件必须落到统一台账（元认知单一事实源），
且不破坏既有内存热窗行为。
"""

import unittest

from neurova.cognitive_layers.meta_cognition_layer.ledger import (
    get_meta_ledger,
    reset_meta_ledger,
)


class TestLoadStateWriteThrough(unittest.TestCase):
    def setUp(self):
        reset_meta_ledger()

    def tearDown(self):
        reset_meta_cognition_all()
        reset_meta_ledger()

    def test_update_state_persists_to_ledger(self):
        from neurova.cognitive_layers.memory_layer.meta_cognition import (
            get_meta_cognition,
            reset_meta_cognition,
        )
        reset_meta_cognition()
        meta = get_meta_cognition("wt_agent")
        meta.update_state(active_tasks=3, memory_usage=0.4, response_time_ms=1500.0, error_rate=0.1)

        state = get_meta_ledger("wt_agent").latest_state("wt_agent")
        self.assertIsNotNone(state, "负荷快照应写穿透到台账")
        self.assertEqual(state["active_tasks"], 3)
        self.assertAlmostEqual(state["load_score"], state["load_score"])

    def test_state_metadata_carries_load_factors(self):
        """四因子必须随 metadata 透出（前端负荷构成视图数据源）。"""
        from neurova.cognitive_layers.memory_layer.meta_cognition import (
            get_meta_cognition,
            reset_meta_cognition,
        )
        reset_meta_cognition()
        meta = get_meta_cognition("wt_agent")
        meta.update_state(active_tasks=5, memory_usage=0.5, response_time_ms=2500.0, error_rate=0.2)
        factors = meta.get_state().metadata.get("factors")
        self.assertIsNotNone(factors)
        self.assertAlmostEqual(factors["tasks"], 0.5)
        self.assertAlmostEqual(factors["response"], 0.5)
        self.assertAlmostEqual(factors["error"], 0.2)

    def test_throttle_level_change_persists_immediately(self):
        """级别变化必须立即落库（低→高负荷切换不被节流吞掉）。"""
        from neurova.cognitive_layers.memory_layer.meta_cognition import (
            get_meta_cognition,
            reset_meta_cognition,
        )
        reset_meta_cognition()
        meta = get_meta_cognition("wt_agent")
        meta.update_state(active_tasks=0, memory_usage=0.0, response_time_ms=0.0, error_rate=0.0)
        ledger = get_meta_ledger("wt_agent")
        self.assertIsNotNone(ledger.latest_state("wt_agent"))
        # 转为高负荷（全失败 + 多任务 + 高耗时）
        meta.update_state(active_tasks=10, memory_usage=1.0, response_time_ms=9000.0, error_rate=1.0)
        high = ledger.latest_state("wt_agent")
        self.assertEqual(high["load_level"], "overload", "级别变化应立即写穿透")


def reset_meta_cognition_all():
    from neurova.cognitive_layers.memory_layer.meta_cognition import reset_meta_cognition
    reset_meta_cognition()


class TestEventWriteThrough(unittest.TestCase):
    def setUp(self):
        reset_meta_ledger()

    def tearDown(self):
        reset_meta_ledger()

    def test_record_event_persists_to_ledger(self):
        from neurova.cognitive_layers.memory_layer.modules.meta_cognition_module import (
            CognitiveProcess,
            MetaCognitionModule,
        )
        module = MetaCognitionModule(agent_id="evt_agent")
        module.init()
        module.record_event(CognitiveProcess.REASONING, "test_event", duration_ms=12.0, success=True)

        events = get_meta_ledger("evt_agent").list_events("evt_agent")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["process_type"], "reasoning" if CognitiveProcess.REASONING.value == "reasoning" else CognitiveProcess.REASONING.value)
        self.assertEqual(events[0]["description"], "test_event")

    def test_end_process_persists_to_ledger(self):
        from neurova.cognitive_layers.memory_layer.modules.meta_cognition_module import (
            CognitiveProcess,
            MetaCognitionModule,
        )
        module = MetaCognitionModule(agent_id="evt_agent2")
        module.init()
        eid = module.start_process(CognitiveProcess.RETRIEVAL)
        module.end_process(eid, "retrieve_done", success=True)

        events = get_meta_ledger("evt_agent2").list_events("evt_agent2")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["description"], "retrieve_done")


if __name__ == "__main__":
    unittest.main()
