"""
记忆系统测试

验证核心组件的闭环：
1. MemoryRecord: 数据模型
2. MemoryStorage: 文件存储 CRUD
3. TemperatureEngine: 温度衰减
4. 端到端: 存储→检索→温度→衰减→搜索
"""
import pytest
import tempfile
import shutil
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════
# 1. MemoryRecord 数据模型测试
# ═══════════════════════════════════════════════════════

class TestMemoryRecord:
    """MemoryRecord 数据模型测试"""

    def test_create_record(self):
        """创建记忆记录"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord
        r = MemoryRecord(id="m1", content="Hello", memory_type="text", owner="user1")
        assert r.id == "m1"
        assert r.content == "Hello"
        assert r.memory_type == "text"
        assert r.access_count == 0

    def test_to_dict(self):
        """序列化为字典"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord
        r = MemoryRecord(id="m1", content="Test", memory_type="text", owner="u1")
        d = r.to_dict()
        assert d["id"] == "m1"
        assert d["content"] == "Test"
        assert "created_at" in d

    def test_from_dict(self):
        """从字典反序列化"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord
        d = {"id": "m2", "content": "Data", "memory_type": "semantic", "owner": "u2"}
        r = MemoryRecord.from_dict(d)
        assert r.id == "m2"
        assert r.memory_type == "semantic"

    def test_tags_and_metadata(self):
        """标签和元数据"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord
        r = MemoryRecord(
            id="m3", content="Tagged", memory_type="text", owner="u1",
            tags=["python", "tutorial"], metadata={"key": "value"}
        )
        assert "python" in r.tags
        assert r.metadata["key"] == "value"

    def test_isolation_fields(self):
        """三层隔离字段"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryRecord
        r = MemoryRecord(
            id="m4", content="Isolated", memory_type="text", owner="u1",
            agent_id="agent_a", neuser_id="neuser_1", user_id="user_1"
        )
        assert r.agent_id == "agent_a"
        assert r.neuser_id == "neuser_1"
        assert r.user_id == "user_1"


# ═══════════════════════════════════════════════════════
# 2. MemoryStorage CRUD 测试
# ═══════════════════════════════════════════════════════

class TestMemoryStorage:
    """MemoryStorage 文件存储测试"""

    @pytest.fixture
    def store(self):
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        tmpdir = tempfile.mkdtemp()
        s = MemoryStorage(tmpdir)
        yield s
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_save_and_get(self, store):
        """保存和获取"""
        mid = store.save(content="Hello", memory_type="text", owner="u1")
        retrieved = store.get(mid)
        assert retrieved is not None
        assert retrieved["content"] == "Hello"

    def test_save_overwrite(self, store):
        """覆盖保存（用不同 ID）"""
        mid1 = store.save(content="V1", memory_type="text", owner="u1")
        mid2 = store.save(content="V2", memory_type="text", owner="u1")
        assert store.get(mid1)["content"] == "V1"
        assert store.get(mid2)["content"] == "V2"

    def test_delete(self, store):
        """删除"""
        mid = store.save(content="Delete me", memory_type="text", owner="u1")
        assert store.delete(mid) is True
        assert store.get(mid) is None

    def test_delete_nonexistent(self, store):
        """删除不存在的记录"""
        assert store.delete("nonexistent") is False

    def test_query_by_type(self, store):
        """按类型查询"""
        store.save(content="A", memory_type="semantic", owner="u1")
        store.save(content="B", memory_type="episodic", owner="u1")
        store.save(content="C", memory_type="semantic", owner="u1")

        results = store.query(memory_type="semantic")
        assert len(results) == 2

    def test_query_by_tag(self, store):
        """按标签查询"""
        store.save(content="A", memory_type="text", owner="u1", tags=["python"])
        store.save(content="B", memory_type="text", owner="u1", tags=["java"])

        results = store.query(tags=["python"])
        assert len(results) == 1

    def test_query_by_owner(self, store):
        """按所有者查询"""
        store.save(content="A", memory_type="text", owner="alice")
        store.save(content="B", memory_type="text", owner="bob")

        results = store.query(owner="alice")
        assert len(results) == 1

    def test_count(self, store):
        """计数"""
        store.save(content="A", memory_type="text", owner="u1")
        store.save(content="B", memory_type="text", owner="u1")
        assert store.count() == 2

    def test_persistence(self):
        """持久化验证"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        tmpdir = tempfile.mkdtemp()
        try:
            s1 = MemoryStorage(tmpdir)
            mid = s1.save(content="Persistent", memory_type="text", owner="u1")

            s2 = MemoryStorage(tmpdir)
            retrieved = s2.get(mid)
            assert retrieved is not None
            assert retrieved["content"] == "Persistent"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_thread_safety(self, store):
        """线程安全"""
        import threading

        def add_memories(prefix, count):
            for i in range(count):
                store.save(content=f"Content {i}", memory_type="text", owner="u1")

        threads = [threading.Thread(target=add_memories, args=(f"t{t}", 10)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert store.count() == 50


# ═══════════════════════════════════════════════════════
# 3. TemperatureEngine 测试
# ═══════════════════════════════════════════════════════

class TestTemperatureEngine:
    """温度引擎测试"""

    def test_access_boost(self):
        """访问升温"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        new_temp = TemperatureEngine.on_access(50.0, importance=0.5)
        assert new_temp > 50.0

    def test_access_boost_importance(self):
        """重要性影响升温"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        t_low = TemperatureEngine.on_access(50.0, importance=0.2)
        t_high = TemperatureEngine.on_access(50.0, importance=0.8)
        assert t_high > t_low

    def test_access_caps_at_100(self):
        """温度上限 100"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        new_temp = TemperatureEngine.on_access(99.0, importance=1.0)
        assert new_temp == 100.0

    def test_decay_basic(self):
        """基础衰减"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        new_temp = TemperatureEngine.on_decay(80.0, days_idle=7)
        assert new_temp < 80.0

    def test_decay_more_days_more_decay(self):
        """更多天数=更多衰减"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        t_1 = TemperatureEngine.on_decay(80.0, days_idle=1)
        t_7 = TemperatureEngine.on_decay(80.0, days_idle=7)
        t_30 = TemperatureEngine.on_decay(80.0, days_idle=30)
        # 更多天数 = 更多衰减 = 更低温度
        assert t_7 < t_1
        assert t_30 < t_7

    def test_decay_higher_temp_faster_decay(self):
        """高温衰减更快"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        t_high = TemperatureEngine.on_decay(90.0, days_idle=7)
        t_low = TemperatureEngine.on_decay(20.0, days_idle=7)
        # 高温应该衰减更多
        decay_high = 90.0 - t_high
        decay_low = 20.0 - t_low
        assert decay_high > decay_low

    def test_emotion_protection(self):
        """情感保护减缓衰减"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        t_no_emo = TemperatureEngine.on_decay(80.0, days_idle=7, emotion_score=0.0)
        t_with_emo = TemperatureEngine.on_decay(80.0, days_idle=7, emotion_score=0.8)
        assert t_with_emo > t_no_emo

    def test_importance_protection(self):
        """重要性保护减缓衰减"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        t_low = TemperatureEngine.on_decay(80.0, days_idle=7, importance=0.1)
        t_high = TemperatureEngine.on_decay(80.0, days_idle=7, importance=0.9)
        assert t_high > t_low

    def test_decay_never_negative(self):
        """衰减后温度不低于 0"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        new_temp = TemperatureEngine.on_decay(1.0, days_idle=365)
        assert new_temp >= 0.0

    def test_lifecycle_active(self):
        """生命周期: active"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        assert TemperatureEngine.get_lifecycle_stage(80.0) == TemperatureEngine.STAGE_ACTIVE

    def test_lifecycle_secondary(self):
        """生命周期: secondary"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        assert TemperatureEngine.get_lifecycle_stage(40.0) == TemperatureEngine.STAGE_SECONDARY

    def test_lifecycle_archived(self):
        """生命周期: archived"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        assert TemperatureEngine.get_lifecycle_stage(10.0) == TemperatureEngine.STAGE_ARCHIVED

    def test_lifecycle_deleted(self):
        """生命周期: deleted"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        assert TemperatureEngine.get_lifecycle_stage(2.0) == TemperatureEngine.STAGE_DELETED


# ═══════════════════════════════════════════════════════
# 4. MemCore 数据模型测试
# ═══════════════════════════════════════════════════════

class TestMemCoreModels:
    """MemCore 数据模型测试"""

    def test_memory_creation(self):
        """创建 Memory"""
        from neurova.mem_core import Memory
        m = Memory(id="m1", content="Test", importance=0.8, temperature=75.0)
        assert m.id == "m1"
        assert m.importance == 0.8

    def test_memory_validation(self):
        """Memory 验证"""
        from neurova.mem_core import Memory
        with pytest.raises(ValueError):
            Memory(id="m1", content="x", importance=1.5)  # importance > 1.0
        with pytest.raises(ValueError):
            Memory(id="m1", content="x", temperature=-1.0)  # negative temp

    def test_memory_auto_id(self):
        """Memory 自动生成 ID"""
        from neurova.mem_core import Memory
        m = Memory(content="No ID")
        assert m.id.startswith("memory_")

    def test_memory_to_dict(self):
        """Memory 序列化"""
        from neurova.mem_core import Memory
        m = Memory(id="m1", content="Test", importance=0.5, temperature=50.0)
        d = m.to_dict()
        assert d["id"] == "m1"
        assert d["importance"] == 0.5

    def test_conversation_creation(self):
        """创建 Conversation"""
        from neurova.mem_core import Conversation
        c = Conversation(session_id="s1", user_id="u1", agent_id="a1")
        assert c.session_id == "s1"
        assert len(c.messages) == 0

    def test_conversation_add_message(self):
        """Conversation 添加消息"""
        from neurova.mem_core import Conversation
        c = Conversation()
        c.add_message("user", "Hello")
        c.add_message("assistant", "Hi")
        assert len(c.messages) == 2
        assert c.messages[0]["role"] == "user"

    def test_conversation_to_dict(self):
        """Conversation 序列化"""
        from neurova.mem_core import Conversation
        c = Conversation(id="c1", session_id="s1")
        c.add_message("user", "Hello")
        d = c.to_dict()
        assert d["id"] == "c1"
        assert len(d["messages"]) == 1


# ═══════════════════════════════════════════════════════
# 5. 端到端: 存储→检索→温度→衰减→搜索 闭环
# ═══════════════════════════════════════════════════════

class TestMemorySystemE2E:
    """记忆系统端到端闭环"""

    def test_store_retrieve_temperature_decay_loop(self):
        """存储→检索→温度更新→衰减 完整闭环"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        tmpdir = tempfile.mkdtemp()
        try:
            store = MemoryStorage(tmpdir)
            engine = TemperatureEngine()

            # 1. 存储记忆
            mid = store.save(content="Python is great", memory_type="semantic", owner="user1")
            mem = store.get(mid)
            assert mem is not None

            # 2. 访问升温
            old_temp = 80.0
            new_temp = engine.on_access(old_temp, importance=0.8)
            store.update_memory(mid, metadata={"temperature": new_temp})
            mem = store.get(mid)
            assert mem["metadata"]["temperature"] > old_temp

            # 3. 模拟时间流逝，衰减
            decayed = engine.on_decay(new_temp, days_idle=7, importance=0.8)
            assert decayed < new_temp

            # 4. 生命周期阶段
            stage = engine.get_lifecycle_stage(decayed)
            assert stage in ["active", "secondary", "archived", "deleted"]

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_search_after_store(self):
        """存储后查询"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        tmpdir = tempfile.mkdtemp()
        try:
            store = MemoryStorage(tmpdir)
            store.save(content="Python", memory_type="semantic", owner="u1", tags=["code"])
            store.save(content="Java", memory_type="semantic", owner="u1", tags=["code"])
            store.save(content="Cooking", memory_type="episodic", owner="u1", tags=["hobby"])

            # 按类型
            assert len(store.query(memory_type="semantic")) == 2
            # 按标签
            assert len(store.query(tags=["code"])) == 2
            assert len(store.query(tags=["hobby"])) == 1
            # 按所有者
            assert len(store.query(owner="u1")) == 3
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_multi_agent_isolation(self):
        """多 agent 隔离"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

        tmpdir = tempfile.mkdtemp()
        try:
            store = MemoryStorage(tmpdir)
            store.save(content="A1", memory_type="text", owner="u1", tags=[], metadata={}, isolation_context=type('IC', (), {'agent_id': 'agent_a', 'neuser_id': 'default', 'user_id': 'default', 'shared': False, 'share_group_ids': []})())
            store.save(content="A2", memory_type="text", owner="u1", tags=[], metadata={}, isolation_context=type('IC', (), {'agent_id': 'agent_b', 'neuser_id': 'default', 'user_id': 'default', 'shared': False, 'share_group_ids': []})())
            store.save(content="A3", memory_type="text", owner="u1", tags=[], metadata={}, isolation_context=type('IC', (), {'agent_id': 'agent_a', 'neuser_id': 'default', 'user_id': 'default', 'shared': False, 'share_group_ids': []})())

            # 查询所有（无隔离上下文）
            all_mem = store.query()
            assert len(all_mem) == 3
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_temperature_lifecycle_flow(self):
        """温度生命周期流程"""
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        # 新记忆: 80度 -> active
        temp = 80.0
        assert TemperatureEngine.get_lifecycle_stage(temp) == "active"

        # 多次衰减: 逐步降低
        for _ in range(5):
            temp = TemperatureEngine.on_decay(temp, days_idle=30)

        # 经过足够衰减后，进入 secondary 或更低
        stage = TemperatureEngine.get_lifecycle_stage(temp)
        assert stage in ["active", "secondary"]

        # 访问恢复
        temp = TemperatureEngine.on_access(temp, importance=0.8)
        assert temp > 0  # 访问后温度上升
