"""Tier 2.1 RED 测试 — cse_au UPDATE trigger 缺失

Bug 2: cognitive_storage_engine.py 只有 cse_ai (INSERT) 和 cse_ad (DELETE) trigger，
缺 cse_au (UPDATE)。当 UPDATE memories SET content 时 FTS 索引不同步。

本测试验证：UPDATE content 后，FTS 索引应同步更新（新内容可搜索，旧内容不残留）。
当前预期 FAIL（无 cse_au trigger）。
"""

import pytest
from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    UnifiedMemoryNode,
)


class TestCseFtsUpdateTrigger:
    """cse_au UPDATE trigger 验证"""

    def test_update_content_syncs_fts_index(self, tmp_path):
        """UPDATE memories SET content 应同步更新 FTS 索引

        步骤：
        1. 创建引擎，store 一条 content='old text' 的节点
        2. flush 到 L1（触发 cse_ai INSERT trigger，FTS 索引 'old text'）
        3. 验证 retrieve('old text') 能找到（基线）
        4. 直接 SQL UPDATE content='new text'
        5. 验证 retrieve('new text') 能找到（RED — 无 cse_au trigger 时 FTS 仍为 'old text'）
        6. 验证 retrieve('old text') 找不到（RED — 无 cse_au trigger 时 FTS 残留 'old text'）
        """
        # 1. 创建引擎
        engine = CognitiveStorageEngine(agent_id="test_cse_au", data_dir=str(tmp_path))

        # 2. store 节点
        node = UnifiedMemoryNode(content="old text unique_token_alpha")
        node_id = engine.store(node)

        # 3. flush 到 L1（触发 cse_ai INSERT trigger）
        engine._flush_l0_to_l1()

        # 4. 基线：retrieve('old text') 应找到
        old_hits = engine.retrieve("old text unique_token_alpha", limit=10)
        assert len(old_hits) >= 1, "基线失败：INSERT 后 FTS 应能搜索到 'old text'"
        assert old_hits[0].id == node_id

        # 5. SQL UPDATE content='new text'
        with engine._db_lock:
            engine._db.execute(
                "UPDATE memories SET content = ? WHERE id = ?",
                ("new text unique_token_beta", node_id),
            )
            engine._db.commit()

        # 6. RED: retrieve('new text') 应找到（当前 FAIL — FTS 索引仍为 'old text'）
        new_hits = engine.retrieve("new text unique_token_beta", limit=10)
        assert len(new_hits) >= 1, (
            "RED: UPDATE 后 FTS 未索引新内容 'new text' — 缺 cse_au trigger"
        )

        # 7. RED: retrieve('old text') 应找不到（当前 FAIL — FTS 残留 'old text'）
        stale_hits = engine.retrieve("old text unique_token_alpha", limit=10)
        assert len(stale_hits) == 0, (
            "RED: UPDATE 后 FTS 仍残留旧内容 'old text' — 缺 cse_au trigger"
        )

        engine.close()
