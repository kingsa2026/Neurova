"""正文表 UPDATE 触发器：改了内容，全文影子必须跟着改。

原判据立的是「引擎自建库缺 `cse_au`」这条缺陷（Tier 2.1）。双根收口后，全文影子
`memories_fts` 与三条触发器长在 `MemoryManager` 的正文表上（名字随宿主改为
`memories_ai` / `memories_ad` / `memories_au`），判据本身一句没松：
UPDATE 后新内容要查得到、旧内容不许残留。
"""

from __future__ import annotations

import sqlite3

from tests.cognitive_body_store import bodyManager

OLD_TEXT = "old text unique_token_alpha"
NEW_TEXT = "new text unique_token_beta"


def _hits(manager, query: str):
    return [mem.content for mem in manager.searchMemoriesFulltext(query, limit=10)]


class TestBodyFtsUpdateTrigger:
    def test_updateContentSyncsFtsIndex(self, tmp_path):
        manager = bodyManager(tmp_path, agentId="test_body_au")
        memoryId = manager.add_memory(OLD_TEXT)

        assert OLD_TEXT in _hits(manager, OLD_TEXT), (
            "基线失败：INSERT 触发器没把正文收进影子表"
        )

        conn = sqlite3.connect(str(manager.persistenceDbPath()), check_same_thread=False)
        conn.execute("UPDATE memories SET content = ? WHERE id = ?", (NEW_TEXT, memoryId))
        conn.commit()
        conn.close()

        assert NEW_TEXT in _hits(manager, NEW_TEXT), (
            "UPDATE 后影子表还留着旧内容——正文表上的 UPDATE 触发器失效了"
        )
        assert OLD_TEXT not in _hits(manager, OLD_TEXT), (
            "旧内容仍被检索命中：影子表与正文脱节，召回会吐出已经不存在的记忆"
        )
