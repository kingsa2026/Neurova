# -*- coding: utf-8 -*-
"""包内 media：内容寻址落盘 + 路径与摘要校验。

源里的图片/文件块有两种形态：base64 正文，或指向源机器命名空间的绝对路径
（实测每日对话记的是 /agents/Kai/workspace/media/xxx，本机在源目录下确有同名文件）。
落进包时统一成 media/<摘要>.<ext>，读回时路径必须仍在包内——引用型包最容易被
"../" 做出一个任意文件读。
"""
import base64
import hashlib
import json
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.media import (
 MAX_MEDIA_BYTES, MediaSink, resolve_payload, verify_media)
from neurova.memory_ingest.bundle.validate import validate_bundle

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg==")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    """伪造一目录结构：源在 …/workspace/dialog，媒体在 …/workspace/media。"""
    dialog = tmp_path / "workspace" / "dialog"
    dialog.mkdir(parents=True)
    (tmp_path / "workspace" / "media").mkdir()
    (tmp_path / "workspace" / "media" / "shot.png").write_bytes(PNG)
    src = dialog / "2026-04-07.jsonl"
    src.write_text("{}\n", encoding="utf-8")
    return src


def test_sink_writes_content_addressed_file_and_reference(tmp_path: Path):
    out = tmp_path / "bundle"
    sink = MediaSink(out, name_hint="shot.png")

    ref = sink.put(PNG)

    assert ref["media"] == f"media/{_digest(PNG)}.png"
    assert (out / ref["media"]).read_bytes() == PNG
    assert ref["bytes"] == len(PNG) and ref["digest"] == _digest(PNG)
    assert ref["mime"] == "image/png"


def test_same_bytes_written_once(tmp_path: Path):
    out = tmp_path / "bundle"
    sink = MediaSink(out, name_hint="a.png")

    first, second = sink.put(PNG), sink.put(PNG)

    assert first["media"] == second["media"]
    assert len(list((out / "media").iterdir())) == 1


def test_oversize_payload_is_refused_not_written(tmp_path: Path):
    sink = MediaSink(tmp_path / "bundle", name_hint="big.bin")

    assert sink.put(b"x" * (MAX_MEDIA_BYTES + 1)) is None


def test_path_payload_resolved_inside_source_tree(store: Path, tmp_path: Path):
    """源里是别的机器的绝对路径：按名在源目录树里找，找不到就报不可达。"""
    found = resolve_payload("/agents/Kai/workspace/media/shot.png", store)
    missing = resolve_payload("/agents/Kai/workspace/media/nope.png", store)

    assert found is not None and found[0] == PNG and found[1] == "shot.png"
    assert missing is None


def test_path_payload_cannot_escape_source_tree(store: Path):
    secret = store.parents[2] / "secret.txt"
    secret.write_text("私密", encoding="utf-8")

    assert resolve_payload(f"/anywhere/../../{secret.name}", store) is None


def test_base64_payload_decodes_with_name(store: Path):
    block = {"type": "data", "name": "shot.png",
             "source": {"type": "base64", "data": base64.b64encode(PNG).decode()}}

    resolved = resolve_payload(block, store)

    assert resolved == (PNG, "shot.png")


def test_broken_base64_is_reported_as_missing(store: Path):
    assert resolve_payload({"type": "data", "name": "x.png",
                            "source": {"type": "base64", "data": "@@@"}}, store) is None


def test_inline_base64_block_without_source_key(store: Path):
    """有的落盘把正文直接挂在块的 data 上（配 mimeType），不套一层 source——不能判成不可达。"""
    block = {"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"}

    resolved = resolve_payload(block, store)
    ref = MediaSink(store.parent.parent / "bundle").put(resolved[0], name=resolved[1])

    assert resolved is not None and resolved[0] == PNG
    assert ref["media"] == f"media/{_digest(PNG)}.png" and ref["mime"] == "image/png"


def test_verify_media_accepts_a_consistent_bundle(tmp_path: Path):
    out = tmp_path / "bundle"
    ref = MediaSink(out, name_hint="shot.png").put(PNG)
    _write_bundle_with_ref(out, ref)

    assert verify_media(out) == [] and validate_bundle(out) == []


def test_verify_media_rejects_traversal_reference(tmp_path: Path):
    out = tmp_path / "bundle"
    _write_bundle_with_ref(out, {"type": "image", "media": "../../outside.png",
                                 "digest": _digest(PNG), "bytes": len(PNG)})

    errors = verify_media(out)

    assert errors and "包外" in errors[0]


def test_verify_media_rejects_digest_mismatch(tmp_path: Path):
    out = tmp_path / "bundle"
    ref = MediaSink(out, name_hint="shot.png").put(PNG)
    (out / ref["media"]).write_bytes(b"tampered-bytes")
    _write_bundle_with_ref(out, ref)

    assert any("摘要不符" in error for error in verify_media(out))


def test_verify_media_rejects_missing_file(tmp_path: Path):
    out = tmp_path / "bundle"
    _write_bundle_with_ref(out, {"type": "image", "media": f"media/{_digest(PNG)}.png",
                                 "digest": _digest(PNG), "bytes": 4})

    assert any("缺文件" in error for error in verify_media(out))


def test_validate_bundle_also_guards_media_references(tmp_path: Path):
    """引用型包最容易被 "../" 做成任意文件读——整包校验必须把它管住。"""
    out = tmp_path / "bundle"
    _write_bundle_with_ref(out, {"type": "image", "media": "../../outside.png",
                                 "digest": _digest(PNG), "bytes": len(PNG)})

    errors = validate_bundle(out)

    assert errors and any("越出包外" in error for error in errors)


def _bundle_refs(out: Path, *refs: dict) -> Path:
    """同一条消息上挂多个媒体引用——命名闸只在多引用时才可能露馅。"""
    out.mkdir(parents=True, exist_ok=True)
    _write_bundle_with_ref(out, refs[0])
    (out / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": "user_message",
        "ts": "2026-05-01T10:00:00+08:00", "identity_key": "sA#1", "role": "user",
        "content_blocks": [{"type": "text", "text": "看图"}, *refs]},
        ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def test_media_reference_must_follow_content_addressed_naming(tmp_path: Path):
    """文件名即摘要：允许 media/a/pic.png 与 media/b/pic.png 并存，落盘就会被拍平成一份。"""
    out = _bundle_refs(tmp_path / "bundle",
                       {"type": "image", "media": "media/a/pic.png", "digest": "0" * 32},
                       {"type": "image", "media": "media/b/pic.png", "digest": "1" * 32})
    (out / "media" / "a").mkdir(parents=True)
    (out / "media" / "b").mkdir(parents=True)
    (out / "media" / "a" / "pic.png").write_bytes(b"PNG-A")
    (out / "media" / "b" / "pic.png").write_bytes(b"PNG-B")

    assert any("命名不符内容寻址约定" in e for e in validate_bundle(out))


def test_media_reference_without_digest_is_rejected(tmp_path: Path):
    """没声明摘要就无法证明"引用与字节是一对"——第三方可拿它塞任意文件。"""
    digest = _digest(PNG)
    out = _bundle_refs(tmp_path / "bundle",
                       {"type": "image", "media": f"media/{digest}.png"})
    (out / "media").mkdir(parents=True, exist_ok=True)
    (out / "media" / f"{digest}.png").write_bytes(PNG)

    assert any("摘要必须声明" in e for e in validate_bundle(out))


def test_sink_produced_reference_still_passes(tmp_path: Path):
    """自家 MediaSink 的产物必须在新闸下依然合法——否则闸写错了。"""
    out = tmp_path / "bundle"
    ref = MediaSink(out, name_hint="shot.png").put(PNG)

    assert validate_bundle(_bundle_refs(out, ref)) == []


def _write_bundle_with_ref(out: Path, ref: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": "user_message",
        "ts": "2026-05-01T10:00:00+08:00", "identity_key": "sA#1", "role": "user",
        "content_blocks": [{"type": "text", "text": "看图"}, ref]}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out / "memories.jsonl").write_text("", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "t", "version": "1"},
        "counts": {"transcripts": 1, "memories": 0, "relations": 0},
        "dropped": [], "stores": []}, ensure_ascii=False), encoding="utf-8")
