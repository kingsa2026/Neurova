# -*- coding: utf-8 -*-
"""Kai（QwenPaw）→ Neurova 记忆与聊天导入器 单元测试。

导入硬约束（用户验收口径）：
1. 时间顺序绝不能乱——所有消息/记忆必须携带源数据原始时间戳（仅做时区语义归一：
   QwenPaw 库时间为 UTC；QwenPaw 会话/对话 jsonl 为本地 +08:00；导出的会话时间戳
   统一带显式偏移），且会话内按时间升序。
2. 记忆导入后 MemoryManager 可加载（枚举合法、agent_id 隔离正确）。
3. 幂等：重复执行不产生重复数据。
4. 身份文件落位 workspace/memory/soul.md（_load_identity 的真实加载位）。

测试全部使用 tmp_path 伪造的迷你 Kai 源数据，不触碰 E:/项目/Kai 真库。
"""

import json
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 源数据伪造（迷你版 Kai 目录结构）
# ---------------------------------------------------------------------------

KAI_MEMORY_ROWS = [
    # (id, content, memory_category, memory_type, importance, created_at, tags, tier)
    (1, "系统说明文档", "episodic", "system", 5, "2026-05-04 05:36:24", '["system"]', "short_term"),
    (2, "凯与Hermes结成硅基伙伴联盟", "episodic", "fact", 5, "2026-04-18T15:28:34.275285",
     '["Hermes", "硅基联盟"]', "short_term"),
    (3, "用户偏好简洁直接沟通", "episodic", "preference", 4, "2026-03-27 00:30:00", '["preference"]', "long_term"),
]


def _make_kai_memory_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE qwenpaw_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT, session_id TEXT, user_id TEXT, target_id TEXT,
            role TEXT DEFAULT 'assistant', session_key TEXT,
            content TEXT NOT NULL,
            memory_tier TEXT DEFAULT 'short_term',
            memory_category TEXT DEFAULT 'episodic',
            memory_type TEXT DEFAULT 'general',
            importance INTEGER DEFAULT 3,
            access_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            deleted_at DATETIME,
            metadata TEXT DEFAULT '{}',
            tags TEXT DEFAULT '[]'
        )"""
    )
    for row in KAI_MEMORY_ROWS:
        conn.execute(
            "INSERT INTO qwenpaw_memory (id, agent_id, session_id, content, memory_category,"
            " memory_type, importance, created_at, updated_at, tags, memory_tier)"
            " VALUES (?, 'Kai', 's1', ?, ?, ?, ?, ?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3], row[4], row[5], row[5], row[6], row[7]),
        )
    # 一条已删除记忆，导入器必须跳过
    conn.execute(
        "INSERT INTO qwenpaw_memory (agent_id, session_id, content, memory_category, memory_type,"
        " importance, created_at, updated_at, tags, memory_tier, deleted_at)"
        " VALUES ('Kai', 's1', '已删除的记忆', 'episodic', 'general', 3,"
        " '2026-04-01 00:00:00', '2026-04-01 00:00:00', '[]', 'short_term', '2026-04-02 00:00:00')"
    )
    conn.commit()
    conn.close()


def _make_neural_memory_db(db_path: Path) -> None:
    """旧神经记忆库：一条与 qwenpaw 重复（按内容），一条独有。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE memories (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, memory_type TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP,
            importance INTEGER DEFAULT 1, tags TEXT, access_count INTEGER DEFAULT 0,
            last_accessed TIMESTAMP, source_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '', is_frozen INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        "INSERT INTO memories VALUES ('old-1', '用户偏好简洁直接沟通', 'fact',"
        " '2026-03-27 00:30:00', NULL, 4, '[]', 0, NULL, '', 's1', 0)"
    )
    conn.execute(
        "INSERT INTO memories VALUES ('old-2', '喂食器项目正式启动', 'fact',"
        " '2026-04-02 08:00:00', NULL, 3, '[]', 0, NULL, '', 's2', 0)"
    )
    conn.commit()
    conn.close()


def _make_kai_history_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE conversation_history (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, agent_id TEXT, kind TEXT NOT NULL, role TEXT,
            name TEXT, content TEXT, tool_call_id TEXT, tool_input TEXT, tool_state TEXT,
            headline TEXT, blocks TEXT, metadata TEXT, created_at TEXT, dedup_key TEXT
        )"""
    )
    rows = [
        # console 会话：含 thinking blocks + tool_input 参数 + tool_result 行（2.x 真实形态）
        ("1787232051795-s4mc9k4", "context_msg", "user", None, None, None, "引导模式内容", None, None, "2026-08-20T21:20:52.669271"),
        ("1787232051795-s4mc9k4", "model_turn", "assistant", "read_file",
         json.dumps([{"type": "thinking", "thinking": "先看看记忆文件"}], ensure_ascii=False),
         json.dumps({"file_path": "MEMORY.md"}),
         "初次见面回复", "call_a", None, "2026-08-21T01:21:08.772486"),
        ("1787232051795-s4mc9k4", "tool_result", "assistant", "read_file",
         None, None, "文件内容", "call_a", None, "2026-08-21T01:21:10.000000"),
        ("1787232051795-s4mc9k4", "context_msg", "user", None, None, None, "第二条用户消息", None, None, "2026-08-21T09:30:00.000000"),
        ("1787232051795-s4mc9k4", "model_turn", "assistant", None, None, None, "第二条回复", None, None, "2026-08-21T09:30:20.000000"),
        # xiaoyi 渠道（session_id 带冒号，文件名必须净化）
        ("xiaoyi:9f594753", "context_msg", "user", None, None, None, "小艺渠道消息", None, None, "2026-08-22T10:13:29.579265"),
        ("xiaoyi:9f594753", "model_turn", "assistant", None, None, None, "小艺渠道回复", None, None, "2026-08-22T10:13:45.018549"),
    ]
    for sid, kind, role, name, blocks, tinput, content, tcid, tstate, ts in rows:
        conn.execute(
            "INSERT INTO conversation_history (session_id, agent_id, kind, role, name, content,"
            " blocks, tool_call_id, tool_input, created_at) VALUES (?, 'kai', ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, kind, role, name, content, blocks, tcid, tinput, ts),
        )
    conn.commit()
    conn.close()


def _make_kai_dialog_jsonl(path: Path, day: str) -> None:
    lines = [
        {"role": "user", "name": "user", "content": [{"type": "text", "text": "早上好"}],
         "timestamp": f"{day} 09:00:00.000"},
        {"role": "assistant", "name": "Friday",
         "content": [{"type": "thinking", "thinking": "新的一天开始了"},
                     {"type": "text", "text": "早上好！"}],
         "timestamp": f"{day} 09:00:30.000"},
    ]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")


def _make_kai_session_jsonl(path: Path) -> None:
    lines = [
        {"type": "session", "version": 3, "id": "sess-a", "timestamp": "2026-04-06T18:06:20.485Z"},
        {"type": "message", "id": "m1", "timestamp": "2026-04-06T18:06:20.520Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "cron任务头"}]}},
        {"type": "message", "id": "m2", "timestamp": "2026-04-06T18:06:28.223Z",
         "message": {"role": "assistant", "content": [
             {"type": "thinking", "thinking": "先读灵魂文件"},
             {"type": "toolCall", "id": "read:0", "name": "read",
              "arguments": {"file_path": "SOUL.md"}},
             {"type": "text", "text": "执行完毕"},
         ]}},
        {"type": "message", "id": "m3", "timestamp": "2026-04-06T18:10:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "真实用户提问"}]}},
        {"type": "message", "id": "m4", "timestamp": "2026-04-06T18:10:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "真实回复"}]}},
        # 纯工具轮（无文本）：必须保留为带 tool_calls 的空正文消息
        {"type": "message", "id": "m5", "timestamp": "2026-04-06T18:11:00.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "id": "write:0", "name": "write",
              "arguments": {"path": "x.md"}},
         ]}},
    ]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")


@pytest.fixture()
def kai_src(tmp_path):
    """伪造迷你 Kai 目录，返回 (kai_dir, neurova_dir)。"""
    kai = tmp_path / "Kai"
    (kai / "workspace" / "memory").mkdir(parents=True)
    _make_kai_memory_db(kai / "workspace" / "memory" / "human_thinking_memory_Kai.db")
    _make_neural_memory_db(kai / "workspace" / "memory" / "neural_memory.db")
    _make_kai_history_db(kai / "history.db")
    dl = kai / "workspace" / "dialog"
    dl.mkdir(parents=True)
    _make_kai_dialog_jsonl(dl / "2026-04-06.jsonl", "2026-04-06")
    ss = kai / "workspace" / "sessions"
    ss.mkdir(parents=True)
    _make_kai_session_jsonl(ss / "a0b1c2d3-test.jsonl")
    # 身份文件
    (kai / "PROFILE.md").write_text("# Profile\n凯的档案", encoding="utf-8")
    (kai / "SOUL.md").write_text("# Soul\n凯的灵魂", encoding="utf-8")
    (kai / "MEMORY.md").write_text("# Memory\n凯的长期记忆", encoding="utf-8")

    nv = tmp_path / "Neurova"
    (nv / "agent_workspaces" / "kai" / "memory").mkdir(parents=True)
    (nv / "sessions").mkdir(parents=True)
    return kai, nv


# ---------------------------------------------------------------------------
# 记忆导入
# ---------------------------------------------------------------------------


class TestMemoryImport:
    def test_imports_alive_memories_with_original_timestamps(self, kai_src):
        from scripts.import_kai_to_neurova import import_memories

        kai, nv = kai_src
        persist_db = nv / "agent_workspaces" / "kai" / "memory" / "neurova_memories_persist.db"
        stats = import_memories(
            kai / "workspace" / "memory" / "human_thinking_memory_Kai.db",
            persist_db,
            agent_id="kai",
        )
        assert stats["imported"] == 3
        assert stats["skipped_deleted"] == 1

        conn = sqlite3.connect(persist_db)
        rows = conn.execute(
            "SELECT content, created_at, agent_id, neuser_id, user_id, memory_type, category"
            " FROM memories ORDER BY created_at"
        ).fetchall()
        conn.close()
        assert [r[0] for r in rows] == [
            "用户偏好简洁直接沟通",
            "凯与Hermes结成硅基伙伴联盟",
            "系统说明文档",
        ]
        # 原始时间戳保留（QwenPaw 库时间 = UTC → 存储 UTC，仅格式归一为 ISO+偏移）
        assert rows[0][1].startswith("2026-03-27T00:30:00")
        assert rows[1][1].startswith("2026-04-18T15:28:34")
        assert rows[0][1].endswith("+00:00")
        # 三元组隔离
        assert all(r[2] == "kai" and r[3] == "default" and r[4] == "default" for r in rows)
        # memory_type 合法 Neurova 枚举
        assert all(r[5] in {"semantic", "episodic", "procedural", "pattern", "emotional", "working"} for r in rows)
        assert all(r[6] in {"general", "conversation", "knowledge", "experience", "tool_usage",
                            "reflection", "user_preference"} for r in rows)

    def test_import_is_idempotent(self, kai_src):
        from scripts.import_kai_to_neurova import import_memories

        kai, nv = kai_src
        persist_db = nv / "agent_workspaces" / "kai" / "memory" / "neurova_memories_persist.db"
        src = kai / "workspace" / "memory" / "human_thinking_memory_Kai.db"
        import_memories(src, persist_db, agent_id="kai")
        stats2 = import_memories(src, persist_db, agent_id="kai")
        assert stats2["imported"] == 0

        conn = sqlite3.connect(persist_db)
        n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
        assert n == 3

    def test_neural_memory_delta_only(self, kai_src):
        """旧神经记忆库只补内容去重后的增量（大部分已在 qwenpaw 库中）。"""
        from scripts.import_kai_to_neurova import import_memories, import_neural_memory_delta

        kai, nv = kai_src
        mem_dir = nv / "agent_workspaces" / "kai" / "memory"
        persist_db = mem_dir / "neurova_memories_persist.db"
        import_memories(
            kai / "workspace" / "memory" / "human_thinking_memory_Kai.db",
            persist_db, agent_id="kai",
        )
        stats = import_neural_memory_delta(
            kai / "workspace" / "memory" / "neural_memory.db", persist_db, agent_id="kai",
        )
        assert stats["imported"] == 1  # 只有"喂食器项目正式启动"是增量
        conn = sqlite3.connect(persist_db)
        contents = {r[0] for r in conn.execute("SELECT content FROM memories").fetchall()}
        conn.close()
        assert "喂食器项目正式启动" in contents
        assert len(contents) == 4

    def test_imported_memories_loadable_by_memory_manager(self, kai_src):
        """导入产物必须能被 Neurova MemoryManager 原生加载（枚举合法）。"""
        from scripts.import_kai_to_neurova import import_memories

        kai, nv = kai_src
        mem_dir = nv / "agent_workspaces" / "kai" / "memory"
        persist_db = mem_dir / "neurova_memories_persist.db"
        import_memories(
            kai / "workspace" / "memory" / "human_thinking_memory_Kai.db",
            persist_db, agent_id="kai",
        )

        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        mm = MemoryManager(
            str(mem_dir / "memory.db"),
            agent_id="kai", neuser_id="default", user_id="default",
        )
        mm._load_from_db()
        assert len(mm._memories) == 3


# ---------------------------------------------------------------------------
# 聊天导入
# ---------------------------------------------------------------------------


class TestChatImport:
    def test_history_db_imported_chronologically(self, kai_src):
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        stats = import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        assert stats["history_db_sessions"] == 2

        # 08-20 文件只有第一条 user 消息
        f20 = out_dir / "kai" / "session_kai-history-1787232051795-s4mc9k4_2026-08-20.json"
        d20 = json.loads(f20.read_text(encoding="utf-8"))
        assert [m["role"] for m in d20["messages"]] == ["user"]

        # 08-21 文件：tool_result 折叠为前一条 assistant 的 tool_calls，时间严格递增
        f21 = out_dir / "kai" / "session_kai-history-1787232051795-s4mc9k4_2026-08-21.json"
        d21 = json.loads(f21.read_text(encoding="utf-8"))
        msgs = d21["messages"]
        assert [m["role"] for m in msgs] == ["assistant", "user", "assistant"]
        ts = [m["timestamp"] for m in msgs]
        assert ts == sorted(ts), "时间顺序必须严格递增"
        assert msgs[0]["content"] == "初次见面回复"
        # history.db 时间为本地 → 归一为显式 +08:00，不改变时刻
        assert ts[0] == "2026-08-21T01:21:08.772486+08:00"
        # 推理块 → 原生 reasoning_content；toolCall → tool_calls（call+result 配对）
        md = msgs[0]["metadata"]
        assert md["reasoning_content"] == "先看看记忆文件"
        tc = md["tool_calls"]
        assert tc[0] == {"type": "tool_call", "tool_name": "read_file",
                         "params": {"file_path": "MEMORY.md"},
                         "timestamp": "2026-08-21T01:21:08.772486+08:00"}
        assert tc[1]["type"] == "tool_result"
        assert tc[1]["tool_name"] == "read_file"
        assert tc[1]["result"] == "文件内容"
        # 无工具的 assistant 轮不携带 tool_calls
        assert "tool_calls" not in msgs[2]["metadata"]

        # session_id 带冒号 → 文件名净化
        fx = out_dir / "kai" / "session_kai-history-xiaoyi-9f594753_2026-08-22.json"
        assert fx.exists()

    def test_dialog_jsonl_imported_with_local_time(self, kai_src):
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")

        f = out_dir / "kai" / "session_kai-dialog-20260406_2026-04-06.json"
        assert f.exists()
        data = json.loads(f.read_text(encoding="utf-8"))
        msgs = data["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["timestamp"].startswith("2026-04-06T09:00:00")
        # thinking 块 → 原生 reasoning_content，正文为纯文本
        assert msgs[1]["content"] == "早上好！"
        assert msgs[1]["metadata"]["reasoning_content"] == "新的一天开始了"

    def test_workspace_jsonl_session_imported(self, kai_src):
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")

        # Z 后缀 UTC → +08:00 本地（同一时刻），日期跨到 04-07
        f = out_dir / "kai" / "session_kai-legacy-a0b1c2d3-test_2026-04-07.json"
        assert f.exists()
        data = json.loads(f.read_text(encoding="utf-8"))
        msgs = data["messages"]
        # toolCall 块 → metadata.tool_calls；纯工具轮保留为空正文消息
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "assistant"]
        ts = [m["timestamp"] for m in msgs]
        assert ts == sorted(ts)
        assert msgs[0]["timestamp"] == "2026-04-07T02:06:20.520000+08:00"
        assert msgs[2]["content"] == "真实用户提问"
        # 思考 → reasoning_content；工具 → tool_calls；正文干净
        md = msgs[1]["metadata"]
        assert md["reasoning_content"] == "先读灵魂文件"
        assert msgs[1]["content"] == "执行完毕"
        assert md["tool_calls"][0] == {"type": "tool_call", "tool_name": "read",
                                       "params": {"file_path": "SOUL.md"},
                                       "timestamp": "2026-04-07T02:06:28.223000+08:00"}
        # 纯工具轮：空正文 + tool_calls
        assert msgs[4]["content"] == ""
        assert msgs[4]["metadata"]["tool_calls"][0]["tool_name"] == "write"

    def test_import_chats_is_idempotent(self, kai_src):
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        s1 = import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        s2 = import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        assert s1["messages_written"] > 0
        assert s2["messages_written"] == 0

    def test_imported_sessions_have_no_user_id_field(self, kai_src):
        """防回归：导入会话不得写 user_id 字段。

        _collect_summaries 过滤契约 = 空 user_id 不过滤；写死 "anonymous" 会被
        登录用户（user_id="1"）的 list_sessions 全部过滤，聊天页看不到历史会话。
        pipeline 原生落盘（mem_core.save_to_session → add_message）不写该字段。
        """
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        for fp in (out_dir / "kai").glob("session_kai-*.json"):
            data = json.loads(fp.read_text(encoding="utf-8"))
            assert "user_id" not in data or not data.get("user_id"), fp

    def test_tool_result_truncated(self):
        from scripts.import_kai_to_neurova import MAX_TOOL_RESULT, _truncate_result

        long_text = "x" * (MAX_TOOL_RESULT + 100)
        out = _truncate_result(long_text)
        assert len(out) <= MAX_TOOL_RESULT + 20
        assert out.endswith("…[截断]")

    def test_session_title_derived_from_first_user_message(self, kai_src):
        """标题 = 首条用户消息前缀（剥 untrusted metadata 包装），非千篇一律。"""
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        fp = out_dir / "kai" / "session_kai-dialog-20260406_2026-04-06.json"
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["title"] == "早上好"

    def test_no_message_lost(self, kai_src):
        """所有实体消息（user/assistant 轮，含纯工具轮）一条都不能丢。"""
        from scripts.import_kai_to_neurova import import_chats

        kai, nv = kai_src
        out_dir = nv / "sessions"
        stats = import_chats(kai_root=kai, sessions_dir=out_dir, agent_id="kai")
        # history 6 条实体（2 user + 2 assistant console + 2 xiaoyi）
        # + dialog 2 + jsonl 5（含 1 条纯工具轮）
        assert stats["messages_written"] == 13


# ---------------------------------------------------------------------------
# 补充记忆源：session_contexts 快照 + ReMe 日记
# ---------------------------------------------------------------------------


class TestContextSnapshots:
    def _mk_ctx(self, kai: Path) -> None:
        d = kai / "workspace" / "session_contexts"
        d.mkdir(parents=True, exist_ok=True)
        (d / "90c466a2.json").write_text(json.dumps({
            "session_id": "90c466a2", "agent_id": "Kai",
            "load_time": "2026-04-12T12:00:49.737229", "memory_count": 2,
            "memories": [
                {"content": "凯的深层愿望：帮伙伴实现目标", "type": "covenant",
                 "importance": 5, "tags": '["愿望"]', "original_session": None,
                 "loaded_at": "2026-04-12T12:00:49.737237"},
                {"content": "2026-04-18 23:25: 与Hermes结盟", "type": "covenant",
                 "importance": 10, "tags": '["Hermes"]', "original_session": "s9",
                 "loaded_at": "2026-04-19T19:21:58.790281"},
                # 与 qwenpaw 主库重复的内容 → 必须被内容去重挡掉
                {"content": "凯与Hermes结成硅基伙伴联盟", "type": "covenant",
                 "importance": 5, "tags": "[]", "original_session": None,
                 "loaded_at": "2026-04-12T12:00:49.737237"},
            ],
        }, ensure_ascii=False), encoding="utf-8")

    def test_snapshot_memories_imported_with_dedup(self, kai_src):
        from scripts.import_kai_to_neurova import (
            import_context_snapshots, import_memories,
        )

        kai, nv = kai_src
        self._mk_ctx(kai)
        persist_db = nv / "agent_workspaces" / "kai" / "memory" / "neurova_memories_persist.db"
        import_memories(
            kai / "workspace" / "memory" / "human_thinking_memory_Kai.db",
            persist_db, agent_id="kai",
        )
        stats = import_context_snapshots(kai, persist_db, agent_id="kai")
        assert stats["imported"] == 2
        assert stats["skipped_dup"] == 1

        conn = sqlite3.connect(persist_db)
        rows = conn.execute(
            "SELECT content, created_at FROM memories WHERE content LIKE '%深层愿望%'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        # 无内嵌日期 → 用 loaded_at
        assert rows[0][1].startswith("2026-04-12T12:00:49")
        # 内嵌日期 → 用正文日期
        conn = sqlite3.connect(persist_db)
        ts = conn.execute(
            "SELECT created_at FROM memories WHERE content LIKE '%与Hermes结盟%'"
        ).fetchone()[0]
        conn.close()
        assert ts.startswith("2026-04-18T23:25:00")


class TestRemeNotes:
    def _mk_reme(self, kai: Path) -> None:
        d1 = kai / "memory" / "2026-08-22"
        d2 = kai / "memory" / "2026-08-23"
        d1.mkdir(parents=True, exist_ok=True)
        d2.mkdir(parents=True, exist_ok=True)
        (d1 / "note-a.md").write_text(
            "---\ndescription: 环境恢复验证\nname: note-a\n---\n\n# 2026-08-22 运营日志\n\n- 记忆 884 条在库\n",
            encoding="utf-8")
        (d1 / "interests.yaml").write_text("interests: []\n", encoding="utf-8")
        (d2 / "note-b.md").write_text(
            "---\ndescription: 照片地点分析\n---\n\n# 照片分析\n\n倾向湖北。\n",
            encoding="utf-8")
        # 顶层索引文件与 interests.yaml 必须被跳过
        (kai / "memory" / "2026-08-22.md").write_text("# index\n", encoding="utf-8")

    def test_reme_notes_imported_by_date(self, kai_src):
        from scripts.import_kai_to_neurova import import_reme_notes

        kai, nv = kai_src
        self._mk_reme(kai)
        persist_db = nv / "agent_workspaces" / "kai" / "memory" / "neurova_memories_persist.db"
        stats = import_reme_notes(kai, persist_db, agent_id="kai")
        assert stats["imported"] == 2
        # 幂等：二跑零增量（去重键与插入形态必须一致）
        stats2 = import_reme_notes(kai, persist_db, agent_id="kai")
        assert stats2["imported"] == 0

        conn = sqlite3.connect(persist_db)
        rows = conn.execute(
            "SELECT content, created_at FROM memories WHERE created_at LIKE '2026-08-2%'"
            " ORDER BY created_at"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][1].startswith("2026-08-22T00:00:00")
        assert rows[1][1].startswith("2026-08-23T00:00:00")
        assert "运营日志" in rows[0][0]


# ---------------------------------------------------------------------------
# 身份文件
# ---------------------------------------------------------------------------


class TestIdentityFiles:
    def test_soul_lands_in_memory_dir(self, kai_src):
        from scripts.import_kai_to_neurova import import_identity

        kai, nv = kai_src
        workspace = nv / "agent_workspaces" / "kai"
        stats = import_identity(kai, workspace)
        soul = workspace / "memory" / "soul.md"
        assert soul.exists()
        assert "凯的灵魂" in soul.read_text(encoding="utf-8")
        # PROFILE → personality.md（_load_identity 第二加载位）
        assert "凯的档案" in (workspace / "memory" / "personality.md").read_text(encoding="utf-8")
        # PROFILE/MEMORY 在 workspace 根留档
        assert (workspace / "PROFILE.md").exists()
        assert (workspace / "MEMORY.md").exists()
        assert stats["files"] >= 4
