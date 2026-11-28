# -*- coding: utf-8 -*-
"""命中回温统一到 D5-R2 比例式 + 反馈轻信号 ±0.5（拍板 2026-11-28，以 58a652ee6 为准）。

58a652ee6（D5-R2）确立「有效命中回温 = T += (100−T)×k，k 默认 0.25」为唯一权威语义。
本文件钉住三条残余收敛：
1. Memory.touch() 不再平 +10，委托 apply_recall_gain（manager.search /
   update_memory_temperature 等调用方随之统一）；
2. CSE UnifiedMemoryNode.touch() 同语义——热层缓冲节点与 DB 行不再分裂；
3. like/dislike 反馈改为轻信号 ±0.5（不再走 touch 的命中回温，也不再用 −15）。
"""
import pytest
from types import SimpleNamespace

from neurova.cognitive_layers.memory_layer.models import Memory
from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    UnifiedMemoryNode,
)
from neurova.cognitive_layers.memory_layer.settings_config import (
    get_memory_settings,
    MemorySettingsConfig,
)
from neurova.mem_core import MemCore


@pytest.fixture
def settings(tmp_path):
    """隔离的配置单例：指向 tmp 目录，测后重置（与 test_settings_wiring 同法）"""
    MemorySettingsConfig.reset_instance()
    cfg = get_memory_settings(str(tmp_path))
    yield cfg
    MemorySettingsConfig.reset_instance()


class TestTouchIsProportional:
    """touch() 单源比例回温（k=0.25：88° 恰 +3.0，60° 出生带 +10.0）。"""

    def test_memory_touch_hot_band_three_degrees(self):
        m = Memory(id="x", temperature=88.0)
        m.touch()
        assert m.temperature == pytest.approx(91.0)  # 88 + 12×0.25

    def test_memory_touch_birth_band_ten_degrees(self):
        m = Memory(id="x", temperature=60.0)
        m.touch()
        assert m.temperature == pytest.approx(70.0)  # 60 + 40×0.25

    def test_memory_touch_counts_access_and_stamps_time(self):
        m = Memory(id="x", temperature=88.0)
        before = m.access_count
        m.touch()
        assert m.access_count == before + 1
        assert m.last_accessed_at is not None

    def test_memory_touch_honors_configured_max(self, settings):
        settings.update({"temperature.max": 80.0})
        m = Memory(id="x", temperature=75.0)
        m.touch()
        assert m.temperature == pytest.approx(80.0)  # 75+6.25=81.25 → clamp 80

    def test_node_touch_same_semantics_as_db_rows(self):
        n = UnifiedMemoryNode(id="n1", content="c", temperature=88.0)
        n.touch()
        assert n.temperature == pytest.approx(91.0)


class TestFeedbackLightSignal:
    """like +0.5 / dislike −0.5：轻信号不挤占命中回温幅度，clamp [0, 100]。"""

    @staticmethod
    def _core(mems):
        class _StubManager:
            def __init__(self, rows):
                self.rows = rows
                self.updates = []
                self.touch_calls = []

            def get_all_memories(self):
                return self.rows

            def update_memory(self, memory_id, temperature=None, **kw):
                self.updates.append((memory_id, temperature))
                return True

            def update_memory_temperature(self, memory_id, interaction_type="recall"):
                self.touch_calls.append(memory_id)
                return True

            def remember(self, *a, **kw):
                # MemCore.memory_manager 赋值会经 installMemoryAdmission 包装，
                # 准入闸需要 remember 属性存在（本测试不触发写入路径）
                return {"success": True}

        core = MemCore.__new__(MemCore)
        # memory_manager 是 property：setter 会经 installMemoryAdmission/Discipline
        # 包装并回写 _agent.memory_manager，故先给一个可挂载的 _agent
        core._agent = SimpleNamespace(memory_manager=None)
        core.memory_manager = _StubManager(mems)
        return core, core.memory_manager

    @staticmethod
    def _round_rows(temperature=88.0):
        return [
            {"id": "m1", "content": "用户: 帮我整理周报",
             "metadata": {"session_id": "s1", "sender_type": "user"},
             "temperature": temperature, "created_at": "2026-11-28T00:00:00"},
            {"id": "m2", "content": "助手: 已按上周格式整理",
             "metadata": {"session_id": "s1", "sender_type": "agent"},
             "temperature": temperature, "created_at": "2026-11-28T00:00:00"},
        ]

    def test_like_raises_half_degree(self):
        core, mgr = self._core(self._round_rows(88.0))
        affected = core.apply_feedback_to_memories(
            session_id="s1", user_input="帮我整理周报",
            agent_response="已按上周格式整理", feedback="like")
        assert affected == 2
        assert sorted(mgr.updates) == [("m1", 88.5), ("m2", 88.5)]
        assert mgr.touch_calls == []  # 反馈不走命中回温咽喉

    def test_dislike_lowers_half_degree(self):
        core, mgr = self._core(self._round_rows(88.0))
        core.apply_feedback_to_memories(
            session_id="s1", user_input="帮我整理周报",
            agent_response="已按上周格式整理", feedback="dislike")
        assert sorted(mgr.updates) == [("m1", 87.5), ("m2", 87.5)]

    def test_like_clamps_at_hundred(self):
        core, mgr = self._core(self._round_rows(99.9))
        core.apply_feedback_to_memories(
            session_id="s1", user_input="帮我整理周报",
            agent_response="已按上周格式整理", feedback="like")
        assert sorted(mgr.updates) == [("m1", 100.0), ("m2", 100.0)]

    def test_dislike_clamps_at_zero(self):
        core, mgr = self._core(self._round_rows(0.2))
        core.apply_feedback_to_memories(
            session_id="s1", user_input="帮我整理周报",
            agent_response="已按上周格式整理", feedback="dislike")
        assert sorted(mgr.updates) == [("m1", 0.0), ("m2", 0.0)]


class TestLegacyRewarmRetired:
    """58a652ee6 收口后旧回温/衰减双实现退役（缺席守卫，防复活）。

    - TemperatureEngine.on_access：旧「importance×饱和×连击」公式，零生产调用
      的测试专用死码，与比例式权威语义冲突——随测试改投 apply_recall_gain 退役；
    - UnifiedMemoryNode.decay：旧线性 temp -= rate*hours（Bug M-5 同族形态），
      零生产调用——真衰减唯一出口是 models.Memory.decay → on_decay 贝叶斯曲线。
    """

    def test_on_access_formula_retired(self):
        from neurova.cognitive_layers.memory_layer import temperature as temp_mod

        assert not hasattr(temp_mod.TemperatureEngine, "on_access")
        assert not hasattr(temp_mod.TemperatureEngine, "_on_access_impl")

    def test_cse_node_linear_decay_retired(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            UnifiedMemoryNode,
        )

        assert not hasattr(UnifiedMemoryNode, "decay")
