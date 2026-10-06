"""经验库 `id` 主键在 schema 迁移中必须存活（DELETE /experience/None 红灯复现）。

历史故障：工单 004 为放开 `success` 可空，用
`CREATE TABLE ... AS SELECT * FROM ...` 重建 experience_records——该语句生成的表
**不带任何约束**，`id INTEGER PRIMARY KEY AUTOINCREMENT` 退化成普通列；而
`add_experience_record` 的 INSERT 不写 id，新行 id 落 NULL，`_to_contract` 的
`str(row["id"])` 产出字符串 "None" 发给前端，删除时 `int("None")` → 400。

两条红线：
1. 老库（success NOT NULL）迁移后 id 仍必须是 INTEGER PRIMARY KEY；
2. 已被旧迁移损坏的库（id 无主键、存量 NULL id 行）首次连接时自愈，
   NULL id 行补发 id，新写入不再产生 NULL。
"""

import sqlite3

import pytest

from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

# 旧 schema（工单 004 之前）：id 有主键、success 不可空
_OLD_DDL = """
CREATE TABLE experience_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    context TEXT,
    result TEXT,
    success INTEGER NOT NULL,
    timestamp TEXT,
    feedback TEXT,
    agent_id TEXT,
    tags TEXT,
    created_at TEXT
)
"""

# 被旧迁移损坏后的 schema：id 退化为普通列（与生产库实测形态一致）
_BROKEN_DDL = """
CREATE TABLE experience_records (
    id INT,
    skill_name TEXT,
    context TEXT,
    result TEXT,
    success INTEGER,
    timestamp TEXT,
    feedback TEXT,
    agent_id TEXT,
    tags TEXT,
    created_at TEXT,
    content_key TEXT,
    seen_count INT,
    injected_count INT,
    last_injected_at TEXT,
    adoption_outcome TEXT,
    evidence_state TEXT,
    operator_disposition TEXT,
    verifiability_state TEXT
)
"""


def _idPk(cur) -> int:
    for row in cur.execute("PRAGMA table_info(experience_records)"):
        if row[1] == "id":
            return row[5]
    return 0


def test_migration_keeps_id_primary_key(tmp_path):
    db = str(tmp_path / "ekb.db")
    conn = sqlite3.connect(db)
    conn.execute(_OLD_DDL)
    conn.execute(
        "INSERT INTO experience_records (skill_name, success, created_at) VALUES ('s1', 1, 't')"
    )
    conn.commit()
    conn.close()

    ekb = ExperienceKnowledgeBase(db_path=db)
    try:
        cur = ekb._conn.cursor()
        assert _idPk(cur) == 1, "迁移后 id 必须仍是主键（pk=1）"

        rid = ekb.add_experience_record(
            skill_name="s2",
            exp=__import__("neurova.skills.models", fromlist=["ExperienceRecord"]).ExperienceRecord(
                skill_name="s2", context={"user_input": "hi"}, result={}, success=None, timestamp=""
            ),
            agent_id="a1",
        )
        assert rid, "新写入必须返回真实 id"
        row = ekb.get_record_by_id(rid)
        assert row is not None and row["id"] == rid, "按返回 id 必须能取回同一行"
        for rec in ekb.get_experience_records():
            assert rec["id"] is not None, "任何行的 id 都不得为 NULL"
    finally:
        ekb.close()


def test_broken_table_with_null_ids_self_repairs(tmp_path):
    db = str(tmp_path / "ekb-broken.db")
    conn = sqlite3.connect(db)
    conn.execute(_BROKEN_DDL)
    conn.execute(
        "INSERT INTO experience_records (skill_name, success, created_at, seen_count,"
        " injected_count, evidence_state, verifiability_state)"
        " VALUES ('sk1', 1, 't1', 1, 0, 'evidenced', 'unchecked')"
    )
    conn.execute(
        "INSERT INTO experience_records (skill_name, success, created_at, seen_count,"
        " injected_count, evidence_state, verifiability_state)"
        " VALUES ('sk2', 0, 't2', 1, 0, 'evidenced', 'unchecked')"
    )
    conn.commit()
    conn.close()

    ekb = ExperienceKnowledgeBase(db_path=db)
    try:
        cur = ekb._conn.cursor()
        assert _idPk(cur) == 1, "损坏表首次连接必须重建出 id 主键"

        records = ekb.get_experience_records()
        assert len(records) == 2
        ids = [r["id"] for r in records]
        assert all(i is not None for i in ids), "存量 NULL id 行必须补发 id"
        assert len(set(ids)) == len(ids), "补发的 id 必须两两不同"

        rid = ekb.add_experience_record(
            skill_name="sk3",
            exp=__import__("neurova.skills.models", fromlist=["ExperienceRecord"]).ExperienceRecord(
                skill_name="sk3", context={"user_input": "x"}, result={}, success=True, timestamp=""
            ),
            agent_id="a1",
        )
        assert ekb.get_record_by_id(rid) is not None, "自愈后新写入必须可按 id 取回"
    finally:
        ekb.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
