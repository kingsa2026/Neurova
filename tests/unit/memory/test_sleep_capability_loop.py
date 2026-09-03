"""睡眠能力与写回契约测试（P3 + 写回根因）

覆盖:
- P3-8: SleepConsolidation 缺少 API 层期望的能力方法
  （start_sleep/wake/is_sleeping/get_dream_logs/get_memory_merges/get_settings...）
  → 端点全部 hasattr 失败，静默降级为 mock 假数据。
- 写回根因: write_back_consolidation_result 把"单例簇"的 source_id 也一并
  soft-forget → 每次睡眠整理都会遗忘所有未合并记忆（数据丢失）。
"""

import unittest
from unittest.mock import patch

from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
from neurova.cognitive_layers.memory_layer.sleep_writeback import write_back_consolidation_result

from tests.unit.core.test_idle_tracker_phase_loop import FakeMemoryManager, _sample_memories


def _make_consolidation():
    fake_mm = FakeMemoryManager(_sample_memories())
    return SleepConsolidation(memory_manager=fake_mm), fake_mm


class SleepCapabilityTest(unittest.TestCase):
    def test_start_sleep_runs_real_cycle_and_writes_back(self):
        sc, fake_mm = _make_consolidation()

        result = sc.start_sleep(duration_minutes=30)

        self.assertTrue(sc.is_sleeping())
        self.assertEqual(sc.get_sleep_cycles(), 1)
        self.assertNotEqual(sc.get_sleep_phase(), "awake")
        self.assertIsNotNone(sc.get_last_sleep_time())
        self.assertEqual(result["total_processed"], 3)

        self.assertEqual(set(fake_mm.forgotten), {"m1", "m2"}, "被合并的源记忆应删除，单例 m3 保留")
        self.assertTrue(fake_mm.added, "合并后的新记忆应写回")

        dreams = sc.get_dream_logs(limit=10)
        self.assertEqual(len(dreams), 1)
        self.assertEqual(set(dreams[0]["memories_involved"]), {"m1", "m2", "m3"})

        merges = sc.get_memory_merges(limit=10)
        self.assertEqual(len(merges), 1)
        self.assertEqual(set(merges[0]["source_memories"]), {"m1", "m2"})

    def test_wake_resets_state(self):
        sc, _ = _make_consolidation()
        sc.start_sleep(duration_minutes=30)

        sc.wake()

        self.assertFalse(sc.is_sleeping())
        self.assertEqual(sc.get_sleep_phase(), "awake")
        self.assertIsNotNone(sc.get_last_wake_time())
        self.assertGreaterEqual(sc.get_total_sleep_duration(), 0.0)

    def test_settings_roundtrip(self):
        sc, _ = _make_consolidation()

        sc.update_settings({"sleep_duration_minutes": 45, "unknown_key": 1})
        settings = sc.get_settings()

        self.assertEqual(settings["sleep_duration_minutes"], 45)
        self.assertNotIn("unknown_key", settings)


class WriteBackSingletonPreservationTest(unittest.TestCase):
    def test_write_back_forgets_only_merged_sources(self):
        fake_mm = FakeMemoryManager([])
        sc = SleepConsolidation()
        records = [MemoryRecord.from_dict(m) for m in _sample_memories()]

        result = sc.run_sleep_cycle(records)
        stats = write_back_consolidation_result(fake_mm, result)

        self.assertEqual(
            set(fake_mm.forgotten),
            {"m1", "m2"},
            "只有真实合并（≥2 个来源）的源记忆才应被删除；单例 m3 不应被遗忘",
        )
        self.assertEqual(stats["forgotten"], 2)


class SleepApiFallbackTest(unittest.TestCase):
    """有真实睡眠管理器时，端点必须返回真实数据，不得回退 mock 假数据"""

    def _build(self, sc):
        import types

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api.auth import create_access_token
        from neurova.api.endpoints import sleep as sleep_api

        self._auth = {"Authorization": f"Bearer {create_access_token({'sub': 'tester', 'role': 'user'})}"}
        agent = types.SimpleNamespace(sleep_consolidation=sc)
        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        client = TestClient(app)
        return client, sleep_api, agent

    def test_status_endpoint_reflects_real_state(self):
        sc, _ = _make_consolidation()
        sc.start_sleep(duration_minutes=30)
        client, sleep_api, agent = self._build(sc)

        with patch.object(sleep_api, "_get_agent", return_value=agent):
            resp = client.get("/api/v1/sleep/default/status", headers=self._auth)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_sleeping"])
        self.assertNotEqual(data["sleep_phase"], "awake")
        self.assertEqual(data["sleep_cycles"], 1)

    def test_dreams_endpoint_returns_real_data_not_mock(self):
        sc, _ = _make_consolidation()
        sc.start_sleep(duration_minutes=30)
        real_dream_id = sc.get_dream_logs(limit=1)[0]["dream_id"]
        client, sleep_api, agent = self._build(sc)

        with patch.object(sleep_api, "_get_agent", return_value=agent):
            resp = client.get("/api/v1/sleep/default/dreams", headers=self._auth)

        self.assertEqual(resp.status_code, 200)
        dreams = resp.json()
        self.assertEqual(len(dreams), 1, "应返回真实的 1 条梦境记录，而非 5 条 mock")
        self.assertEqual(dreams[0]["dream_id"], real_dream_id)

    def test_dreams_endpoint_empty_when_no_data(self):
        sc, _ = _make_consolidation()  # 未执行过睡眠 → 无梦境
        client, sleep_api, agent = self._build(sc)

        with patch.object(sleep_api, "_get_agent", return_value=agent):
            resp = client.get("/api/v1/sleep/default/dreams", headers=self._auth)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [], "管理器存在但无数据时应返回空列表，而非 mock 假数据")


if __name__ == "__main__":
    unittest.main()
