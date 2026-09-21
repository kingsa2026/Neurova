# -*- coding: utf-8 -*-
"""F-18：同一支源被两条导入路先后处理，盘上只能有一套会话身份。

实测过的分裂（规格 §7.3）：同一支每日对话源，老脚本落
`session_kai-dialog-20260501`、ingest 落 `session_dialog-2026-05-01`——两套会话号、
两套行幂等键，互不认对方。于是同一段历史在盘上两份，两条路重跑各自都当"新数据"。

修法不是给老脚本再补一份派生规则（那是第二份事实源），而是让老脚本的会话导入
**走产品链**：会话号与行幂等键只在转换器里定义一处，两条路的幂等域因此天然是同一个。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.intake import apply_bundle
from neurova.memory_ingest.probe import probe_store
from neurova.session_manager import SessionManager

_COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
         "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


@pytest.fixture()
def manager(tmp_path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "mem" / "memory.db"))


@pytest.fixture()
def kai_root(tmp_path: Path) -> Path:
    """迷你 Kai 源：产品链认得出的三族会话各一支。"""
    root = tmp_path / "Kai"
    (root / "workspace" / "dialog").mkdir(parents=True)
    (root / "workspace" / "sessions").mkdir(parents=True)
    (root / "workspace" / "dialog" / "2026-04-06.jsonl").write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in [
            {"role": "user", "name": "u", "content": [{"type": "text", "text": "早上好"}],
             "timestamp": "2026-04-06 09:00:00.000"},
            {"role": "assistant", "name": "a",
             "content": [{"type": "thinking", "thinking": "新的一天"},
                         {"type": "text", "text": "早上好！"}],
             "timestamp": "2026-04-06 09:00:30.000"}]),
        encoding="utf-8")
    (root / "workspace" / "sessions" / "a0b1c2d3-test.jsonl").write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in [
            {"type": "session", "version": 3, "id": "sess-a",
             "timestamp": "2026-04-06T18:06:20.485Z"},
            {"type": "message", "id": "m1", "timestamp": "2026-04-06T18:06:20.520Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "1.x 提问"}]}}]),
        encoding="utf-8")
    conn = sqlite3.connect(root / "history.db")
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in _COLS) + ")")
    conn.execute(f"INSERT INTO conversation_history VALUES ({','.join('?' * len(_COLS))})",
                 (1, "sA", "kai", "context_msg", "user", None, "会话表提问", None, None,
                  None, None, None, None, "2026-05-01T10:00:01", "k1"))
    conn.commit()
    conn.close()
    return root


def _files(sessions: SessionManager, agent_id: str = "kai") -> list:
    directory = sessions._sessions_dir / agent_id
    return sorted(p.name for p in directory.glob("session_*.json")) if directory.is_dir() else []


def test_legacy_script_reuses_the_product_session_identity(kai_root: Path, sessions):
    """老脚本落盘的会话号必须就是产品链那一个——两套会话号就是两套身份。"""
    from scripts.import_kai_to_neurova import import_chats

    import_chats(kai_root=kai_root, sessions_dir=sessions._sessions_dir, agent_id="kai")

    names = _files(sessions)
    assert "session_dialog-2026-04-06_2026-04-06.json" in names
    assert "session_a0b1c2d3-test_2026-04-07.json" in names
    assert "session_sA_2026-05-01.json" in names
    assert not [n for n in names if n.startswith("session_kai-")]


def test_ingest_import_after_the_legacy_script_adds_nothing(kai_root: Path, sessions, manager):
    """两条路的幂等域是同一个：老脚本写过的行，产品链必须认得出来。"""
    from scripts.import_kai_to_neurova import import_chats

    import_chats(kai_root=kai_root, sessions_dir=sessions._sessions_dir, agent_id="kai")
    before = _files(sessions)

    for store in probe_store(kai_root / "workspace" / "dialog"):
        bundle = kai_root / "bundle"
        CONVERTERS[store.hits[0]](Path(store.path), bundle, agent_name="kai")
        report = apply_bundle(bundle, agent_id="kai", manager=manager, sessions=sessions,
                              run_id="nvimp-interop")
        assert (report.messages_added, report.messages_skipped) == (0, 2)

    assert _files(sessions) == before


def test_legacy_script_rows_carry_the_ingest_identity_key(kai_root: Path, sessions):
    """落盘行必须带产品链读侧唯一认的键；自造一套键就等于互不感知。"""
    from scripts.import_kai_to_neurova import import_chats

    import_chats(kai_root=kai_root, sessions_dir=sessions._sessions_dir, agent_id="kai")

    path = sessions._sessions_dir / "kai" / "session_dialog-2026-04-06_2026-04-06.json"
    stored = json.loads(path.read_text(encoding="utf-8"))["messages"]
    keys = [m["metadata"]["ingest"]["identity_key"] for m in stored]
    assert all(keys) and len(set(keys)) == len(keys)
    assert [m["metadata"]["ingest"]["session_id"] for m in stored] == \
        ["dialog-2026-04-06"] * len(stored)


def test_legacy_script_reports_turns_written_per_family(kai_root: Path, sessions):
    """三族各自的计数仍要报出来——它是对外口径，不是内部细节。"""
    from scripts.import_kai_to_neurova import import_chats

    stats = import_chats(kai_root=kai_root, sessions_dir=sessions._sessions_dir, agent_id="kai")

    assert stats["dialog_sessions"] == 1
    assert stats["legacy_sessions"] == 1
    assert stats["history_db_sessions"] == 1
    assert stats["messages_written"] == 4          # 1 + 1 + 2（会话表两行不成轮）
    assert stats["total_sessions"] == 3


def test_legacy_script_after_ingest_skips_without_touching_disk(kai_root: Path, sessions,
                                                                manager):
    """反方向同样成立：产品链先导，老脚本次跑零增量、盘上文件一个字节不动。

    两个方向都要咬合才算真打通——只测一个方向，把"两边各自认得自己"当成打通。
    """
    from scripts.import_kai_to_neurova import import_chats

    stores = probe_store(kai_root)
    stores = stores if isinstance(stores, list) else [stores]
    assert len(stores) == 3
    for index, store in enumerate(stores):
        bundle = kai_root / f"bundle-{index}"
        CONVERTERS[store.hits[0]](Path(store.path), bundle, agent_name="kai")
        apply_bundle(bundle, agent_id="kai", manager=manager, sessions=sessions,
                     run_id=f"nvimp-first-{index}")

    path = sessions._sessions_dir / "kai" / "session_dialog-2026-04-06_2026-04-06.json"
    before = path.read_bytes()

    stats = import_chats(kai_root=kai_root, sessions_dir=sessions._sessions_dir,
                         agent_id="kai")

    assert stats["messages_written"] == 0
    assert path.read_bytes() == before
