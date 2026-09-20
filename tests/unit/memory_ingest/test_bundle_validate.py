# -*- coding: utf-8 -*-
"""整包校验器：任一不合契约即由调用方拒绝整支 store，绝不半导（设计 §5 漂移守卫）。"""
import json
from pathlib import Path

from neurova.memory_ingest.bundle.validate import validate_bundle

MANIFEST = {
    "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
    "agent_name": "imported", "source": {"converter": "x", "version": "1"},
    "counts": {"transcripts": 2, "memories": 1, "relations": 0},
    "dropped": [], "stores": [],
}
T1 = {"session_id": "s1", "seq": 1, "kind": "user_message",
      "ts": "2026-05-01T10:00:00+00:00", "identity_key": "a"}
T2 = {"session_id": "s1", "seq": 2, "kind": "tool_result",
      "ts": "2026-05-01T10:00:01+00:00", "identity_key": "b", "tool_call_id": "tc1"}
M1 = {"identity_key": "m1", "content": "c", "memory_type": "semantic", "category": "general",
      "origin": "owner", "importance": 50.0, "ts": "2026-05-01T10:00:00+00:00"}


def _bundle(tmp_path: Path, *, transcripts=None, memories=None, manifest=None) -> Path:
    if manifest is not None:
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (tmp_path / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    if transcripts is not None:
        (tmp_path / "transcripts.jsonl").write_text(
            "\n".join(json.dumps(x) for x in transcripts), encoding="utf-8")
    if memories is not None:
        (tmp_path / "memories.jsonl").write_text(
            "\n".join(json.dumps(x) for x in memories), encoding="utf-8")
    return tmp_path


def test_valid_bundle_passes(tmp_path: Path):
    assert validate_bundle(_bundle(tmp_path, transcripts=[T1, T2], memories=[M1])) == []


def test_missing_manifest_reported(tmp_path: Path):
    assert any("manifest" in e for e in validate_bundle(tmp_path))


def test_unsupported_schema_version_reported(tmp_path: Path):
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, T2], memories=[M1],
                                     manifest=dict(MANIFEST, schema_version=7)))
    assert any("schema_version" in e for e in errors)


def test_counts_must_match_actual_lines(tmp_path: Path):
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1], memories=[M1]))

    assert any("transcripts.jsonl" in e and "计数不符" in e for e in errors)


def test_required_fields_reported(tmp_path: Path):
    broken = {k: v for k, v in T2.items() if k != "identity_key"}

    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, broken], memories=[M1]))

    assert any("transcripts.jsonl 缺字段" in e and "identity_key" in e for e in errors)


def test_seq_gap_or_duplicate_rejected(tmp_path: Path):
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, dict(T2, seq=9)], memories=[M1]))
    assert any("seq" in e for e in errors)

    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, dict(T2, seq=1)], memories=[M1]))
    assert any("seq" in e for e in errors)


def test_duplicate_identity_key_rejected(tmp_path: Path):
    errors = validate_bundle(
        _bundle(tmp_path, transcripts=[T1, dict(T2, identity_key="a")], memories=[M1]))

    assert any("identity_key 重复" in e for e in errors)


def test_origin_outside_closed_set_rejected(tmp_path: Path):
    errors = validate_bundle(
        _bundle(tmp_path, transcripts=[T1, T2], memories=[dict(M1, origin="superuser")]))

    assert any("origin 越界" in e for e in errors)


def test_missing_jsonl_with_nonzero_counts_rejected(tmp_path: Path):
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, T2]))

    assert any("memories.jsonl 缺失" in e for e in errors)


def test_broken_json_line_reported_with_lineno(tmp_path: Path):
    root = _bundle(tmp_path, transcripts=[T1, T2], memories=[M1])
    (root / "transcripts.jsonl").write_text(
        json.dumps(T1) + "\n{oops\n" + json.dumps(T2), encoding="utf-8")

    errors = validate_bundle(root)

    assert any("transcripts.jsonl:2" in e for e in errors)


def test_ts_without_offset_is_rejected(tmp_path: Path):
    """ts 是包内唯一可靠的排序与分桶依据：裸时间一律整包拒绝，不猜时区。"""
    root = tmp_path / 'bundle'
    root.mkdir()
    (root / 'manifest.json').write_text(json.dumps({
        'schema_version': 1, 'generated_at': '2026-09-20T00:00:00+00:00',
        'agent_name': 'x', 'source': {}, 'counts': {'transcripts': 1, 'memories': 0,
        'relations': 0}}), encoding='utf-8')
    (root / 'transcripts.jsonl').write_text(json.dumps({
        'session_id': 'sA', 'seq': 1, 'kind': 'user_message', 'ts': '2026-05-01T10:00:00',
        'identity_key': 'sA#1'}), encoding='utf-8')
    (root / 'memories.jsonl').write_text('', encoding='utf-8')

    errors = validate_bundle(root)

    assert any('缺时区' in e for e in errors)


def test_ts_with_z_suffix_is_accepted(tmp_path: Path):
    root = tmp_path / 'bundle2'
    root.mkdir()
    (root / 'manifest.json').write_text(json.dumps({
        'schema_version': 1, 'generated_at': '2026-09-20T00:00:00+00:00',
        'agent_name': 'x', 'source': {}, 'counts': {'transcripts': 1, 'memories': 0,
        'relations': 0}}), encoding='utf-8')
    (root / 'transcripts.jsonl').write_text(json.dumps({
        'session_id': 'sA', 'seq': 1, 'kind': 'user_message', 'ts': '2026-05-01T10:00:00Z',
        'identity_key': 'sA#1'}), encoding='utf-8')
    (root / 'memories.jsonl').write_text('', encoding='utf-8')

    assert validate_bundle(root) == []
