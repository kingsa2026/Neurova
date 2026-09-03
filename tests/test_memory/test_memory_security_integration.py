"""
记忆安全防护测试 - 对齐真实 MemoryStorage / MemorySecurityGuard 契约

存储层是中性存储（不做安全拦截）；安全策略由 MemorySecurityGuard 承担，
真实集成面在 CognitiveSecuritySystem（_memory_guard）。
"""
import tempfile
import shutil

import pytest

from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
from neurova.security.cognitive_security import (
    MemorySecurityGuard,
    CognitiveSecuritySystem,
    SafetyLevel,
)


class TestMemoryStorageContract:
    """MemoryStorage 真实契约：CRUD + 三层隔离 + 中性存储"""

    @pytest.fixture
    def tmp_dir(self):
        path = tempfile.mkdtemp(suffix="_memory_security")
        yield path
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    def storage(self, tmp_dir):
        return MemoryStorage(storage_dir=tmp_dir)

    def test_save_returns_id_and_roundtrip(self, storage):
        mid = storage.save("这是一条正常的记忆内容", memory_type="general")
        assert isinstance(mid, str) and mid.startswith("mem_")

        retrieved = storage.get(mid)
        assert retrieved is not None
        assert retrieved["content"] == "这是一条正常的记忆内容"
        assert retrieved["memory_type"] == "general"
        assert retrieved["id"] == mid

    def test_save_persists_isolation_context(self, storage):
        ctx = IsolationContext(
            agent_id="yi_ling",
            neuser_id="sys_1",
            user_id="user_1",
            shared=True,
            share_group_ids=("g1",),
        )
        mid = storage.save("隔离记忆", memory_type="conversation", isolation_context=ctx)

        rec = storage.get(mid)
        assert rec["agent_id"] == "yi_ling"
        assert rec["neuser_id"] == "sys_1"
        assert rec["user_id"] == "user_1"
        assert rec["shared"] is True
        assert rec["share_group_ids"] == ["g1"]

    def test_update_and_delete(self, storage):
        mid = storage.save("可更新记忆", memory_type="general")
        assert storage.update_memory(mid, tags=["a", "b"], importance=0.5) is True

        rec = storage.get(mid)
        assert rec["tags"] == ["a", "b"]
        assert rec["importance"] == 0.5

        assert storage.delete(mid) is True
        assert storage.delete(mid) is False
        assert storage.get(mid) is None

    def test_storage_is_neutral_for_sensitive_content(self, storage):
        """存储层不拦截敏感内容——策略在 MemorySecurityGuard，不在 storage 内部"""
        mid = storage.save("密码是 password123", memory_type="conversation")
        assert storage.get(mid) is not None
        assert storage.get(mid)["content"] == "密码是 password123"

    def test_get_recent_memories_and_count(self, storage):
        for i in range(3):
            storage.save(f"记忆 {i}", memory_type="general")

        assert storage.count() == 3
        recent = storage.get_recent_memories(limit=2)
        assert len(recent) == 2
        # 按 created_at DESC
        assert recent[0]["content"] == "记忆 2"

    def test_get_recent_memories_filters_by_agent(self, storage):
        storage.save("A 的", memory_type="general", isolation_context=IsolationContext(agent_id="a"))
        storage.save("B 的", memory_type="general", isolation_context=IsolationContext(agent_id="b"))

        filtered = storage.get_recent_memories(agent_id="a")
        assert len(filtered) == 1
        assert filtered[0]["content"] == "A 的"


class TestMemorySecurityGuardUnit:
    """MemorySecurityGuard 真实 API：should_remember / sanitize_memory / check_memory_safety"""

    def test_initialization(self):
        guard = MemorySecurityGuard()
        assert hasattr(guard, "_sensitive_detector")
        assert len(guard.SENSITIVE_MEMORY_TYPES) > 0

    def test_should_remember_blocks_high_severity_patterns(self):
        guard = MemorySecurityGuard()
        # api_key 为 CRITICAL
        assert guard.should_remember("API_KEY=sk_test_1234567890") is False
        # password / token 为 HIGH
        assert guard.should_remember("password=123456") is False
        assert guard.should_remember("token=abc123") is False
        # 正常内容
        assert guard.should_remember("今天天气很好") is True
        assert guard.should_remember("这是正常内容") is True

    def test_should_remember_blocks_sensitive_memory_type(self):
        guard = MemorySecurityGuard()
        # 记忆类型本身属敏感类型时整体拒绝（与内容无关）
        assert guard.should_remember("任意内容", memory_type="password") is False
        assert guard.should_remember("任意内容", memory_type="api_key") is False

    def test_should_remember_only_triggers_on_key_value_form(self):
        """真实检测器要求 key= 或 key: 形式：裸的 password123 单词不构成敏感模式"""
        guard = MemorySecurityGuard()
        assert guard.should_remember("密码是 password123") is True
        assert guard.should_remember("这是我的 private key: xk123456") is True

    def test_sanitize_memory_masks_credentials(self):
        guard = MemorySecurityGuard()
        assert guard.sanitize_memory("API_KEY=sk_test_1234567890") == "API_KEY=***"
        sanitized = guard.sanitize_memory("password=123456")
        assert "123456" not in sanitized
        assert sanitized == "password=***"
        # 正常内容原样返回
        assert guard.sanitize_memory("这是正常内容") == "这是正常内容"
        assert guard.sanitize_memory("") == ""

    def test_check_memory_safety_result_shape(self):
        guard = MemorySecurityGuard()
        result = guard.check_memory_safety("API_KEY=sk_abc")
        assert result.is_safe is False
        assert result.safety_level == SafetyLevel.CRITICAL
        assert len(result.findings) > 0
        assert result.sanitized_text == "API_KEY=***"
        assert result.check_duration_ms >= 0

    def test_check_memory_safety_benign_content(self):
        guard = MemorySecurityGuard()
        result = guard.check_memory_safety("这是正常内容")
        assert result.is_safe is True
        assert result.safety_level == SafetyLevel.LOW
        assert result.findings == []
        assert result.sanitized_text is None

    def test_cognitive_security_system_owns_guard(self):
        """守卫的真实集成面：CognitiveSecuritySystem 持有 MemorySecurityGuard 实例"""
        system = CognitiveSecuritySystem()
        assert isinstance(system._memory_guard, MemorySecurityGuard)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
