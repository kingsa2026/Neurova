# -*- coding: utf-8 -*-
"""intake 编排：校验 → 只读出计划 → 显式写库 → 按批次撤销。

"不 --apply 就不写库"的姿态在这里落地：plan_bundle 全程只读。写会话必须过轮形装配，
否则导入产物是运行期从不在盘上出现的形状（见 bundle/turns.py）。
"""
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.intake import apply_bundle, plan_bundle
from neurova.session_manager import SessionManager

_ROWS: List[Dict[str, Any]] = [
    {"session_id": "sA", "seq": 1, "kind": "user_message", "ts": "2026-05-01T10:00:01+00:00",
     "identity_key": "e1", "role": "user",
     "content_blocks": [{"type": "text", "text": "问题"}]},
    {"session_id": "sA", "seq": 2, "kind": "assistant_message",
     "ts": "2026-05-01T10:00:02+00:00", "identity_key": "e2", "role": "assistant",
     "content_blocks": [{"type": "text", "text": "先读文件"}], "reasoning_state": "text",
     "reasoning_text": "在想"},
    {"session_id": "sA", "seq": 3, "kind": "tool_call", "ts": "2026-05-01T10:00:03+00:00",
     "identity_key": "e3", "role": "assistant", "tool_call_id": "tc1",
     "tool_name": "fs_read", "extra": {"tool_input": '{"path": "A.md"}'}},
    {"session_id": "sA", "seq": 4, "kind": "tool_result", "ts": "2026-05-01T10:00:04+00:00",
     "identity_key": "e4", "role": "tool", "tool_call_id": "tc1", "tool_name": "fs_read",
     "tool_state": "success", "content_blocks": [{"type": "text", "text": "结果正文"}]},
]

_MEM = {"identity_key": "m1", "content": "历史记忆", "memory_type": "semantic",
        "category": "general", "origin": "owner", "importance": 60.0,
        "ts": "2026-05-01T10:00:00+00:00"}

_DROPPED = [{"field": "blocks:data", "count": 1, "reason": "media 未落地"}]


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path, _ROWS, [_MEM])


def _write_bundle(tmp_path: Path, rows, memories=(), *, counts=None, dropped=()) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "test", "version": "1"},
        "counts": counts or {"transcripts": len(rows), "memories": len(memories),
                             "relations": 0},
        "dropped": list(dropped), "stores": []}, ensure_ascii=False), encoding="utf-8")
    (root / "transcripts.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    (root / "memories.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in memories), encoding="utf-8")
    return root


@pytest.fixture()
def manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


@pytest.fixture()
def sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def _stored_messages(sessions: SessionManager, agent_id: str, session_id: str) -> List[dict]:
    path = sessions._get_session_file(agent_id, session_id, "2026-05-01")
    data = sessions._read_session_file(path) or {}
    return data.get("messages", [])


def test_plan_is_read_only(manager, sessions, bundle, tmp_path: Path):
    plan = plan_bundle(bundle)

    assert plan.counts == {"transcripts": 4, "memories": 1}
    assert plan.turn_messages == 2               # 4 条事件装配成 2 条轮形消息
    assert plan.agent_name == "imported"
    assert manager._memories == {}
    # 会话根目录由 SessionManager 自身建，只读的要害是不产出任何会话文件
    assert not list((tmp_path / "sessions").glob("**/session_*.json"))


def test_apply_writes_both_throats(manager, sessions, bundle):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    assert (report.memories_added, report.memories_skipped) == (1, 0)
    assert (report.messages_added, report.messages_skipped) == (2, 0)
    assert report.sessions_touched == 1
    assert any(m.content == "历史记忆" for m in manager._memories.values())


def test_apply_writes_turn_shaped_messages(manager, sessions, bundle):
    """写进会话文件的必须是运行期那条形：一条 assistant 消息带整串工具调用与结果。"""
    apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    stored = _stored_messages(sessions, "default", "sA")
    assert [m["role"] for m in stored] == ["user", "assistant"]
    turn = stored[1]
    assert turn["content"] == "先读文件"
    assert turn["metadata"]["reasoning_content"] == "在想"
    entries = turn["metadata"]["tool_calls"]
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    assert entries[0]["params"] == {"path": "A.md"}
    assert entries[1]["result"] == "结果正文"


def test_apply_twice_is_idempotent(manager, sessions, bundle):
    first = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    second = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)

    assert (first.memories_added, first.messages_added) == (1, 2)
    assert (second.memories_added, second.memories_skipped) == (0, 1)
    assert (second.messages_added, second.messages_skipped) == (0, 2)


def test_undo_removes_exactly_the_batch(manager, sessions, bundle):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    manager.remember(content="运行期记忆", category="general")

    mem_removed, msg_removed = report.undo(manager=manager, sessions=sessions)

    assert (mem_removed, msg_removed) == (1, 2)
    assert [m.content for m in manager._memories.values()] == ["运行期记忆"]


def test_report_carries_loss_declarations(manager, sessions, tmp_path: Path):
    root = _write_bundle(tmp_path, _ROWS, [], dropped=_DROPPED)

    plan = plan_bundle(root)
    report = apply_bundle(root, agent_id="default", manager=manager, sessions=sessions)

    assert plan.dropped == tuple(_DROPPED)
    assert report.dropped == tuple(_DROPPED)


def test_invalid_bundle_is_rejected_wholesale(manager, sessions, tmp_path: Path):
    broken = _write_bundle(tmp_path, _ROWS, [], counts={"transcripts": 99, "memories": 0,
                                                        "relations": 0})

    with pytest.raises(BundleError, match="计数不符"):
        plan_bundle(broken)
    assert manager._memories == {}


def test_unknown_field_in_record_is_rejected(manager, sessions, tmp_path: Path):
    """拼错的字段名不能被静默忽略：整包拒绝，否则那条数据的语义已经不可知。"""
    rows = [dict(_ROWS[0], dreaming="?")]
    root = _write_bundle(tmp_path, rows, [])

    with pytest.raises(BundleError, match="transcripts.jsonl"):
        apply_bundle(root, agent_id="default", manager=manager, sessions=sessions)


def test_oversized_bundle_is_refused(manager, sessions, bundle, monkeypatch):
    monkeypatch.setattr("neurova.memory_ingest.intake.MAX_RECORDS", 3)

    with pytest.raises(BundleError, match="超上限"):
        apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)


def test_session_write_failure_tells_how_to_undo(manager, sessions, bundle, monkeypatch):
    """半途失败不能留悬批：报错必须给出撤销路径，已落的记忆才收得回。"""
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sessions, "import_session_messages", boom)

    with pytest.raises(BundleError, match="undo"):
        apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    assert any(m.content == "历史记忆" for m in manager._memories.values())


def test_apply_stages_media_into_the_agent_workspace(manager, sessions, tmp_path: Path):
    """媒体不能停在临时暂存目录里：apply 要把它落到工作区，消息里给可寻址的引用。"""
    import base64
    from neurova.core.agent_workspaces import get_agent_workspace_dir
    from neurova.memory_ingest.bundle.media import MediaSink

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    bundle_dir = tmp_path / "bundle"
    ref = dict(MediaSink(bundle_dir, name_hint="shot.png").put(png), type="image")
    root = _write_bundle(tmp_path, [dict(_ROWS[0], content_blocks=[
        {"type": "text", "text": "看图"}, ref])])

    apply_bundle(root, agent_id="media-agent", manager=manager, sessions=sessions)

    staged = get_agent_workspace_dir("media-agent") / "media"
    files = sorted(p.name for p in staged.glob("*"))
    assert len(files) == 1 and files[0].endswith(".png")
    assert (staged / files[0]).read_bytes() == png
    turn = _stored_messages(sessions, "media-agent", "sA")
    entry = turn[0]["metadata"]["artifacts"][0]
    assert entry["name"] == files[0] and entry["size"] == len(png)
    assert entry["artifact_id"] and entry["mime_type"] == "image/png"
    assert "media" not in turn[0]["metadata"]


def test_apply_refuses_bundle_with_dangling_media_reference(manager, sessions, tmp_path: Path):
    """引用指向包外或不存在的文件时整包拒绝——摘要引用不做成任意文件读。"""
    root = _write_bundle(tmp_path, [dict(_ROWS[0], content_blocks=[
        {"type": "text", "text": "看图"},
        {"type": "image", "media": "../../outside.png", "digest": "x" * 32, "bytes": 4}])])

    with pytest.raises(BundleError, match="越出包外"):
        apply_bundle(root, agent_id="media-agent", manager=manager, sessions=sessions)
    assert manager._memories == {}


def test_undo_removes_media_no_longer_referenced(tmp_path: Path, manager, sessions):
    """撤销不能把媒体文件留在盘上：这次导入落的，没人引用了就该一起走。"""
    import base64
    from neurova.core.agent_workspaces import get_agent_workspace_dir
    from neurova.memory_ingest.bundle.media import MediaSink

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    bundle_dir = tmp_path / "bundle"
    ref = dict(MediaSink(bundle_dir, name_hint="shot.png").put(png), type="image")
    root = _write_bundle(tmp_path, [dict(_ROWS[0], content_blocks=[
        {"type": "text", "text": "看图"}, ref])])

    report = apply_bundle(root, agent_id="media-agent", manager=manager, sessions=sessions)
    staged = get_agent_workspace_dir("media-agent") / "media"
    assert len(report.staged_media) == 1 and list(staged.glob("*"))

    removed = report.undo(manager=manager, sessions=sessions)

    assert removed[1] == 1 and list(staged.glob("*")) == []


def test_undo_keeps_media_still_referenced_by_other_runs(tmp_path: Path, manager, sessions):
    """同一份内容被两批导入共用时，撤销一批不能把另一批还引用的文件删掉。"""
    import base64
    from neurova.core.agent_workspaces import get_agent_workspace_dir
    from neurova.memory_ingest.bundle.media import MediaSink

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    bundle_dir = tmp_path / "bundle"
    ref = dict(MediaSink(bundle_dir, name_hint="shot.png").put(png), type="image")
    root = _write_bundle(tmp_path, [dict(_ROWS[0], content_blocks=[
        {"type": "text", "text": "看图"}, ref])])
    first = apply_bundle(root, agent_id="media-agent", manager=manager, sessions=sessions,
                         run_id="run-a")
    second = apply_bundle(root, agent_id="media-agent", manager=manager, sessions=sessions,
                          run_id="run-b")
    staged = get_agent_workspace_dir("media-agent") / "media"

    # 第二批因 identity_key 重复被跳过：文件仍是第一批的引用目标，撤销第一批才该删
    assert second.messages_skipped == 1 and len(first.staged_media) == 1
    first.undo(manager=manager, sessions=sessions)

    assert list(staged.glob("*")) == []            # 两条都被删了，文件自然无人引用(manager, sessions, bundle, tmp_path):
    with pytest.raises(BundleError, match="agent_id"):
        apply_bundle(bundle, agent_id="../escape", manager=manager, sessions=sessions)

    assert manager._memories == {}
    assert not list(tmp_path.glob("**/session_*.json"))


class _SessionsWith:
    def __init__(self, files):
        self._files = files

    def iter_session_files(self, agent_id):
        return list(self._files)


def test_undo_prunes_even_when_name_appears_in_body(tmp_path: Path, monkeypatch):
    """文件名只在正文里出现过一次，不算"仍被引用"：子串匹配会把它永久留住。"""
    from neurova.memory_ingest import intake

    digest = "a" * 32
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / f"{digest}.png").write_bytes(b"PNG")
    session = tmp_path / "session_sA_2026-05-01.json"
    session.write_text(json.dumps({"messages": [
        {"role": "user", "content": f"我贴了 {digest}.png 但没注册产物",
         "metadata": {"ingest_run_id": "other-run"}}]}), encoding="utf-8")
    monkeypatch.setattr(intake, "workspace_media_dir",
                        lambda agent_id, create=True: media_dir)

    removed = intake._prune_media("audit", {f"{digest}.png"}, _SessionsWith([session]))

    assert removed == 1 and not (media_dir / f"{digest}.png").exists()


class _Recorder:
    """替身只记调用，不碰任何 store：本用例要证的就是"根本没被叫到"。"""

    def __init__(self):
        self.calls = []

    def import_memories(self, records, *, ingest_run_id):
        self.calls.append(("memories", len(records)))
        return len(records), 0

    def import_session_messages(self, agent_id, session_id, date, batch, *, ingest_run_id):
        self.calls.append(("messages", len(batch)))
        return len(batch), 0

    def iter_session_files(self, agent_id):
        return []


def _bundle_with_one_record(root: Path, kind: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-21T00:00:00+00:00",
        "agent_name": "audit", "source": {"converter": "audit", "version": "1"},
        "counts": {"transcripts": 1, "memories": 0, "relations": 0},
        "dropped": [], "stores": []}), encoding="utf-8")
    (root / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": kind, "role": "user",
        "ts": "2026-05-01T10:00:00+00:00", "identity_key": "sA#1",
        "content_blocks": [{"type": "text", "text": "hi"}]}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return root


def test_unknown_kind_is_rejected_before_any_write(tmp_path: Path):
    """包里有非法 kind：既要以 BundleError 拒绝，也不能留下"记忆已写、会话没写"的半批。"""
    recorder = _Recorder()
    root = _bundle_with_one_record(tmp_path / "bundle", "totally_unknown_kind")

    with pytest.raises(BundleError):
        apply_bundle(root, agent_id="audit", manager=recorder, sessions=recorder)

    assert recorder.calls == []
