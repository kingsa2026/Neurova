"""睡眠阶段功能分工 + 可配阶段时长 + 自动醒来（补齐 A，2026-09-15）

背景（审计结论）：自动阶段触发链所有阶段跑同一套整理；梦境/合并记录只有手动
start_sleep 才写；洞察端点恒空；无任何到点唤醒；状态页 phase 与 tracker 五阶段
推进脱节。

契约（先红）：
1. 递进式分工：light_sleep=只写回放梦境（不动记忆/不写合并）；deep_sleep=整理+
   合并历史+统计留存；rem=基于真实合并统计派生洞察+创造型梦境（无来源如实为空）；
   hibernate=全套（合并+洞察+problem_solving 梦境）。
2. run_sleep_cycle 默认 phase="sleep" 保持旧行为（不写梦境/合并/不落盘）——
   手动 start_sleep/shutdown 路径零回归。
3. 阶段路径周期末落盘（sleep_logs.json），重启后 /dreams /insights /merges 可读。
4. 每阶段最长停留可配（链序 浅睡→REM→深睡→休眠）：
   phase_max_minutes_light_sleep=120 / _rem=60 / _deep_sleep=180 / _hibernate=120；
   dwell 超时强制沿链推进；hibernate（链尾）超时→回 active 并 wake 记账。
5. 手动 start_sleep 以 sleep_duration_minutes 登记唤醒 deadline；监控循环
   check_auto_wake 到点自动醒；tracker 回 active（活动）同步 wake。
6. /status：sleep_phase 统一源（手动会话=deep_sleep；否则 tracker 阶段，
   active→awake）+ next_wake 字段。
7. 24h 完整周期冷却：进入休眠=跑完全链→打点，active 起 24h 内不再自动入睡；
   不完整（未达休眠）不记冷却，随时可进。
"""

import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import create_access_token
from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
from neurova.core.idle_tracker import IdleTimeTracker

_TOKEN = create_access_token({"sub": "tester", "username": "tester", "role": "user"})
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


class FakeMemoryManager:
    """最小记忆管理器桩：记录写操作（与 test_idle_tracker_phase_loop 同口径）"""

    def __init__(self, memories):
        self._mems = {m["id"]: dict(m) for m in memories}
        self.added = []
        self.forgotten = []
        self.updated = []

    def get_all_memories(self):
        return [dict(v) for v in self._mems.values()]

    def remember(self, content, **kwargs):
        mid = f"new_{len(self.added)}"
        self.added.append({"id": mid, "content": content, **kwargs})
        self._mems[mid] = {"id": mid, "content": content, **kwargs}
        return mid

    def forget(self, memory_id, soft=True):
        self.forgotten.append(memory_id)
        return True

    def update_memory(self, memory_id=None, **kwargs):
        self.updated.append(("update_memory", memory_id, kwargs))
        return True

    def update_memory_temperature(self, memory_id=None, interaction_type="recall"):
        self.updated.append(("temperature", memory_id, interaction_type))
        return True


def _sample_memories():
    """m1/m2 语义相似（同嵌入）应被合并；m3 孤立单例保留"""
    return [
        {"id": "m1", "content": "用户喜欢咖啡", "embedding": [1.0, 0.0], "temperature": 60.0,
         "importance": 0.5, "categories": ["preference"], "agent_id": "default"},
        {"id": "m2", "content": "用户喜欢咖啡和茶", "embedding": [1.0, 0.0], "temperature": 50.0,
         "importance": 0.6, "categories": ["preference"], "agent_id": "default"},
        {"id": "m3", "content": "完全不同的话题", "embedding": [0.0, 1.0], "temperature": 40.0,
         "importance": 0.3, "categories": ["misc"], "agent_id": "default"},
    ]


def _records():
    return [MemoryRecord.from_dict(m) for m in _sample_memories()]


def _make_consolidation(memories=None, **kwargs):
    mm = FakeMemoryManager(memories if memories is not None else _sample_memories())
    return SleepConsolidation(memory_manager=mm, **kwargs), mm


class PhaseCapabilityTest(unittest.TestCase):
    """问题1-3：递进式分工与旧行为保持"""

    def test_light_sleep_writes_only_dream_replay(self):
        sc, mm = _make_consolidation()
        sc.run_sleep_cycle(_records(), phase="light_sleep")
        dreams = sc.get_dream_logs(50)
        self.assertEqual(len(dreams), 1, "浅睡应写一条回放梦境")
        self.assertEqual(dreams[0]["dream_type"], "consolidation")
        # 不动记忆、不写合并/洞察
        self.assertEqual(mm.added, [])
        self.assertEqual(mm.updated, [])
        self.assertEqual(sc.get_memory_merges(50), [])
        self.assertEqual(sc.get_dream_insights(50), [])

    def test_deep_sleep_consolidates_and_records_merges(self):
        sc, mm = _make_consolidation()
        result = sc.run_sleep_cycle(_records(), phase="deep_sleep")
        self.assertGreaterEqual(result["merged_count"], 1)
        merges = sc.get_memory_merges(50)
        self.assertGreaterEqual(len(merges), 1, "深睡应写合并历史（四页签之合并）")
        self.assertEqual(merges[0]["merge_type"], "consolidation")
        # 深睡不写梦境（分工：梦境属浅睡/REM/休眠）
        self.assertEqual(sc.get_dream_logs(50), [])

    def test_rem_generates_insights_from_real_stats(self):
        sc, mm = _make_consolidation()
        sc.run_sleep_cycle(_records(), phase="deep_sleep")
        sc.run_sleep_cycle(_records(), phase="rem")
        insights = sc.get_dream_insights(50)
        self.assertGreaterEqual(len(insights), 1, "REM 应基于真实合并统计派生洞察")
        rec = insights[0]
        for key in ("insight_id", "agent_id", "timestamp", "insight_type", "content", "related_memories"):
            self.assertIn(key, rec)
        dreams = sc.get_dream_logs(50)
        self.assertEqual(len(dreams), 1)
        self.assertEqual(dreams[0]["dream_type"], "creative")

    def test_rem_without_prior_stats_stays_empty(self):
        """诚实性：没有真实合并来源就不编造洞察"""
        sc, mm = _make_consolidation()
        sc.run_sleep_cycle(_records(), phase="rem")
        self.assertEqual(sc.get_dream_insights(50), [])

    def test_hibernate_runs_full_set(self):
        sc, mm = _make_consolidation()
        sc.run_sleep_cycle(_records(), phase="hibernate")
        self.assertGreaterEqual(len(sc.get_memory_merges(50)), 1)
        self.assertGreaterEqual(len(sc.get_dream_insights(50)), 1)
        dreams = sc.get_dream_logs(50)
        self.assertEqual(dreams[0]["dream_type"], "problem_solving")

    def test_legacy_default_phase_keeps_old_behavior(self):
        """phase 缺省（shutdown/手动/过载）：只整理，不写记录、不落盘——零回归"""
        sc, mm = _make_consolidation()
        result = sc.run_sleep_cycle(_records())
        self.assertEqual(result["phase"], "sleep")
        self.assertGreaterEqual(result["merged_count"], 1)
        self.assertEqual(sc.get_dream_logs(50), [])
        self.assertEqual(sc.get_memory_merges(50), [])

    def test_dream_replay_gate_applies_to_phase_path(self):
        sc, mm = _make_consolidation()
        sc.update_settings({"dream_replay_enabled": False})
        sc.run_sleep_cycle(_records(), phase="light_sleep")
        self.assertEqual(sc.get_dream_logs(50), [], "dream_replay_enabled=False 时阶段路径也不写梦境")

    def test_phase_cycle_persists_and_reloads(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sleep_logs.json")
            sc, mm = _make_consolidation(logs_store_path=path)
            sc.run_sleep_cycle(_records(), phase="deep_sleep")
            sc2, _ = _make_consolidation(logs_store_path=path)
            self.assertGreaterEqual(len(sc2.get_memory_merges(50)), 1, "阶段产生的合并记录重启后可读")


class PhaseMaxSettingsTest(unittest.TestCase):
    """问题4：每阶段最长停留设置键

    默认值按用户定义的阶段链 浅睡→REM→深睡→休眠 与整觉预算：
    浅睡 120 / REM 60 / 深睡 180 / 休眠 120 分钟。
    """

    def test_default_keys_and_values(self):
        sc, mm = _make_consolidation()
        s = sc.get_settings()
        self.assertEqual(s["phase_max_minutes_light_sleep"], 120)
        self.assertEqual(s["phase_max_minutes_deep_sleep"], 180)
        self.assertEqual(s["phase_max_minutes_rem"], 60)
        self.assertEqual(s["phase_max_minutes_hibernate"], 120)

    def test_update_roundtrip_persists(self):
        import tempfile
        import os
        from neurova.core.sleep_settings_store import SleepSettingsStore

        with tempfile.TemporaryDirectory() as d:
            store = SleepSettingsStore("default", base_dir=d)
            sc, mm = _make_consolidation(settings_store=store)
            sc.update_settings({"phase_max_minutes_light_sleep": 5})
            sc2, _ = _make_consolidation(settings_store=store)
            self.assertEqual(sc2.get_settings()["phase_max_minutes_light_sleep"], 5)


class DwellProgressionTest(unittest.TestCase):
    """问题4-5：tracker 消费 dwell —— 超时强制推进；休眠超时→active+wake 记账"""

    def _tracker_with(self):
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(sc)
        tracker.set_memory_manager(mm)
        tracker._monitor_running = False  # 测试不起线程
        tracker.register_callback("phase_changed", tracker._on_phase_changed)
        return sc, tracker

    def test_dwell_timeout_forces_next_phase(self):
        sc, tracker = self._tracker_with()
        sc.update_settings({"phase_max_minutes_light_sleep": 1})
        tracker._current_phase = "light_sleep"
        tracker._phase_start_time = time.time() - 120
        tracker._temperature_provider = lambda: 99.0  # 温度远未达阈值
        result = tracker.check_and_update_phase()
        self.assertEqual(result, "rem", "阶段停留超时应按链序推进：浅睡→REM")

    def test_hibernate_dwell_timeout_wakes(self):
        sc, tracker = self._tracker_with()
        sc.update_settings({"phase_max_minutes_hibernate": 1})
        tracker._current_phase = "hibernate"
        tracker._phase_start_time = time.time() - 120
        tracker._temperature_provider = lambda: 99.0
        result = tracker.check_and_update_phase()
        self.assertEqual(result, "active", "最深阶段超时=整觉完成→回 active")
        self.assertEqual(tracker._current_phase, "active")
        self.assertIsNotNone(sc.get_last_wake_time(), "回 active 必须 wake 记账")

    def test_activity_return_to_active_wakes_session(self):
        """有活动回到 active：手动睡眠会话同步 wake"""
        sc, tracker = self._tracker_with()
        sc.start_sleep(duration_minutes=60)
        self.assertTrue(sc.is_sleeping())
        tracker._current_phase = "deep_sleep"
        tracker.record_activity()
        self.assertFalse(sc.is_sleeping(), "活动唤醒应结束睡眠会话")


class FullCycleCooldownTest(unittest.TestCase):
    """24h 完整周期冷却：跑完一遍 浅睡→REM→深睡→休眠 后，24h 内不再自动入睡。

    不完整（从未到达休眠）= 无冷却，随时可进 —— 避免反复深睡。
    """

    def _ready_tracker(self):
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(sc)
        tracker.set_memory_manager(mm)
        tracker._monitor_running = False
        tracker.register_callback("phase_changed", tracker._on_phase_changed)
        # time 模式 + 空闲门放开：active→首阶段本应可推进，用于验证冷却是否拦截
        # （idle_threshold 0 会回退内置，须设正分钟数；空闲拉满远超 1 分钟）
        sc.update_settings({"sleep_mode": "time", "sleep_threshold_minutes": 0,
                            "idle_threshold_light_sleep": 1})
        tracker._last_activity_time = time.time() - 9999
        tracker._current_phase = "active"
        return sc, tracker

    def test_entering_hibernate_marks_cycle_completed(self):
        sc, tracker = self._ready_tracker()
        self.assertIsNone(sc.get_sleep_cycle_completed_at())
        tracker._transition_to_phase("hibernate")
        self.assertIsNotNone(sc.get_sleep_cycle_completed_at())

    def test_completed_cycle_within_24h_blocks_auto_sleep(self):
        sc, tracker = self._ready_tracker()
        sc.mark_sleep_cycle_completed()  # 刚完成
        result = tracker.check_and_update_phase()
        self.assertIsNone(result, "完整周期 24h 内应拦截自动入睡")

    def test_completed_cycle_after_24h_allows_auto_sleep(self):
        sc, tracker = self._ready_tracker()
        sc.mark_sleep_cycle_completed(at=time.time() - 25 * 3600)  # 25h 前完成
        result = tracker.check_and_update_phase()
        self.assertIsNotNone(result, "超过 24h 应允许再次自动入睡")
        self.assertEqual(result, "light_sleep")

    def test_incomplete_cycle_never_blocks(self):
        sc, tracker = self._ready_tracker()
        # 走到深睡但未达休眠 = 不完整，被活动打断也不记冷却
        tracker._transition_to_phase("rem")
        tracker._transition_to_phase("deep_sleep")
        tracker.record_activity()  # 唤醒，未达 hibernate（重置空闲时钟）
        self.assertIsNone(sc.get_sleep_cycle_completed_at())
        tracker._last_activity_time = time.time() - 9999  # 再满足空闲门
        self.assertIsNotNone(tracker.check_and_update_phase())

    def test_cooldown_persists_across_restart(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sleep_logs.json")
            sc, mm = _make_consolidation(logs_store_path=path)
            sc.mark_sleep_cycle_completed()
            sc2, _ = _make_consolidation(logs_store_path=path)
            self.assertIsNotNone(sc2.get_sleep_cycle_completed_at())


class FullChainEndToEndTest(unittest.TestCase):
    """全链闭环：time 模式下逐阶段 dwell 超时推进 浅睡→REM→深睡→休眠，
    进入休眠打点完整周期→回 active→24h 冷却拦截再次入睡。"""

    def _tracker(self):
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        tracker.set_sleep_consolidation(sc)
        tracker.set_memory_manager(mm)
        tracker._monitor_running = False
        tracker.register_callback("phase_changed", tracker._on_phase_changed)
        # 阶段时长设 1 分钟，便于用 _phase_start_time 手动触发推进
        sc.update_settings({
            "sleep_mode": "time", "sleep_threshold_minutes": 0,
            "idle_threshold_light_sleep": 1,
            "phase_max_minutes_light_sleep": 1, "phase_max_minutes_rem": 1,
            "phase_max_minutes_deep_sleep": 1, "phase_max_minutes_hibernate": 1,
        })
        tracker._last_activity_time = time.time() - 9999
        return sc, tracker

    def test_full_chain_then_cooldown(self):
        sc, tracker = self._tracker()

        # active → 浅睡（get_next_phase: 空闲达阈值）
        self.assertEqual(tracker.check_and_update_phase(), "light_sleep")
        # 逐级 dwell 超时沿链推进
        for expect in ("rem", "deep_sleep", "hibernate"):
            tracker._phase_start_time = time.time() - 120
            self.assertEqual(tracker.check_and_update_phase(), expect)
        # 进入休眠 = 完整周期打点
        self.assertIsNotNone(sc.get_sleep_cycle_completed_at())
        # 休眠 dwell 超时 → 回 active（整觉完成）
        tracker._phase_start_time = time.time() - 120
        self.assertEqual(tracker.check_and_update_phase(), "active")
        # 回 active 后处于 24h 冷却：即便空闲/阈值都满足也不再自动入睡
        tracker._last_activity_time = time.time() - 9999
        self.assertIsNone(tracker.check_and_update_phase())
        # 冷却期满（25h 前的完成点）→ 允许再次入睡
        sc.mark_sleep_cycle_completed(at=time.time() - 25 * 3600)
        self.assertEqual(tracker.check_and_update_phase(), "light_sleep")


class AutoWakeDeadlineTest(unittest.TestCase):

    def test_start_sleep_sets_deadline_and_check_wakes_at_time(self):
        sc, mm = _make_consolidation()
        now = time.time()
        sc.start_sleep(duration_minutes=1)
        self.assertTrue(sc.is_sleeping())
        self.assertIsNotNone(sc.get_next_wake())
        self.assertAlmostEqual(sc.get_next_wake(), now + 60, delta=5)
        # 未到点不醒
        self.assertFalse(sc.check_auto_wake(now + 10))
        self.assertTrue(sc.is_sleeping())
        # 到点自动醒 + 清 deadline
        self.assertTrue(sc.check_auto_wake(now + 61))
        self.assertFalse(sc.is_sleeping())
        self.assertIsNone(sc.get_next_wake())
        self.assertIsNotNone(sc.get_last_wake_time())

    def test_deadline_from_settings_when_duration_omitted(self):
        sc, mm = _make_consolidation()
        sc.update_settings({"sleep_duration_minutes": 90})
        now = time.time()
        sc.start_sleep()
        self.assertAlmostEqual(sc.get_next_wake(), now + 90 * 60, delta=5)

    def test_wake_clears_deadline(self):
        sc, mm = _make_consolidation()
        sc.start_sleep(duration_minutes=1)
        sc.wake()
        self.assertIsNone(sc.get_next_wake())


class StatusContractTest(unittest.TestCase):
    """问题6：/status sleep_phase 统一源 + next_wake"""

    def setUp(self):
        from neurova.api.endpoints import sleep as sleep_api

        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        self.client = TestClient(app)
        self.sleep_api = sleep_api

    def _agent(self, sc, tracker=None):
        class Stub:
            pass

        a = Stub()
        a.sleep_consolidation = sc
        if tracker is not None:
            a.idle_tracker = tracker
        return a

    def test_status_reports_tracker_phase(self):
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        tracker._current_phase = "rem"
        tracker._phase_start_time = time.time()
        agent = self._agent(sc, tracker)
        with patch.object(self.sleep_api, "_get_agent", return_value=agent):
            resp = self.client.get("/api/v1/sleep/default/status", headers=_AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["sleep_phase"], "rem", "状态页阶段应反映真实推进（统一源）")
        self.assertIn("next_wake", body)

    def test_status_active_maps_awake(self):
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        agent = self._agent(sc, tracker)
        with patch.object(self.sleep_api, "_get_agent", return_value=agent):
            resp = self.client.get("/api/v1/sleep/default/status", headers=_AUTH)
        self.assertEqual(resp.json()["sleep_phase"], "awake")
        self.assertIsNone(resp.json()["next_wake"])

    def test_status_manual_session_phase_and_deadline(self):
        sc, mm = _make_consolidation()
        sc.start_sleep(duration_minutes=2)
        agent = self._agent(sc)
        with patch.object(self.sleep_api, "_get_agent", return_value=agent):
            resp = self.client.get("/api/v1/sleep/default/status", headers=_AUTH)
        body = resp.json()
        self.assertEqual(body["sleep_phase"], "deep_sleep")
        self.assertIsNotNone(body["next_wake"])


class SettingsEndpointFieldsTest(unittest.TestCase):
    """设置端点契约：PUT/GET 往返 4 个新字段"""

    def setUp(self):
        from neurova.api.endpoints import sleep as sleep_api

        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        self.client = TestClient(app)
        self.sleep_api = sleep_api

    def test_settings_roundtrip_new_fields(self):
        sc, mm = _make_consolidation()

        class Stub:
            sleep_consolidation = sc

        with patch.object(self.sleep_api, "_get_agent", return_value=Stub()):
            resp = self.client.put(
                "/api/v1/sleep/default/settings",
                json={"phase_max_minutes_rem": 45},
                headers=_AUTH,
            )
            self.assertEqual(resp.status_code, 200)
            got = self.client.get("/api/v1/sleep/default/settings", headers=_AUTH).json()
        self.assertEqual(got["phase_max_minutes_rem"], 45)

    def test_resolve_forwards_apply_to_store(self):
        """端点契约：apply_to_store 必须透传给引擎（此前 body 未定义该字段被静默丢弃）"""
        sc, mm = _make_consolidation()

        class Stub:
            sleep_consolidation = sc

        with patch.object(sc, "resolve_conflict", return_value={"id": "cr_1"}) as mock_resolve:
            with patch.object(self.sleep_api, "_get_agent", return_value=Stub()):
                resp = self.client.post(
                    "/api/v1/sleep/default/conflicts/cr_1/resolve",
                    json={"resolution": "merge", "apply_to_store": True},
                    headers=_AUTH,
                )
        self.assertEqual(resp.status_code, 200)
        mock_resolve.assert_called_once_with("cr_1", "merge", True)

    def test_wake_resets_tracker_phase(self):
        """闭环断点修复：状态页按派生 isInSleep 在自动睡眠期也显示唤醒按钮；
        POST /wake 若只结束手动会话、不回落 tracker 阶段，按钮就是哑的。
        """
        sc, mm = _make_consolidation()
        tracker = IdleTimeTracker()
        tracker._current_phase = "deep_sleep"

        class Stub:
            sleep_consolidation = sc
            idle_tracker = tracker

        with patch.object(self.sleep_api, "_get_agent", return_value=Stub()):
            resp = self.client.post("/api/v1/sleep/default/wake", headers=_AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(tracker.get_current_phase(), "active", "唤醒必须回落阶段推进链")

    def test_full_loop_settings_to_sleep_session(self):
        """整觉闭环：手动会话→监控判时→到点醒→四页签数据落盘可读→状态归零"""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sleep_logs.json")
            sc, mm = _make_consolidation(logs_store_path=path)
            tracker = IdleTimeTracker()
            tracker.set_sleep_consolidation(sc)
            tracker.set_memory_manager(mm)
            tracker.register_callback("phase_changed", tracker._on_phase_changed)

            sc.start_sleep(duration_minutes=1)
            self.assertTrue(sc.is_sleeping())
            # 监控循环一轮：未到点（check_auto_wake(now) 无参数用真实时间，
            # 用引擎级判时函数注入时刻验证未到/到点两态）
            self.assertFalse(sc.check_auto_wake(time.time() + 10))
            self.assertTrue(sc.check_auto_wake(time.time() + 61))
            self.assertFalse(sc.is_sleeping())

            # 重启读取：落盘链路闭合
            sc2, _ = _make_consolidation(logs_store_path=path)
            self.assertGreaterEqual(len(sc2.get_dream_logs(50)), 1)
            # 状态字段归零一致
            self.assertEqual(sc.get_sleep_phase(), "awake")
            self.assertIsNone(sc.get_next_wake())
            self.assertIsNotNone(sc.get_last_wake_time())


if __name__ == "__main__":
    unittest.main()
