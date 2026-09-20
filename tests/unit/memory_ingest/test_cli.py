# -*- coding: utf-8 -*-
"""导入 CLI：detect 只读、apply 需 --yes、undo 按批次。

退出码是给脚本看的（CI 与批处理按码分支，不解析文案）；manager/sessions 走注入，
否则测试要么碰 get_memory_manager 的按作用域缓存，要么把 SessionManager 类级单例
指向仓库 sessions/——那正是我们刚修完的那类污染。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.cli_errors import (
    EXIT_INVALID_BUNDLE, EXIT_OK, EXIT_REPORT_ONLY, EXIT_UNRECOGNIZED)
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.probe import Handprint, _HANDPRINTS
from neurova.session_manager import SessionManager
from scripts.ingest_memory import main


def _jsonl(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines)
    path.write_text(body + "\n", encoding="utf-8")
    return path

COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
        "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


def _rows(**over):
    base = dict(seq=1, session_id="sA", agent_id="凯", kind="context_msg", role="user",
                content="问题", created_at="2026-05-01T10:00:01", dedup_key="k1")
    base.update(over)
    return tuple(base.get(col) for col in COLS)


def _db(path: Path, *rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.executemany(f"INSERT INTO conversation_history VALUES ({','.join('?' * len(COLS))})",
                     list(rows) or [_rows()])
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


@pytest.fixture()
def sessions(tmp_path: Path, monkeypatch) -> SessionManager:
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _session_files(tmp_path: Path, agent_id: str = "kai-import"):
    return list((tmp_path / "sessions" / agent_id).glob("session_*.json")) \
        if (tmp_path / "sessions" / agent_id).exists() else []


def test_detect_reports_store_and_writes_nothing(tmp_path: Path, capsys):
    db = _db(tmp_path / "history.db")

    assert main(["detect", str(db)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "唯一命中" in out and "qwenpaw_history" in out
    assert not (tmp_path / "bundle").exists() and not _session_files(tmp_path)


def test_unrecognized_store_exits_2(tmp_path: Path, capsys):
    conn = sqlite3.connect(tmp_path / "other.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    assert main(["detect", str(tmp_path / "other.db")]) == EXIT_UNRECOGNIZED

    assert main(["apply", str(tmp_path / "other.db"), "--agent-id", "kai-import", "--yes"]) \
        == EXIT_UNRECOGNIZED

    assert "未识别" in capsys.readouterr().out


def test_conflicting_fingerprints_refuse_to_guess(tmp_path: Path):
    """多指纹冲突不猜最像的那个：宁可退出 2 让人来看。"""
    db = _db(tmp_path / "history.db")
    impostor = Handprint("impostor", "sqlite", lambda path: True)
    _HANDPRINTS.append(impostor)
    try:
        assert main(["detect", str(db)]) == EXIT_UNRECOGNIZED
    finally:
        _HANDPRINTS.remove(impostor)


def test_directory_source_reports_per_store(tmp_path: Path, capsys):
    _db(tmp_path / "a" / "history.db")
    _db(tmp_path / "b" / "other.db")

    assert main(["detect", str(tmp_path)]) == EXIT_OK

    assert capsys.readouterr().out.count("唯一命中") == 2


def test_directory_apply_imports_recognized_stores_and_reports_the_rest(
        tmp_path: Path, manager, sessions, capsys):
    """整目录源里混着认不出的文件：认得出的照常导，认不出的照实报并以非零码收尾。

    这不是放宽"不猜"——认不出的那支一个字节都不写，只是不再让一个无关文件
    把整目录的导入判死。
    """
    _db(tmp_path / "hist" / "history.db", _rows(seq=1, dedup_key="a"))
    (tmp_path / "junk").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tmp_path / "junk" / "unrelated.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    code = main(["apply", str(tmp_path), "--agent-id", "mixed-import", "--yes",
                 "--run-id", "run-mixed"], manager=manager, sessions=sessions)

    printed = capsys.readouterr()
    assert code == EXIT_UNRECOGNIZED
    assert "已写入" in printed.out and "未识别" in printed.out
    assert list((tmp_path / "sessions" / "mixed-import").glob("session_*.json"))
    assert manager._memories == {}


def test_directory_undo_cleans_every_recognized_store(tmp_path: Path, manager, sessions):
    _db(tmp_path / "hist" / "history.db", _rows(seq=1, dedup_key="a"))
    main(["apply", str(tmp_path / "hist"), "--agent-id", "mixed-import", "--yes",
          "--run-id", "run-mixed-2"], manager=manager, sessions=sessions)
    assert list((tmp_path / "sessions" / "mixed-import").glob("session_*.json"))

    assert main(["undo", "--agent-id", "mixed-import", "--run-id", "run-mixed-2"],
                manager=manager, sessions=sessions) == EXIT_OK

    assert not list((tmp_path / "sessions" / "mixed-import").glob("session_*.json"))


def test_convert_writes_a_validatable_bundle(tmp_path: Path):
    db = _db(tmp_path / "history.db")
    out = tmp_path / "staging"

    assert main(["convert", str(db), "--out", str(out), "--agent-name", "kai-import"]) == EXIT_OK

    assert validate_bundle(out) == []


def test_apply_without_yes_is_report_only(tmp_path: Path, manager, sessions, capsys):
    db = _db(tmp_path / "history.db")

    code = main(["apply", str(db), "--agent-id", "kai-import"], manager=manager,
                sessions=sessions)

    assert code == EXIT_REPORT_ONLY
    assert "未写库" in capsys.readouterr().out
    assert manager._memories == {} and _session_files(tmp_path) == []


def test_apply_with_yes_writes_turns(tmp_path: Path, manager, sessions, capsys):
    db = _db(tmp_path / "history.db",
             _rows(seq=1, kind="context_msg", content="问题", dedup_key="k1"),
             _rows(seq=2, kind="model_turn", role="assistant", name="凯", content="回答",
                   blocks=json.dumps([{"type": "thinking", "thinking": "想"}]),
                   created_at="2026-05-01T10:00:02", dedup_key="k2"))

    code = main(["apply", str(db), "--agent-id", "kai-import", "--yes",
                 "--run-id", "run-cli-1"], manager=manager, sessions=sessions)

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "run-cli-1" in out and "undo" in out
    stored = json.loads(_session_files(tmp_path)[0].read_text(encoding="utf-8"))["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["metadata"]["ingest_run_id"] == "run-cli-1"
    assert stored[1]["metadata"]["reasoning_content"] == "想"


def test_apply_refuses_bundle_that_fails_validation(tmp_path: Path, manager, sessions, capsys):
    """源里 dedup_key 重复 → identity_key 撞车 → 整包拒绝，一条都不写。"""
    db = _db(tmp_path / "history.db",
             _rows(seq=1, dedup_key="same"), _rows(seq=2, session_id="sA", dedup_key="same"))

    code = main(["apply", str(db), "--agent-id", "kai-import", "--yes"], manager=manager,
                sessions=sessions)

    printed = capsys.readouterr()
    assert code == EXIT_INVALID_BUNDLE
    assert "identity_key" in printed.out + printed.err
    assert manager._memories == {} and _session_files(tmp_path) == []


def test_undo_removes_the_batch(tmp_path: Path, manager, sessions):
    db = _db(tmp_path / "history.db")
    main(["apply", str(db), "--agent-id", "kai-import", "--yes", "--run-id", "run-cli-2"],
         manager=manager, sessions=sessions)

    assert main(["undo", "--agent-id", "kai-import", "--run-id", "run-cli-2"],
                manager=manager, sessions=sessions) == EXIT_OK

    assert _session_files(tmp_path) == []
