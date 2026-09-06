"""EKB 经验知识库写入防污染 — 契约测试（红绿灯 TDD）

根因（3920 条垃圾经验事故，2026-09-06）：
1. 管线级测试用 MagicMock evolution（hasattr 恒真）→ _step_record_experience
   的 EKB 写入分支必执行 → 模块单例默认打生产库 data/experience_knowledge.db，
   测试对话（"Hello" ×1223 等）全部灌进真库；
2. add_experience_record 无去重门禁，同内容重复写入照单全收；
3. str(MagicMock) 直接落库 agent_id 列（~93 行 "<MagicMock ...>" 垃圾值）。

锁定契约：
- add_experience_record 对完全相同 (agent_id, skill_name, context, result) 去重；
- agent_id 非法值（Mock repr / 含空白尖括号）归一为 None，不落库；
- DB 路径支持 NEUROVA_EKB_DB 环境变量覆盖（conftest autouse 隔离挂点）；
- conftest autouse fixture 生效：测试内 EKB 单例不指向项目 data/ 目录。
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def ekb(tmp_path, monkeypatch):
    from neurova.skills import experience_knowledge_base as ekb_mod

    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "ekb.db"))
    ekb_mod.reset_experience_knowledge_base()
    db = ekb_mod.get_experience_knowledge_base()
    yield db
    ekb_mod.reset_experience_knowledge_base()


class TestDedupGate:
    def test_identical_record_not_duplicated(self, ekb):
        """完全相同的经验（agent+skill+context+result）只落一行。"""
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        exp = ExperienceRecord(
            skill_name="chat",
            context={"user_input": "Hello"},
            result={"reply_excerpt": "hi there"},
            success=True,
        )
        rid1 = ekb.add_experience_record("chat", exp, agent_id="a1")
        rid2 = ekb.add_experience_record("chat", exp, agent_id="a1")

        n = sqlite3.connect(ekb._db_path).execute(
            "SELECT COUNT(*) FROM experience_records WHERE skill_name='chat'"
        ).fetchone()[0]
        assert n == 1, f"重复经验应被去重门禁拦截，实际 {n} 行"
        assert rid1 == rid2, "重复写入应返回既有记录 id"

    def test_different_reply_not_deduped(self, ekb):
        """同问不同答是不同经验（reply 不同），不误杀。"""
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        base = {"user_input": "Hello"}
        ekb.add_experience_record(
            "chat",
            ExperienceRecord(skill_name="chat", context=base, result={"reply_excerpt": "v1"}, success=True),
            agent_id="a1",
        )
        ekb.add_experience_record(
            "chat",
            ExperienceRecord(skill_name="chat", context=base, result={"reply_excerpt": "v2"}, success=True),
            agent_id="a1",
        )
        n = sqlite3.connect(ekb._db_path).execute(
            "SELECT COUNT(*) FROM experience_records"
        ).fetchone()[0]
        assert n == 2, "不同 result 应各自成行"

    def test_dedup_scoped_by_agent(self, ekb):
        """去重按 agent 隔离：A agent 的经验不影响 B agent 写入。"""
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        exp = ExperienceRecord(
            skill_name="chat", context={"user_input": "X"}, result={"reply_excerpt": "Y"}, success=True,
        )
        ekb.add_experience_record("chat", exp, agent_id="agent-a")
        ekb.add_experience_record("chat", exp, agent_id="agent-b")
        n = sqlite3.connect(ekb._db_path).execute(
            "SELECT COUNT(*) FROM experience_records"
        ).fetchone()[0]
        assert n == 2


class TestAgentIdSanitization:
    def test_mock_repr_agent_id_normalized_to_none(self, ekb):
        """MagicMock repr（含空格/尖括号）不得落库 → 归一为 None。"""
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        bad = "<MagicMock name='mock.agent_id' id='2960297107120'>"
        rid = ekb.add_experience_record(
            "chat",
            ExperienceRecord(skill_name="chat", context={"u": "1"}, result={"r": "1"}, success=True),
            agent_id=bad,
        )
        row = sqlite3.connect(ekb._db_path).execute(
            "SELECT agent_id FROM experience_records WHERE id=?", (rid,)
        ).fetchone()
        assert row is not None
        assert row[0] is None, f"非法 agent_id 应归一为 None，实际落库: {row[0]!r}"

    def test_valid_agent_id_preserved(self, ekb):
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        rid = ekb.add_experience_record(
            "chat",
            ExperienceRecord(skill_name="chat", context={"u": "1"}, result={"r": "1"}, success=True),
            agent_id="agent-01_x",
        )
        row = sqlite3.connect(ekb._db_path).execute(
            "SELECT agent_id FROM experience_records WHERE id=?", (rid,)
        ).fetchone()
        assert row[0] == "agent-01_x"


class TestDbPathEnvOverride:
    def test_env_override_controls_singleton_path(self, tmp_path, monkeypatch):
        """NEUROVA_EKB_DB 环境变量控制单例落盘位置（conftest 隔离挂点）。"""
        from neurova.skills import experience_knowledge_base as ekb_mod

        target = tmp_path / "isolated" / "ekb.db"
        monkeypatch.setenv("NEUROVA_EKB_DB", str(target))
        ekb_mod.reset_experience_knowledge_base()
        try:
            db = ekb_mod.get_experience_knowledge_base()
            assert str(db._db_path) == str(target)
        finally:
            ekb_mod.reset_experience_knowledge_base()

    def test_no_env_falls_back_to_project_data_dir(self, monkeypatch):
        """未设环境变量时保持向后兼容默认路径。"""
        from neurova.skills import experience_knowledge_base as ekb_mod

        monkeypatch.delenv("NEUROVA_EKB_DB", raising=False)
        ekb_mod.reset_experience_knowledge_base()
        try:
            db = ekb_mod.get_experience_knowledge_base()
            assert str(db._db_path).endswith("experience_knowledge.db")
            assert "data" in str(db._db_path)
        finally:
            ekb_mod.reset_experience_knowledge_base()
