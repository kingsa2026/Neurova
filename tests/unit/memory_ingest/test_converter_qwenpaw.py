# -*- coding: utf-8 -*-
"""QwenPaw 会话族转换器：只产包、不写库。

现脚本对 conversation_history 是字段级有损的（实测 15 列只 SELECT 9 列），本转换器的验收
标准是把 headline / tool_state / agent_id / tool_input / metadata 补回；凡是契约与 extra
都接不住的东西（未知列、未知 kind、未知块型）必须进 manifest.dropped 申报——静默降级是
市面互导实现共同的病灶。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters import CONVERTERS
from neurova.memory_ingest.converters.qwenpaw_history import CONVERTER_NAME, convert

COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
        "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


def _row(**kw):
    base = {c: None for c in COLS}
    base.update(kw)
    return tuple(base[c] for c in COLS)


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    """源 kind 用真实词表（context_msg / model_turn / tool_result），不是包内规范名。"""
    db = tmp_path / "history.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.executemany(
        f"INSERT INTO conversation_history VALUES ({','.join('?' * len(COLS))})",
        [
            _row(seq=1, session_id="sA", agent_id="凯", kind="context_msg", role="user",
                 name="用户", content="问题", created_at="2026-05-01T10:00:01", dedup_key="k1"),
            _row(seq=2, session_id="sA", agent_id="凯", kind="model_turn", role="assistant",
                 name="凯", content="先读文件", headline="要点",
                 blocks=json.dumps([{"type": "thinking", "thinking": "想一想"}]),
                 created_at="2026-05-01T10:00:02", dedup_key="k2"),
            _row(seq=3, session_id="sA", agent_id="凯", kind="tool_result", role="tool",
                 name="fs_read", content="结果", tool_call_id="tc1", tool_state="ok",
                 created_at="2026-05-01T10:00:03", dedup_key="k3"),
            _row(seq=4, session_id="sA", agent_id="凯", kind="model_turn", role="assistant",
                 name="fs_read", tool_call_id="tc9",
                 tool_input=json.dumps({"path": "config"}),
                 created_at="2026-05-01T10:00:04", dedup_key="k4"),
            _row(seq=5, session_id="sB", agent_id="凯", kind="context_msg", role="user",
                 name="用户", content="另一会话", created_at="2026-05-01T11:00:01",
                 dedup_key="k5"),
        ])
    conn.commit()
    conn.close()
    return db


def _records(out: Path):
    lines = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    return {f"{r['session_id']}:{r['seq']}": r for r in lines}


def test_convert_produces_valid_bundle(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"

    convert(src, out, agent_name="imported")

    assert validate_bundle(out) == []


def test_convert_keeps_fields_the_old_script_dropped(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert by_key["sA:2"]["extra"]["headline"] == "要点"
    assert by_key["sA:3"]["tool_state"] == "ok"
    assert by_key["sA:1"]["extra"]["agent_id"] == "凯"
    assert by_key["sA:4"]["extra"]["tool_input"] == json.dumps({"path": "config"})


def test_convert_normalizes_source_kinds(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert [by_key[f"sA:{n}"]["kind"] for n in (1, 2, 3, 4)] == [
        "user_message", "assistant_message", "tool_result", "tool_call"]


def test_convert_renumbers_seq_per_session_and_keeps_source_seq(tmp_path: Path, src: Path):
    """包内 seq 是会话内 1..n（校验器要求）；源全局 seq 进 extra 不丢。"""
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")
    by_key = _records(out)

    assert by_key["sB:1"]["seq"] == 1
    assert by_key["sB:1"]["extra"]["source_seq"] == 5


def test_convert_keeps_reasoning_as_text(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported")

    assistant = _records(out)["sA:2"]
    assert assistant["reasoning_state"] == "text"
    assert assistant["reasoning_text"] == "想一想"


def test_convert_reports_no_loss_for_this_source(tmp_path: Path, src: Path):
    """这支转换器把每列都放进了契约或 extra，因此"无损"是可验证的承诺。"""
    out = tmp_path / "bundle"
    manifest = convert(src, out, agent_name="imported")

    assert manifest.dropped == ()
    assert manifest.counts == {"transcripts": 5, "memories": 0, "relations": 0}


def test_convert_declares_unmapped_columns(tmp_path: Path, src: Path):
    """源里出现契约与 extra 都接不住的列时，必须申报条数而不是丢掉。"""
    conn = sqlite3.connect(src)
    conn.execute("ALTER TABLE conversation_history ADD COLUMN dream_state TEXT")
    conn.execute("UPDATE conversation_history SET dream_state = 'active'")
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert any(entry["field"] == "dream_state" and entry["count"] == 5
               and entry["reason"] for entry in manifest.dropped)


def test_convert_declares_unknown_kind_rows(tmp_path: Path, src: Path):
    """认不出的 kind 不猜映射：整行不入包，但必须在申报里数得出来。"""
    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO conversation_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        _row(seq=6, session_id="sA", kind="dream_turn", role="assistant", content="?",
             created_at="2026-05-01T10:00:05", dedup_key="k6"))
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert any(entry["field"] == "kind:dream_turn" and entry["count"] == 1
               for entry in manifest.dropped)
    assert manifest.counts["transcripts"] == 5
    assert validate_bundle(out) == []


def test_convert_stamps_explicit_offset_on_naive_source_time(tmp_path: Path, src: Path):
    """源里是本地墙钟裸时间：包内必须带上偏移，否则读侧连 fromisoformat 都过不去。"""
    out = tmp_path / 'bundle'

    convert(src, out, agent_name='imported')

    assert _records(out)['sA:1']['ts'] == '2026-05-01T10:00:01+08:00'


def test_convert_is_read_only_on_source(tmp_path: Path, src: Path):
    before = src.read_bytes()

    convert(src, tmp_path / "bundle", agent_name="imported")

    assert src.read_bytes() == before


def test_convert_rejects_store_that_does_not_match_its_fingerprint(tmp_path: Path):
    """转换器必须自证来源：指纹不符就拒，不靠调用方保证路由正确。"""
    conn = sqlite3.connect(tmp_path / "other.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(BundleError):
        convert(tmp_path / "other.db", tmp_path / "bundle", agent_name="imported")


def test_convert_declares_block_types_the_contract_cannot_carry(tmp_path: Path, src: Path):
    """reasoning_text 只装得下思考；audio 这类块型接不住就必须申报，不能默默扔掉。"""
    conn = sqlite3.connect(src)
    conn.execute(
        "UPDATE conversation_history SET blocks = ? WHERE seq = 2",
        (json.dumps([{"type": "thinking", "thinking": "想一想"},
                     {"type": "audio", "url": "file:///tmp/a.mp3"}]),))
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert any(entry["field"] == "blocks:audio" and entry["count"] == 1
               and entry["reason"] for entry in manifest.dropped)
    assert _records(out)["sA:2"]["reasoning_text"] == "想一想"


def test_convert_carries_base64_block_as_media(tmp_path: Path, src: Path):
    """贴图块的正文是 base64：落进包内 media/，不再只是申报一条丢失。"""
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    conn = sqlite3.connect(src)
    conn.execute("UPDATE conversation_history SET blocks = ? WHERE seq = 2",
                 (json.dumps([{"type": "thinking", "thinking": "想一想"},
                              {"type": "data", "name": "shot.png",
                               "source": {"type": "base64",
                                          "data": base64.b64encode(png).decode()}}]),))
    conn.commit()
    conn.close()
    out = tmp_path / "bundle"

    manifest = convert(src, out, agent_name="imported")

    assert manifest.dropped == ()
    blocks = _records(out)["sA:2"]["content_blocks"]
    assert blocks[1]["type"] == "image" and blocks[1]["mime"] == "image/png"
    assert (out / blocks[1]["media"]).read_bytes() == png


def test_converter_is_routable_by_its_own_handprint_name():
    """指纹名必须查到转换器，否则 detect 报"唯一命中"而 apply 无路可走。"""
    assert CONVERTERS[CONVERTER_NAME] is convert


# --- 一轮多调用：实测源里 model_turn 的 blocks 最多含 6 个 tool_call，
#     平列 tool_call_id/tool_input 只留最后一个（现脚本因此只导回 21/179 个调用）


def _convert(tmp_path: Path, name: str, rows):
    db = tmp_path / name
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.executemany(
        f"INSERT INTO conversation_history VALUES ({','.join('?' * len(COLS))})", rows)
    conn.commit()
    conn.close()
    out = tmp_path / f"bundle-{name}"
    return convert(db, out, agent_name="imported"), out


def _call(call_id, tool_name, args, state="finished"):
    return {"type": "tool_call", "id": call_id, "name": tool_name, "state": state,
            "input": json.dumps(args, ensure_ascii=False)}


def test_convert_expands_every_tool_call_block(tmp_path: Path):
    """一轮里的每个调用都要成一条记录：平列只有一份，按平列转就丢调用。"""
    blocks = [{"type": "thinking", "thinking": "先看看"},
              {"type": "text", "text": "我来读两个文件"},
              _call("tc1", "read_file", {"file_path": "A.md"}),
              _call("tc2", "glob_search", {"pattern": "*.md"})]
    rows = [_row(seq=1, session_id="sX", kind="model_turn", role="assistant", name="glob_search",
                 content="我来读两个文件", tool_call_id="tc2",
                 tool_input=json.dumps({"pattern": "*.md"}, ensure_ascii=False),
                 blocks=json.dumps(blocks, ensure_ascii=False),
                 created_at="2026-05-01T10:00:00", dedup_key="kx")]

    manifest, out = _convert(tmp_path, "multi.db", rows)
    records = list(_records(out).values())

    assert manifest.counts["transcripts"] == 3
    calls = [r for r in records if r["kind"] == "tool_call"]
    assert [c["tool_call_id"] for c in calls] == ["tc1", "tc2"]
    assert [c["tool_name"] for c in calls] == ["read_file", "glob_search"]
    assert [c["tool_state"] for c in calls] == ["finished", "finished"]
    assert json.loads(calls[0]["extra"]["tool_input"]) == {"file_path": "A.md"}


def test_convert_keeps_text_and_call_order(tmp_path: Path):
    """正文与调用的先后顺序是轮内语义，展开后仍按源块序排。"""
    blocks = [{"type": "text", "text": "先说话"}, _call("tc1", "t", {}),
              {"type": "text", "text": "后说话"}]
    rows = [_row(seq=1, session_id="sX", kind="model_turn", role="assistant",
                 content="先说话后说话", blocks=json.dumps(blocks, ensure_ascii=False),
                 created_at="2026-05-01T10:00:00", dedup_key="kx")]

    _, out = _convert(tmp_path, "order.db", rows)
    by_key = _records(out)

    assert [by_key[f"sX:{n}"]["kind"] for n in (1, 2, 3)] == [
        "assistant_message", "tool_call", "assistant_message"]
    assert by_key["sX:1"]["content_blocks"][0]["text"] == "先说话"
    assert by_key["sX:3"]["content_blocks"][0]["text"] == "后说话"


def test_identity_keys_stay_unique_within_one_source_row(tmp_path: Path):
    """identity_key 是幂等键：一行展开成多条时必须各自可寻址，否则二次导入互相吞。"""
    blocks = [_call("tc1", "t", {}), _call("tc2", "t", {})]
    rows = [_row(seq=1, session_id="sX", kind="model_turn", role="assistant",
                 blocks=json.dumps(blocks), created_at="2026-05-01T10:00:00",
                 dedup_key="kx")]

    _, out = _convert(tmp_path, "idem.db", rows)
    keys = [r["identity_key"] for r in _records(out).values()]

    assert len(keys) == 2 and len(set(keys)) == 2
    assert validate_bundle(out) == []


def test_convert_declares_binary_blocks(tmp_path: Path):
    """解不出字节的媒体块必须申报，不能塞进会话文件也不能默默扔。"""
    rows = [_row(seq=1, session_id="sX", kind="context_msg", role="user", content="看图",
                 blocks=json.dumps([{"type": "text", "text": "看图"},
                                    {"type": "data", "name": "shot.png",
                                     "source": {"type": "base64", "data": "iVBORw0KGgo"}}]),
                 created_at="2026-05-01T10:00:00", dedup_key="kx")]

    manifest, out = _convert(tmp_path, "binary.db", rows)

    assert any(entry["field"] == "media:不可达" and entry["count"] == 1
               and "media" in entry["reason"] for entry in manifest.dropped)
    assert manifest.counts["transcripts"] == 1
