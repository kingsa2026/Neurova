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


def test_apply_accepts_a_previously_converted_bundle(tmp_path: Path, manager, sessions):
    """convert 的产物必须能直接 apply——否则"先看包再导"这条路是断的。"""
    db = _db(tmp_path / "history.db")
    bundle = tmp_path / "bundle"
    assert main(["convert", str(db), "--out", str(bundle),
                 "--agent-name", "kai-import"]) == EXIT_OK

    code = main(["apply", str(bundle), "--agent-id", "kai-import", "--yes",
                 "--run-id", "run-bundle-1"], manager=manager, sessions=sessions)

    assert code == EXIT_OK
    assert list((tmp_path / "sessions" / "kai-import").glob("session_*.json"))


def test_apply_on_directory_without_stores_is_not_success(tmp_path: Path, manager, sessions):
    """指错目录（一个可探的 store 都没有）不能退 0：那和"导完了"无法区分。"""
    empty = tmp_path / "nothing"
    empty.mkdir()
    (empty / "readme.txt").write_text("不是会话", encoding="utf-8")

    assert main(["apply", str(empty), "--agent-id", "kai-import", "--yes"],
                manager=manager, sessions=sessions) == EXIT_UNRECOGNIZED


def test_detect_on_a_converted_bundle_still_reports_nothing_to_import(
        tmp_path: Path, capsys):
    """包不是源：detect 指到包上要说清"这是包"，不是逐文件报未识别。"""
    db = _db(tmp_path / "history.db")
    bundle = tmp_path / "bundle"
    main(["convert", str(db), "--out", str(bundle), "--agent-name", "kai-import"])

    assert main(["detect", str(bundle)]) == EXIT_OK

    assert "包" in capsys.readouterr().out


def _bundle_with_memories(tmp_path: Path) -> Path:
    """直接落一支带记忆行的包：apply 认包，不必再造一个源库。"""
    root = tmp_path / "membundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "memories.jsonl").write_text(json.dumps(
        {"identity_key": "m1", "content": "一条回填的历史", "memory_type": "semantic",
         "category": "general", "origin": "owner", "importance": 50.0,
         "ts": "2026-05-01T10:00:00+00:00"}, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-05-01T10:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "test", "version": "1"},
        "counts": {"transcripts": 0, "memories": 1, "relations": 0},
        "dropped": [], "stores": []}), encoding="utf-8")
    return root


def test_apply_reports_written_memories_need_a_restart_to_be_visible(
        tmp_path: Path, manager, sessions, capsys):
    """写入侧与运行中的后端各持一份内存表：CLI 必须把"记忆要重启才可见"说清楚。

    会话面是读盘即见的，记忆面只在进程构造时 `_load_from_db`（manager.py:248 是唯一调用点），
    所以同一个"导入成功"两半不一致。改运行期咽喉（开端点 / 加 reload 入口）是产品决定，
    本轮不拍；但把不一致藏着不说不行——整批记忆在后端里一条看不见，报告却写"已写入"。
    这里钉的是诚实暴露：口径印在输出里；没写记忆的批次不该出现这句。
    """
    code = main(["apply", str(_bundle_with_memories(tmp_path)), "--agent-id", "kai-import",
                 "--yes"], manager=manager, sessions=sessions)
    assert code == EXIT_OK
    printed = capsys.readouterr().out
    assert "重启" in printed and "记忆" in printed

    db = _db(tmp_path / "history.db")   # 只有会话行，记忆为 0 条
    main(["apply", str(db), "--agent-id", "kai-import", "--yes"], manager=manager,
         sessions=sessions)
    assert "重启" not in capsys.readouterr().out


# --- F-04 属主参数：多用户/多渠道下导入他人历史必须能指定归属


def test_apply_points_at_the_reload_route_when_memories_were_written(
        tmp_path: Path, manager, sessions, capsys):
    """可见性不再只有"重启"一条路：CLI 要指出不重启就看见的办法（F-05 闭环）。

    前批只做了诚实暴露（"需重启后才可见"），用户拍板开了 HTTP 入口后，出口那句
    必须跟着换代——否则用户按 CLI 的指引去重启，而端点早已能解决。判据：
    真写了记忆时那句要指向 reload 通道；没写记忆的批次不该出现这句。
    """
    code = main(["apply", str(_bundle_with_memories(tmp_path)), "--agent-id", "kai-import",
                 "--yes"], manager=manager, sessions=sessions)
    assert code == EXIT_OK
    printed = capsys.readouterr().out
    assert "reload" in printed, (
        "写了记忆却不告诉用户怎么不重启就看见——可见性通道接好了而出口没跟上"
    )

    db = _db(tmp_path / "history.db")
    main(["apply", str(db), "--agent-id", "kai-import", "--yes"], manager=manager,
         sessions=sessions)
    assert "reload" not in capsys.readouterr().out


def test_apply_owner_parameter_lands_on_the_session(tmp_path: Path, manager, sessions):
    db = _db(tmp_path / "history.db")

    code = main(["apply", str(db), "--agent-id", "kai-import", "--yes",
                 "--run-id", "run-owner-1", "--owner-user-id", "u_alice"],
                manager=manager, sessions=sessions)

    assert code == EXIT_OK
    assert [s["session_id"] for s in sessions.list_sessions("kai-import", user_id="u_alice")]
    assert sessions.list_sessions("kai-import", user_id="u_bob") == []


def test_apply_without_owner_keeps_the_session_shared(tmp_path: Path, manager, sessions):
    db = _db(tmp_path / "history.db")

    main(["apply", str(db), "--agent-id", "kai-import", "--yes", "--run-id", "run-owner-2"],
         manager=manager, sessions=sessions)

    assert sessions.list_sessions("kai-import")[0]["user_id"] == ""
    assert sessions.list_sessions("kai-import", user_id="u_bob")


def test_apply_refuses_to_take_over_an_owned_session(tmp_path: Path, manager, sessions, capsys):
    """同一份会话被两次不同属主的导入碰：第二次整批拒绝，不改写登记在册的属主。"""
    db = _db(tmp_path / "history.db")
    assert main(["apply", str(db), "--agent-id", "kai-import", "--yes",
                 "--run-id", "run-owner-a", "--owner-user-id", "u_alice"],
                manager=manager, sessions=sessions) == EXIT_OK

    code = main(["apply", str(db), "--agent-id", "kai-import", "--yes",
                 "--run-id", "run-owner-b", "--owner-user-id", "u_bob"],
                manager=manager, sessions=sessions)

    printed = capsys.readouterr()
    assert code == EXIT_INVALID_BUNDLE
    assert "u_alice" in printed.out + printed.err
    assert sessions.list_sessions("kai-import", user_id="u_alice")


def test_undo_reports_the_owner_of_what_it_removes(tmp_path: Path, manager, sessions, capsys):
    """撤销要能说清撤的是谁的批次：报告里看得见属主。"""
    db = _db(tmp_path / "history.db")
    main(["apply", str(db), "--agent-id", "kai-import", "--yes", "--run-id", "run-owner-3",
          "--owner-user-id", "u_alice"], manager=manager, sessions=sessions)

    assert main(["undo", "--agent-id", "kai-import", "--run-id", "run-owner-3"],
                manager=manager, sessions=sessions) == EXIT_OK

    assert "u_alice" in capsys.readouterr().out


def test_undo_points_at_the_reload_route_when_memories_were_removed(
        tmp_path: Path, manager, sessions, capsys):
    """撤销的出口必须与 apply 的出口对称：撤完还要让运行中的后端与盘对账。

    撤销只删盘，运行中的实例手里那份快照仍持这批行，而它的任何一次改写都会把
    撤销结果写回盘上——CLI 不把这条出口说出来，用户看到的就是"撤了还在"。
    """
    code = main(["apply", str(_bundle_with_memories(tmp_path)), "--agent-id", "kai-import",
                 "--yes", "--run-id", "undo-out-1"], manager=manager, sessions=sessions)
    assert code == EXIT_OK
    capsys.readouterr()

    assert main(["undo", "--agent-id", "kai-import", "--run-id", "undo-out-1"],
                manager=manager, sessions=sessions) == EXIT_OK

    printed = capsys.readouterr().out
    assert "reload" in printed, (
        "撤销了记忆却不告诉用户运行中的后端要重新对账——它手里那批行还在，"
        "点一次强化就把撤销结果写回盘上"
    )
