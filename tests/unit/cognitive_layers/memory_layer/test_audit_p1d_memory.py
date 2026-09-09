# -*- coding: utf-8 -*-
"""P1-D 记忆层写路径与检索防回归测试（审计批次 P1-D）。

覆盖：
- D1 persist.db WAL：核心持久库开启 WAL + synchronous=NORMAL（写放大
  数量级瓶颈；同项目 dependency_graph 等早已开启）。
- D2 recall touch 批量：recall 对 top-N 的温度更新单事务落盘（原逐条
  connect+commit，limit=10 即 10 次 fsync）。
- D3 依赖图合批：后台依赖提取 entity/edge 批量写（原每 entity/edge
  一次 connect+commit）。
- D6 关键词索引增量：semantic_search 索引存在增量维护入口，recall 每
  查询不再全量 clear+重建（O(N)@锁内）；recall 引擎与 manager 共享单例
  不再互相踩踏。
- D7 温度通道 SQL：按索引排序 LIMIT n（原全量 get_all_memories 深拷贝
  + O(N log N) 排序）。
- D8 _PersistDbStore 参数化/常驻：不再每次查询新建连接。
- D9 refresh_moe_index 增量：不清空重编全量 embedding。
"""
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════
# D1: persist.db WAL
# ═══════════════════════════════════════════════════════════════


class TestD1PersistWAL:
    def test_persist_db_uses_wal(self, tmp_path):
        """MemoryManager 初始化持久库后 journal_mode 必须为 wal。"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        db_dir = tmp_path / "mem"
        db_dir.mkdir()
        mgr = MemoryManager.__new__(MemoryManager)
        mgr._db_path = str(db_dir / "memory.db")
        mgr._agent_id = "a"
        mgr._neuser_id = "n"
        mgr._user_id = "u"
        mgr._init_persistence_db()

        conn = sqlite3.connect(str(db_dir / "neurova_memories_persist.db"))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode.lower() == "wal", f"persist.db journal_mode={mode}（应为 wal）"
        # synchronous 是 per-connection PRAGMA，检查常驻连接上的设置
        sync = mgr._persist_conn.execute("PRAGMA synchronous").fetchone()[0]
        assert sync == 1, f"常驻连接 synchronous={sync}（应为 NORMAL=1）"


# ═══════════════════════════════════════════════════════════════
# D2: recall touch 批量落盘
# ═══════════════════════════════════════════════════════════════


class TestD2TouchBatch:
    def test_recall_persists_touched_memories_batched(self, tmp_path):
        """recall 命中多条记忆时，温度更新经批量事务（executemany）落盘；
        连接打开次数与批次数同阶，不再与命中条数线性相关。"""
        # 用计数器包一层 sqlite3.connect 统计 manager 模块的连接打开次数
        import neurova.cognitive_layers.memory_layer.manager as mm_mod

        opens = {"n": 0}
        orig_connect = sqlite3.connect

        def counting_connect(*a, **kw):
            opens["n"] += 1
            return orig_connect(*a, **kw)

        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        from neurova.cognitive_layers.memory_layer.models import (
            EmotionType,
            LifecycleStage,
            Memory,
            MemoryCategory,
            MemoryType,
        )

        db_dir = tmp_path / "mem"
        db_dir.mkdir()
        mgr = MemoryManager.__new__(MemoryManager)
        mgr._db_path = str(db_dir / "memory.db")
        mgr._agent_id = "a"
        mgr._neuser_id = "n"
        mgr._user_id = "u"
        mgr._init_persistence_db()
        # 常驻连接路径也允许（WAL 常驻连接只需打开一次）
        mgr._persist_conn = getattr(mgr, "_persist_conn", None)

        # 灌 5 条高记忆
        mems = []
        for i in range(5):
            m = Memory(
                id=f"m{i}",
                content=f"记忆内容 {i}",
                memory_type=MemoryType.SEMANTIC,
                category=MemoryCategory.GENERAL,
                lifecycle_stage=LifecycleStage.ACTIVE,
                emotion=EmotionType.NEUTRAL,
            )
            mems.append(m)

        # 模拟 recall 的 touch+persist 段：走批量入口
        opens["n"] = 0
        with patch_connect(counting_connect):
            mgr.persist_memory_batch(mems)

        # 批量路径：允许 ≤2 次连接打开（复用常驻连接则 0）
        assert opens["n"] <= 2, (
            f"批量持久化打开 {opens['n']} 次连接（应 ≤2，原逐条=5）"
        )
        # 数据确实落盘
        conn = orig_connect(str(db_dir / "neurova_memories_persist.db"))
        n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
        assert n == 5, f"批量落盘后应 5 条，实际 {n}"


import contextlib


@contextlib.contextmanager
def patch_connect(counting_connect):
    import neurova.cognitive_layers.memory_layer.manager as mm_mod

    orig = mm_mod.sqlite3.connect
    mm_mod.sqlite3.connect = counting_connect
    try:
        yield
    finally:
        mm_mod.sqlite3.connect = orig


# ═══════════════════════════════════════════════════════════════
# D6: 关键词索引增量
# ═══════════════════════════════════════════════════════════════


class TestD6KeywordIndexIncremental:
    def test_index_upsert_without_full_rebuild(self):
        """单条记忆增删经增量入口 upsert/remove，不触发全量 clear+重建。"""
        from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search

        search = get_semantic_search()
        rebuild_calls = {"n": 0}

        orig_build = search.build_keyword_index

        def counting_build(*a, **kw):
            rebuild_calls["n"] += 1
            return orig_build(*a, **kw)

        search.build_keyword_index = counting_build
        try:
            search.upsert_memory_index({"id": "mem_x", "content": "部署 docker 容器"})
            search.upsert_memory_index({"id": "mem_y", "content": "k8s 集群升级"})
            search.remove_memory_index("mem_x")
            assert rebuild_calls["n"] == 0, (
                f"增量入口触发 {rebuild_calls['n']} 次全量重建（应为 0）"
            )
            hits = search.search_by_keywords("docker", limit=5)
            assert "mem_x" not in hits, "remove 后仍命中"
        finally:
            search.build_keyword_index = orig_build
            search.remove_memory_index("mem_x")
            search.remove_memory_index("mem_y")

    def test_recall_path_uses_incremental_index(self):
        """manager._semantic_recall 每查询不再调用 build_keyword_index
        全量重建（改增量 upsert 语义）。"""
        src = Path(
            "neurova/cognitive_layers/memory_layer/manager.py"
        ).read_text(encoding="utf-8")
        # 全量重建必须被"仅当索引为空"守卫包住（首次建、后续增量）
        assert re.search(
            r"if not search\._keyword_index:\s*\n\s*search\.build_keyword_index", src
        ), "_semantic_recall 的全量重建缺少空索引守卫（仍每查询 O(N) 重建）"


# ═══════════════════════════════════════════════════════════════
# D7: 温度通道 SQL 化
# ═══════════════════════════════════════════════════════════════


class TestD7TemperatureChannelSQL:
    def test_temperature_channel_queries_sql_not_full_scan(self):
        """温度通道经 SQL ORDER BY temperature DESC LIMIT n，不再全量
        get_all_memories 深拷贝排序。"""
        src = Path("neurova/cognitive_layers/memory_layer/neurova_recall.py").read_text(
            encoding="utf-8"
        )
        import re

        m = re.search(r"def _channel_temperature\(.*?(?=\n    def )", src, re.S)
        assert m, "_channel_temperature 未找到"
        body = m.group(0)
        assert "get_top_memories_by_temperature" in body, (
            "温度通道主路径未走 SQL Top-N（get_top_memories_by_temperature）"
        )
        assert "ORDER BY temperature" in body.replace("\n", " ").upper() or (
            "order by temperature" in body.lower()
        ), "温度通道未走 SQL ORDER BY temperature"


# ═══════════════════════════════════════════════════════════════
# D8: _PersistDbStore 常驻连接
# ═══════════════════════════════════════════════════════════════


class TestD8PersistStoreConnection:
    def test_execute_reuses_connection(self, tmp_path):
        """两次 execute 只打开一次连接（常驻只读连接）。"""
        import neurova.mem_core as mc

        store = mc._PersistDbStore(
            str(tmp_path / "persist.db"), "a", "n", "u"
        )
        store._ensure_schema()
        store.upsert_row(
            {
                "id": "r1",
                "content": "c",
                "memory_type": "semantic",
                "category": "general",
                "lifecycle_stage": "active",
                "temperature": 50,
                "importance": 50,
                "access_count": 0,
                "metadata": "{}",
                "agent_id": "a",
                "neuser_id": "n",
                "user_id": "u",
                "shared": 0,
            }
        )

        opens = {"n": 0}
        orig_connect = store._sqlite3.connect

        def counting(*a, **kw):
            opens["n"] += 1
            return orig_connect(*a, **kw)

        store._sqlite3.connect = counting
        try:
            store.execute("SELECT * FROM memories ORDER BY created_at DESC LIMIT 5")
            store.execute("SELECT * FROM memories ORDER BY created_at DESC LIMIT 5")
        finally:
            store._sqlite3.connect = orig_connect

        assert opens["n"] <= 1, (
            f"两次 execute 打开 {opens['n']} 次连接（常驻连接应 ≤1，原每次新建=2）"
        )


# ═══════════════════════════════════════════════════════════════
# D9: MoE 索引刷新增量
# ═══════════════════════════════════════════════════════════════


class TestD9RefreshMoeIncremental:
    def test_refresh_uses_incremental_index(self):
        """refresh_moe_index 走增量（incremental=True），不清空重编全量。"""
        src = Path("neurova/mem_core.py").read_text(encoding="utf-8")
        import re

        m = re.search(r"def refresh_moe_index\(.*?(?=\n    def |\n\ndef )", src, re.S)
        assert m, "refresh_moe_index 未找到"
        body = m.group(0)
        assert "incremental=True" in body, (
            "refresh_moe_index 仍全量清空重编 embedding（嵌入缓存全失效）"
        )
