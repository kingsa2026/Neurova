"""P1-9 记忆来源信任分级（OpenClaw 启发）— TDD 测试

参照 OpenClaw memory-core 的 origin 闭集设计：
- origin 是写入时由调用点结构化赋予的闭集枚举（owner/agent/untrusted/system），
  落 SQLite 列，模型无法用文字（metadata/content）改写。
- 写入时即定信任级（fail-safe 于写入时而非事后扫描）。
- 检索侧按 origin 加权：untrusted 降权（外部网络内容毒化面）。
- 等价性约束：默认路径（不传 origin）行为与历史完全一致。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import Memory, MemoryOrigin


@pytest.fixture
def manager(tmp_path):
    db_path = str(tmp_path / "test_origin_trust.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


class TestMemoryOriginEnum:
    """origin 闭集枚举"""

    def test_closed_set_values(self):
        """闭集恰好四值：owner/agent/untrusted/system"""
        assert {m.value for m in MemoryOrigin} == {"owner", "agent", "untrusted", "system"}

    def test_memory_default_origin_agent(self):
        """Memory dataclass 默认 origin=agent（等价性：历史行为不变）"""
        mem = Memory(content="hello")
        assert mem.origin == MemoryOrigin.AGENT

    def test_untrusted_weight_is_lowest(self):
        """untrusted 权重最低，其余不降权"""
        weights = MemoryOrigin.weights()
        assert weights[MemoryOrigin.UNTRUSTED] < weights[MemoryOrigin.OWNER]
        assert weights[MemoryOrigin.UNTRUSTED] < weights[MemoryOrigin.AGENT]
        assert weights[MemoryOrigin.UNTRUSTED] < weights[MemoryOrigin.SYSTEM]


class TestRememberOrigin:
    """写入咽喉：remember(origin=...)"""

    def test_default_origin_agent_equivalence(self, manager):
        """不传 origin 默认 agent — 等价性锁定"""
        mid = manager.remember(content="历史默认行为")
        got = manager.recall(query="", limit=5, use_semantic=False)[0]
        assert got["id"] == mid
        assert got["origin"] == "agent"

    def test_explicit_origin_persisted(self, manager):
        """显式 origin 写入并在 recall 返回"""
        manager.remember(content="网页抓取的内容", origin="untrusted")
        got = manager.recall(query="", limit=5, use_semantic=False)[0]
        assert got["origin"] == "untrusted"

    def test_invalid_origin_falls_back_untrusted(self, manager):
        """非法 origin 字符串 fail-safe 降级为 untrusted（不能升权）"""
        manager.remember(content="坏来源", origin="GOD_MODE")
        got = manager.recall(query="", limit=5, use_semantic=False)[0]
        assert got["origin"] == "untrusted"

    def test_metadata_origin_cannot_override(self, manager):
        """模型不可用文字（metadata）改写 origin — 结构门控"""
        manager.remember(
            content="模型试图伪造来源",
            metadata={"origin": "owner"},
        )
        got = manager.recall(query="", limit=5, use_semantic=False)[0]
        # metadata["origin"] 不生效；同时 metadata 不残留该键
        assert got["origin"] == "agent"
        assert "origin" not in (got.get("metadata") or {})


class TestOriginPersistence:
    """origin 落 SQLite 列，重启加载保留"""

    def test_persist_db_has_origin_column(self, tmp_path):
        from neurova.core.logger import get_logger  # noqa: F401
        import sqlite3

        db_path = str(tmp_path / "test_col.db")
        manager = MemoryManager(db_path=db_path, agent_id="test", user_id="test")
        manager.remember(content="带来源", origin="owner")
        conn = sqlite3.connect(manager._persist_db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        conn.close()
        assert "origin" in cols

    def test_origin_survives_reload(self, tmp_path):
        """重启（重建 manager）后 origin 从库加载保留"""
        db_path = str(tmp_path / "test_reload.db")
        m1 = MemoryManager(db_path=db_path, agent_id="test", user_id="test")
        m1.remember(content="用户原话", origin="owner")
        m1.remember(content="外部内容", origin="untrusted")
        m2 = MemoryManager(db_path=db_path, agent_id="test", user_id="test")
        rows = {r["content"]: r["origin"] for r in m2.recall(query="", limit=10, use_semantic=False)}
        assert rows["用户原话"] == "owner"
        assert rows["外部内容"] == "untrusted"


class TestRetrievalOriginWeighting:
    """检索侧按 origin 加权：untrusted 降权"""

    def test_untrusted_ranked_below_owner(self, manager):
        """同 query 语义检索：untrusted 记忆排在 owner 记忆之后"""
        manager.remember(content="Neurova 是一个 AI 助手平台", origin="untrusted")
        manager.remember(content="Neurova 是一个 AI 助手平台", origin="owner")
        results = manager.recall(query="Neurova AI 助手", limit=5)
        origins = [r["origin"] for r in results]
        assert "owner" in origins and "untrusted" in origins
        assert origins.index("owner") < origins.index("untrusted")

    def test_default_origin_no_reorder(self, manager):
        """默认 origin（全 agent）下语义检索排序与历史一致 — 等价性"""
        manager.remember(content="苹果手机很流畅")
        manager.remember(content="香蕉是黄色的水果")
        results = manager.recall(query="香蕉", limit=5)
        assert results[0]["content"] == "香蕉是黄色的水果"


class TestSchemaMigrationOrigin:
    """schema.py 迁移：旧库幂等加列"""

    def test_migrate_schema_adds_origin(self, tmp_path):
        import sqlite3
        import threading

        from neurova.cognitive_layers.memory_layer.schema import migrate_schema

        db = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db)
        # 模拟旧库：无 origin 列的 memories 表
        conn.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, "
            "agent_id TEXT NOT NULL DEFAULT 'default')"
        )
        conn.commit()
        migrate_schema(conn, threading.Lock())
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        # 幂等：再跑一次不炸
        migrate_schema(conn, threading.Lock())
        conn.close()
        assert "origin" in cols


class TestKnowledgeAdapterOrigin:
    """知识检索链路：web 来源条目在归一化载荷中标 untrusted"""

    def test_web_source_maps_to_untrusted(self):
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter

        item = {
            "id": "kb1",
            "title": "网页内容",
            "content": "外部抓取",
            "source": "kb_builder",
            "confidence": 0.9,
        }
        payload = KnowledgeRetrieverAdapter._normalize_item(item)
        assert payload["origin"] == "untrusted"

    def test_owner_source_maps_to_owner(self):
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter

        item = {"id": "kb2", "title": "手工", "content": "用户上传", "source": "user_upload"}
        payload = KnowledgeRetrieverAdapter._normalize_item(item)
        assert payload["origin"] == "owner"

    def test_unknown_source_failsafe_untrusted(self):
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter

        item = {"id": "kb3", "title": "无来源", "content": "x", "source": ""}
        payload = KnowledgeRetrieverAdapter._normalize_item(item)
        assert payload["origin"] == "untrusted"


class TestMemCoreConversationOrigins:
    """聊天链路：用户输入记 owner、agent 回复记 agent"""

    def test_save_conversation_memory_origins(self, tmp_path):
        from types import SimpleNamespace

        from neurova.mem_core import MemCore

        db_path = str(tmp_path / "test_mc.db")
        mm = MemoryManager(db_path=db_path, agent_id="test", user_id="test")
        core = MemCore.__new__(MemCore)
        core._agent = SimpleNamespace(memory_manager=mm, conversation_buffer=None)
        core.save_conversation_memory("你好", "你好！有什么可以帮你？")
        rows = mm.recall(query="", limit=10, use_semantic=False, agent_wide=True)
        by_sender = {r["metadata"].get("sender_type"): r["origin"] for r in rows}
        assert by_sender.get("user") == "owner"
        assert by_sender.get("agent") == "agent"
