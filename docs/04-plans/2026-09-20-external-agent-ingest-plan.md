# 外部 Agent 导入（Ingest Bundle）第一轮实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `neurova/memory_ingest/`：一个只认中立 Ingest Bundle 的导入子系统，能识别来源 store、路由转换器、显式确认后写入记忆与会话两个咽喉入口，并可按批次撤销。

**Architecture:** 转换器只产包、不写库；`intake` 是唯一写入口，把包里的记录分派给 `MemoryManager.import_memories()` 与 `SessionManager.import_session_messages()`（本轮新增的两个导入专用入口，不触发运行期副作用）。识别以 store 为单位做结构断言（表列集 / JSONL 首行键集），三态结论：唯一命中、冲突、未识别。

**Tech Stack:** Python 3.12、sqlite3（只读 URI）、dataclasses、Click 风格的 argparse CLI、pytest。

**Spec:** `docs/specs/2026-09-20-external-agent-ingest-design.md`

## Global Constraints

- 所有测试用合成夹具，**不依赖 `E:/项目/Kai` 或任何外部工程目录存在**。
- 打开外部 SQLite 一律 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`。
- `MemoryOrigin` 闭集不扩：只接受 `owner|agent|untrusted|system`，越界即拒绝该记录。
- 导入路径不触发运行期副作用：不调用内容门、`semantic_search.upsert_memory_index`、`_sync_runtime_vector_store`。
- 每次 apply 生成一个 `ingest_run_id`，写进每条落库记录的 metadata；撤销按该 id 精确删除。
- v1 包形态 = 目录（zip 属后续）；`relations.jsonl` 只登记不消费。
- 命名沿用仓库风格：函数 snake_case、类 PascalCase；不使用模糊词。
- 提交遵循 Conventional Commits；共享工作树里只提自己的 hunk（禁用 `git add -A`、`git stash`、`git reset`）。

---

### Task 1: bundle 记录类型与校验器

**Files:**
- Create: `neurova/memory_ingest/__init__.py`
- Create: `neurova/memory_ingest/bundle/__init__.py`
- Create: `neurova/memory_ingest/bundle/records.py`
- Create: `neurova/memory_ingest/bundle/manifest.py`
- Create: `neurova/memory_ingest/bundle/validate.py`
- Test: `tests/unit/memory_ingest/test_bundle_records.py`
- Test: `tests/unit/memory_ingest/test_bundle_validate.py`

**Interfaces:**
- Produces:
  - `BundleManifest(schema_version:int, generated_at:str, agent_name:str, source:dict, counts:dict, dropped:tuple, stores:tuple)`
  - `TranscriptRecord(session_id:str, seq:int, kind:str, ts:str, identity_key:str, role:str="", content_blocks:tuple=(), tool_call_id:str="", tool_name:str="", tool_state:str="", reasoning_state:str="absent", reasoning_text:str="", parent_seq:int|None=None, extra:dict={})`，方法 `to_session_message() -> dict`
    （`tool_state` 与 `extra` 是"源里有、契约无对应字段"的透传位，缺了它们 §7 的"补回被丢字段"就落空）
  - `MemoryRecord(identity_key:str, content:str, memory_type:str, category:str, origin:str, importance:float, ts:str, temperature:float=100.0, tags:tuple=(), source_ref:str="", supersedes:str="")`
  - `load_manifest(path:Path) -> BundleManifest`（缺文件/版本不符抛 `BundleError`）
  - `validate_bundle(root:Path) -> list[str]`（返回错误列表，空即通过；不抛）
  - `BundleError(Exception)`

- [ ] **Step 1: 写失败测试（记录类型 + manifest）**

```python
# tests/unit/memory_ingest/test_bundle_records.py
import json
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.manifest import BundleError, load_manifest
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord

GOOD_MANIFEST = {
    "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
    "agent_name": "imported", "source": {"converter": "x", "version": "1"},
    "counts": {"transcripts": 1, "memories": 1, "relations": 0},
    "dropped": [], "stores": [],
}


def test_load_manifest_reads_fields(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(json.dumps(GOOD_MANIFEST), encoding="utf-8")
    m = load_manifest(tmp_path / "manifest.json")
    assert m.schema_version == 1 and m.agent_name == "imported"
    assert m.counts == {"transcripts": 1, "memories": 1, "relations": 0}


def test_load_manifest_rejects_unknown_version(tmp_path: Path):
    bad = dict(GOOD_MANIFEST, schema_version=99)
    (tmp_path / "manifest.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(BundleError, match="schema_version"):
        load_manifest(tmp_path / "manifest.json")


def test_transcript_to_session_message_carries_ingest_metadata():
    rec = TranscriptRecord(
        session_id="s1", seq=3, kind="tool_result", ts="2026-05-01T10:00:00+00:00",
        identity_key="ik3", role="tool", tool_call_id="tc1", tool_name="fs_read",
        content_blocks=({"type": "text", "text": "结果正文"},),
    )
    msg = rec.to_session_message()
    assert msg["role"] == "tool" and msg["tool_call_id"] == "tc1"
    assert msg["metadata"]["ingest"]["identity_key"] == "ik3"


def test_memory_record_defaults_are_not_trusted_by_accident():
    rec = MemoryRecord(identity_key="m1", content="c", memory_type="semantic",
                       category="general", origin="owner", importance=50.0,
                       ts="2026-05-01T10:00:00+00:00")
    assert rec.temperature == 100.0 and rec.origin == "owner"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_bundle_records.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'neurova.memory_ingest'`

- [ ] **Step 3: 实现 records.py**

```python
# neurova/memory_ingest/bundle/records.py
"""Ingest Bundle 的记录类型（各家落盘方言的最大公约数，见设计 §3）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

VALID_KINDS = ("user_message", "assistant_message", "tool_call", "tool_result",
               "system", "compact_summary")
VALID_ROLE_KINDS = {
    "user_message": "user", "assistant_message": "assistant",
    "tool_call": "assistant", "tool_result": "tool",
    "system": "system", "compact_summary": "assistant",
}
VALID_REASONING = ("text", "opaque", "absent")


@dataclass(frozen=True)
class TranscriptRecord:
    session_id: str
    seq: int
    kind: str
    ts: str
    identity_key: str
    role: str = ""
    content_blocks: Tuple[Dict[str, Any], ...] = ()
    tool_call_id: str = ""
    tool_name: str = ""
    tool_state: str = ""
    reasoning_state: str = "absent"
    reasoning_text: str = ""
    parent_seq: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"未知 kind: {self.kind!r}")
        if self.reasoning_state not in VALID_REASONING:
            raise ValueError(f"未知 reasoning_state: {self.reasoning_state!r}")

    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content_blocks if b.get("type") == "text")

    def to_session_message(self) -> Dict[str, Any]:
        return {
            "role": self.role or VALID_ROLE_KINDS[self.kind],
            "content": self.text(),
            "timestamp": self.ts,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_state": self.tool_state,
            "metadata": {
                "ingest": {
                    "identity_key": self.identity_key, "seq": self.seq,
                    "kind": self.kind, "reasoning_state": self.reasoning_state,
                    "extra": dict(self.extra),
                },
                **({"reasoning_content": self.reasoning_text} if self.reasoning_text else {}),
            },
        }


@dataclass(frozen=True)
class MemoryRecord:
    identity_key: str
    content: str
    memory_type: str
    category: str
    origin: str
    importance: float
    ts: str
    temperature: float = 100.0
    tags: Tuple[str, ...] = ()
    source_ref: str = ""
    supersedes: str = ""
```

- [ ] **Step 4: 实现 manifest.py**

```python
# neurova/memory_ingest/bundle/manifest.py
"""manifest.json：版本与计数的唯一真相入口（各家无版本字段的教训，见设计 §2）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

SUPPORTED_SCHEMA_VERSION = 1


class BundleError(Exception):
    """包不合规：版本不符、缺文件、坏行、越界值。调用方必须整包拒绝。"""


@dataclass(frozen=True)
class BundleManifest:
    schema_version: int
    generated_at: str
    agent_name: str
    source: Dict[str, Any]
    counts: Dict[str, int]
    dropped: Tuple[Dict[str, Any], ...]
    stores: Tuple[Dict[str, Any], ...]


def load_manifest(path: Path) -> BundleManifest:
    if not path.exists():
        raise BundleError(f"缺 manifest.json: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise BundleError(f"schema_version 不支持: {version!r}（本版本只认 {SUPPORTED_SCHEMA_VERSION}）")
    for key in ("generated_at", "agent_name", "source", "counts"):
        if key not in raw:
            raise BundleError(f"manifest 缺字段 {key!r}")
    return BundleManifest(
        schema_version=version, generated_at=raw["generated_at"], agent_name=raw["agent_name"],
        source=dict(raw["source"]), counts=dict(raw["counts"]),
        dropped=tuple(raw.get("dropped", ())), stores=tuple(raw.get("stores", ())),
    )
```

- [ ] **Step 5: 写失败测试（校验器负例）**

```python
# tests/unit/memory_ingest/test_bundle_validate.py
import json
from pathlib import Path

from neurova.memory_ingest.bundle.validate import validate_bundle

MANIFEST = {
    "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
    "agent_name": "imported", "source": {"converter": "x", "version": "1"},
    "counts": {"transcripts": 2, "memories": 1, "relations": 0},
    "dropped": [], "stores": [],
}
T1 = {"session_id": "s1", "seq": 1, "kind": "user_message", "ts": "2026-05-01T10:00:00+00:00",
      "identity_key": "a"}
T2 = {"session_id": "s1", "seq": 2, "kind": "tool_result", "ts": "2026-05-01T10:00:01+00:00",
      "identity_key": "b", "tool_call_id": "tc1"}
M1 = {"identity_key": "m1", "content": "c", "memory_type": "semantic", "category": "general",
      "origin": "owner", "importance": 50.0, "ts": "2026-05-01T10:00:00+00:00"}


def _bundle(tmp_path: Path, *, transcripts=None, memories=None, manifest=None, extra=None):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest or MANIFEST), encoding="utf-8")
    if transcripts is not None:
        (tmp_path / "transcripts.jsonl").write_text(
            "\n".join(json.dumps(x) for x in transcripts), encoding="utf-8")
    if memories is not None:
        (tmp_path / "memories.jsonl").write_text(
            "\n".join(json.dumps(x) for x in memories), encoding="utf-8")
    for name in extra or ():
        (tmp_path / name).write_text("{}", encoding="utf-8")
    return tmp_path


def test_valid_bundle_passes(tmp_path: Path):
    assert validate_bundle(_bundle(tmp_path, transcripts=[T1, T2], memories=[M1])) == []


def test_counts_must_match_actual_lines(tmp_path: Path):
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1], memories=[M1]))
    assert any("transcripts" in e and "计数不符" in e for e in errors)


def test_seq_gaps_are_rejected(tmp_path: Path):
    t2 = dict(T2, seq=9)
    errors = validate_bundle(_bundle(tmp_path, transcripts=[T1, t2], memories=[M1]))
    assert any("seq" in e for e in errors)


def test_origin_outside_closed_set_is_rejected(tmp_path: Path):
    errors = validate_bundle(
        _bundle(tmp_path, transcripts=[T1, T2], memories=[dict(M1, origin="superuser")]))
    assert any("origin" in e for e in errors)


def test_missing_manifest_is_rejected(tmp_path: Path):
    assert any("manifest" in e for e in validate_bundle(tmp_path))


def test_duplicate_identity_key_is_rejected(tmp_path: Path):
    errors = validate_bundle(
        _bundle(tmp_path, transcripts=[T1, dict(T2, identity_key="a")], memories=[M1]))
    assert any("identity_key 重复" in e for e in errors)
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_bundle_validate.py -q`
Expected: FAIL —— `ModuleNotFoundError: ... bundle.validate`

- [ ] **Step 7: 实现 validate.py**

```python
# neurova/memory_ingest/bundle/validate.py
"""整包校验：任一错误即由调用方拒绝整个 store（不半导，见设计 §5 漂移守卫）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from neurova.memory_ingest.bundle.manifest import SUPPORTED_SCHEMA_VERSION
from neurova.memory_ingest.bundle.records import VALID_KINDS

_TRANSIENT_KEYS = {"schema_version", "generated_at", "agent_name", "source", "counts",
                   "dropped", "stores"}


def _read_jsonl(path: Path) -> List[dict]:
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{lineno} 不是合法 JSON: {exc}") from exc
    return rows


def _check_required(rows: List[dict], required, label: str) -> List[str]:
    errors = []
    for row in rows:
        missing = [k for k in required if k not in row or row[k] in ("", None)]
        if missing:
            errors.append(f"{label} 缺字段 {missing}")
    return errors


def validate_bundle(root: Path) -> List[str]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return [f"缺 manifest.json: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json 不是合法 JSON: {exc}"]
    if manifest.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return [f"schema_version 不支持: {manifest.get('schema_version')!r}"]

    errors: List[str] = []
    rows_by_name = {}
    for name, required in (
        ("transcripts.jsonl", ("session_id", "seq", "kind", "ts", "identity_key")),
        ("memories.jsonl", ("identity_key", "content", "memory_type", "category",
                            "origin", "importance", "ts")),
    ):
        path = root / name
        if not path.exists():
            rows_by_name[name] = []
            if int(manifest.get("counts", {}).get(name.split(".")[0], 0)) > 0:
                errors.append(f"{name} 缺失但 counts 声称有条目")
            continue
        try:
            rows = _read_jsonl(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        rows_by_name[name] = rows
        errors += _check_required(rows, required, name)
        errors += [f"{name} {e}" for e in _seq_errors(rows) if name.startswith("transcripts")]
        errors += _dup_errors(rows, name)
    errors += _origin_errors(rows_by_name.get("memories.jsonl", []))
    errors += _count_errors(manifest, rows_by_name)
    return errors


def _seq_errors(rows: List[dict]) -> List[str]:
    errors = []
    by_session = {}
    for row in rows:
        if isinstance(row.get("seq"), int):
            by_session.setdefault(str(row.get("session_id")), []).append(int(row["seq"]))
    for sid, seqs in by_session.items():
        if sorted(seqs) != list(range(min(seqs), min(seqs) + len(seqs))):
            errors.append(f"会话 {sid} seq 断裂或重复: {sorted(seqs)}")
        if any(s < 1 for s in seqs):
            errors.append(f"会话 {sid} seq 必须从 1 起")
    return errors


def _dup_errors(rows: List[dict], name: str) -> List[str]:
    seen, errors = set(), []
    for row in rows:
        key = row.get("identity_key")
        if key in seen:
            errors.append(f"{name} identity_key 重复: {key!r}")
        seen.add(key)
    return errors


def _origin_errors(rows: List[dict]) -> List[str]:
    allowed = {"owner", "agent", "untrusted", "system"}
    return [f"memories.jsonl origin 越界: {r.get('origin')!r}"
            for r in rows if r.get("origin") not in allowed]


def _count_errors(manifest: dict, rows_by_name: dict) -> List[str]:
    errors = []
    for name, rows in rows_by_name.items():
        key = name.split(".")[0]
        claimed = int(manifest.get("counts", {}).get(key, 0))
        if claimed != len(rows):
            errors.append(f"{name} 计数不符: manifest={claimed} 实际={len(rows)}")
    return errors
```

- [ ] **Step 8: 跑两个测试文件确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/ -q`
Expected: PASS（全部）

- [ ] **Step 9: 提交**

```bash
git add neurova/memory_ingest/ tests/unit/memory_ingest/
git commit -m "feat(ingest): Ingest Bundle 记录类型与整包校验器"
```

---

### Task 2: MemoryManager 导入专用入口

**Files:**
- Modify: `neurova/cognitive_layers/memory_layer/manager.py`（在 `register_runtime_vector_store` 附近增方法）
- Test: `tests/unit/memory_ingest/test_import_memories.py`

**Interfaces:**
- Consumes: `MemoryRecord`（Task 1）
- Produces:
  - `MemoryManager.import_memories(records: Sequence[MemoryRecord], *, ingest_run_id: str) -> Tuple[int, int]`（`(新增, 跳过)`）
  - `MemoryManager.delete_ingested_memories(ingest_run_id: str) -> int`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/memory_ingest/test_import_memories.py
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.records import MemoryRecord

_RUN = "nvimp-test-1"


def _manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


def _record(seq: int, content: str) -> MemoryRecord:
    return MemoryRecord(identity_key=f"ik-{seq}", content=content, memory_type="semantic",
                        category="general", origin="owner", importance=60.0,
                        ts=f"2026-05-01T10:00:{seq:02d}+00:00")


def test_import_memories_visible_without_restart_and_keeps_history_ts(tmp_path: Path):
    manager = _manager(tmp_path)
    added, skipped = manager.import_memories([_record(1, "历史记忆一")], ingest_run_id=_RUN)

    assert (added, skipped) == (1, 0)
    stored = next(m for m in manager._memories.values() if m.content == "历史记忆一")
    assert stored.origin.value == "owner"
    assert stored.created_at.startswith("2026-05-01")      # 历史时间戳不被 now() 覆盖
    assert stored.metadata["ingest_run_id"] == _RUN


def test_import_memories_is_idempotent(tmp_path: Path):
    manager = _manager(tmp_path)
    records = [_record(1, "同一内容"), _record(2, "另一条")]

    first = manager.import_memories(records, ingest_run_id=_RUN)
    second = manager.import_memories(records, ingest_run_id=_RUN)

    assert first == (2, 0)
    assert second == (0, 2)


def test_import_memories_does_not_trigger_runtime_side_effects(tmp_path: Path, monkeypatch):
    """导入不得走内容门 / 关键词倒排 / MoE 向量同步（那是运行期写入口的事）。"""
    manager = _manager(tmp_path)
    calls = []
    monkeypatch.setattr(manager, "_sync_runtime_vector_store",
                        lambda *a, **k: calls.append("vector"))
    monkeypatch.setattr(manager, "_content_gate_key", lambda mem: calls.append("gate") or None)

    manager.import_memories([_record(1, "无副作用")], ingest_run_id=_RUN)

    assert calls == []


def test_delete_ingested_memories_rolls_back_exactly_that_run(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.import_memories([_record(1, "本批")], ingest_run_id=_RUN)
    manager.remember(content="运行期记忆", category="general")   # 不属本批

    removed = manager.delete_ingested_memories(_RUN)

    assert removed == 1
    assert all(m.metadata.get("ingest_run_id") != _RUN for m in manager._memories.values())
    assert any(m.content == "运行期记忆" for m in manager._memories.values())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_import_memories.py -q`
Expected: FAIL —— `AttributeError: 'MemoryManager' object has no attribute 'import_memories'`

- [ ] **Step 3: 实现入口**

放在 `register_runtime_vector_store` 之后。要点：构造 `Memory` 时显式带 `origin`/时间戳，进 `self._memories` 保证运行中实例即刻可见，落盘走既有 `_persist_memory` 的批量事务，幂等由 metadata 里的 `identity_key` 判定。

```python
    def import_memories(self, records, *, ingest_run_id: str) -> tuple:
        """导入专用写入口：批量、单事务、保留历史时间戳、不触发运行期副作用。

        与 remember() 的分工（设计 §4）：这里不跑内容门、不喂关键词倒排、不同步
        MoE 向量库——回填的历史不该被当作"刚发生的经验"重新定温或裁决。可见性仍然
        成立：行同时进内存表与持久层，检索按既有路径工作。
        """
        if not ingest_run_id:
            raise ValueError("ingest_run_id 必填（撤销按它精确删除）")
        existing_keys = {
            m.metadata.get("ingest", {}).get("identity_key") for m in self._memories.values()
        }
        added = skipped = 0
        with self._lock:
            for rec in records:
                if rec.identity_key in existing_keys:
                    skipped += 1
                    continue
                mem = Memory(
                    content=rec.content, memory_type=rec.memory_type, category=rec.category,
                    temperature=float(rec.temperature), importance=float(rec.importance),
                    origin=MemoryOrigin(rec.origin), created_at=rec.ts, updated_at=rec.ts,
                    agent_id=self._agent_id, neuser_id=self._neuser_id, user_id=self._user_id,
                    metadata={
                        "ingest_run_id": ingest_run_id,
                        "ingest": {"identity_key": rec.identity_key, "source_ref": rec.source_ref},
                        **({"tags": list(rec.tags)} if rec.tags else {}),
                    },
                )
                self._memories[mem.id] = mem
                existing_keys.add(rec.identity_key)
                self._persist_memory(mem)
                added += 1
            self._stats["total_memories"] = len(self._memories)
        return added, skipped

    def delete_ingested_memories(self, ingest_run_id: str) -> int:
        """按导入批次精确撤销（设计 §6：回滚不靠快照，靠标签）。"""
        removed = 0
        with self._lock:
            for mem_id, mem in list(self._memories.items()):
                if mem.metadata.get("ingest_run_id") != ingest_run_id:
                    continue
                del self._memories[mem_id]
                self._delete_persisted_memory(mem_id)
                removed += 1
            self._stats["total_memories"] = len(self._memories)
        return removed
```

- [ ] **Step 4: 跑测试确认通过；跑记忆面回归**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_import_memories.py tests/unit/memory -q`
Expected: PASS（`tests/unit/memory` 与改动前基线同数，无新增失败）

- [ ] **Step 5: 提交**

```bash
git add neurova/cognitive_layers/memory_layer/manager.py tests/unit/memory_ingest/test_import_memories.py
git commit -m "feat(ingest): MemoryManager 导入专用入口（历史时间戳、幂等、可撤销）"
```

---

### Task 3: SessionManager 导入专用入口

**Files:**
- Modify: `neurova/session_manager.py`（紧邻 `add_message` 增方法）
- Test: `tests/unit/memory_ingest/test_import_sessions.py`

**Interfaces:**
- Consumes: `TranscriptRecord.to_session_message()`
- Produces:
  - `SessionManager.import_session_messages(agent_id: str, session_id: str, date: str, messages: Sequence[dict], *, ingest_run_id: str) -> Tuple[int, int]`
  - `SessionManager.delete_ingested_messages(ingest_run_id: str) -> int`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/memory_ingest/test_import_sessions.py
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.records import TranscriptRecord
from neurova.session_manager import SessionManager

_RUN = "nvimp-sess-1"


@pytest.fixture(autouse=True)
def _fresh_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield
    SessionManager._instance = None


def _rec(seq: int, kind: str, text: str, **kw) -> dict:
    return TranscriptRecord(session_id="sA", seq=seq, kind=kind,
                            ts=f"2026-05-01T10:00:{seq:02d}+00:00", identity_key=f"ik{seq}",
                            content_blocks=({"type": "text", "text": text},), **kw).to_session_message()


def test_import_keeps_tool_call_and_result_as_separate_rows(tmp_path):
    sm = SessionManager()
    msgs = [_rec(1, "user_message", "问题"), _rec(2, "assistant_message", "先读文件"),
            _rec(3, "tool_call", "", tool_call_id="tc1", tool_name="fs_read"),
            _rec(4, "tool_result", "结果", tool_call_id="tc1", tool_name="fs_read")]

    added, skipped = sm.import_session_messages("default", "sA", "2026-05-01", msgs,
                                                ingest_run_id=_RUN)

    stored = sm.get_session("default", "sA", date="2026-05-01")
    assert (added, skipped) == (4, 0)
    assert [m["role"] for m in stored.messages] == ["user", "assistant", "assistant", "tool"]
    assert stored.messages[3]["tool_call_id"] == "tc1"          # 不压成文本注释


def test_import_is_idempotent_and_groups_by_date(tmp_path):
    sm = SessionManager()
    first = sm.import_session_messages("default", "sA", "2026-05-01", [_rec(1, "user_message", "早")],
                                       ingest_run_id=_RUN)
    again = sm.import_session_messages("default", "sA", "2026-05-01", [_rec(1, "user_message", "早")],
                                       ingest_run_id=_RUN)
    assert (first, again) == ((1, 0), (0, 1))


def test_delete_ingested_messages_removes_only_that_run(tmp_path):
    sm = SessionManager()
    sm.import_session_messages("default", "sA", "2026-05-01",
                               [_rec(1, "user_message", "导入的"), _rec(2, "assistant_message", "导入回复")],
                               ingest_run_id=_RUN)
    sm.add_message("default", "sA", "运行期提问", "运行期回答", date="2026-05-01")

    removed = sm.delete_ingested_messages(_RUN)

    stored = sm.get_session("default", "sA", date="2026-05-01")
    assert removed == 2
    assert [m["content"] for m in stored.messages] == ["运行期提问", "运行期回答"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_import_sessions.py -q`
Expected: FAIL —— `AttributeError: 'SessionManager' object has no attribute 'import_session_messages'`
（若 `NEUROVA_SESSIONS_DIR` 不是既有 env，改用 `SessionManager(sessions_dir=...)` 并把实例注入改为参数，见 Step 3 备注。）

- [ ] **Step 3: 实现入口**

复用 `_get_session_file` / `_read_session_file` / `_write_session_file` 与 `_get_file_lock`；幂等键取 `metadata.ingest.identity_key`。

```python
    def import_session_messages(self, agent_id: str, session_id: str, date: str,
                                messages, *, ingest_run_id: str) -> Tuple[int, int]:
        """导入专用写入口：保留扁平事件行（工具调用与结果各自成行，见设计 §2 取证 1）。

        与 add_message 的分工：后者表达"一问一答"的运行期轮次；历史回填里一轮可含
        多个调用与多个结果，压成成对消息就会丢掉结构（市面导入器的通病）。
        """
        if not ingest_run_id:
            raise ValueError("ingest_run_id 必填（撤销按它精确删除）")
        path = self._get_session_file(agent_id, session_id, date)
        file_lock = self._get_file_lock(path)
        with file_lock:
            data = self._read_session_file(path) or {
                "agent_id": agent_id, "session_id": session_id, "session_date": date,
                "messages": [], "created_at": (messages[0].get("timestamp") if messages else ""),
                "total_messages": 0,
            }
            seen = {m.get("metadata", {}).get("ingest", {}).get("identity_key")
                    for m in data["messages"]}
            added = skipped = 0
            for msg in messages:
                key = msg.get("metadata", {}).get("ingest", {}).get("identity_key")
                if key in seen:
                    skipped += 1
                    continue
                msg.setdefault("metadata", {}).setdefault("ingest_run_id", ingest_run_id)
                data["messages"].append(msg)
                seen.add(key)
                added += 1
            data["total_messages"] = len(data["messages"])
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_session_file(path, data)
        return added, skipped

    def delete_ingested_messages(self, agent_id: str, ingest_run_id: str) -> int:
        """按导入批次撤销某 agent 的会话消息；整会话被清空则删文件。"""
        removed = 0
        agent_dir = self._get_session_dir(agent_id)
        for path in agent_dir.glob("session_*.json"):
            with self._get_file_lock(path):
                data = self._read_session_file(path)
                if not data:
                    continue
                kept = [m for m in data.get("messages", [])
                        if m.get("metadata", {}).get("ingest_run_id") != ingest_run_id]
                dropped = len(data.get("messages", [])) - len(kept)
                if not dropped:
                    continue
                if not kept:
                    path.unlink(missing_ok=True)
                    removed += dropped
                    continue
                data["messages"] = kept
                data["total_messages"] = len(kept)
                self._write_session_file(path, data)
                removed += dropped
        return removed
```

- [ ] **Step 4: 跑测试 + 会话面回归**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_import_sessions.py tests/unit/api -q -k "session or ingest"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add neurova/session_manager.py tests/unit/memory_ingest/test_import_sessions.py
git commit -m "feat(ingest): SessionManager 导入入口（保留跨行工具事件、幂等、可撤销）"
```

---

### Task 4: probe 结构指纹与三态判定

**Files:**
- Create: `neurova/memory_ingest/probe.py`
- Test: `tests/unit/memory_ingest/test_probe.py`

**Interfaces:**
- Produces:
  - `StoreFinding(path: str, kind: str, hits: Tuple[str, ...], verdict: str, structure: dict)`；`verdict ∈ ("unique", "conflict", "unknown")`
  - `probe_store(path: Path) -> StoreFinding`
  - `Handprint(name: str, matches: Callable[[Path], bool], structure: Callable[[Path], dict])` + 两个内置断言工厂 `sqlite_columns(table, required, forbidden=())`、`jsonl_header(required_keys)`

- [ ] **Step 1: 写失败测试（含"像但不是"负例）**

```python
# tests/unit/memory_ingest/test_probe.py
import json
import sqlite3
from pathlib import Path

from neurova.memory_ingest.probe import probe_store

QWENPAW_COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content",
                "tool_call_id", "tool_input", "tool_state", "headline", "blocks",
                "metadata", "created_at", "dedup_key"]


def _db(path: Path, cols) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in cols) + ")")
    conn.commit(); conn.close()
    return path


def test_qwenpaw_history_recognized(tmp_path: Path):
    finding = probe_store(_db(tmp_path / "history.db", QWENPAW_COLS))
    assert finding.verdict == "unique" and "qwenpaw_history" in finding.hits


def test_missing_dedup_key_is_not_qwenpaw(tmp_path: Path):
    """像但不是：缺 dedup_key 不能认成 QwenPaw（漂移即拒，见设计 §5）。"""
    finding = probe_store(_db(tmp_path / "history.db", [c for c in QWENPAW_COLS if c != "dedup_key"]))
    assert finding.verdict == "unknown"
    assert "conversation_history" in finding.structure["tables"]


def test_unrelated_sqlite_is_unknown_with_structure_summary(tmp_path: Path):
    finding = probe_store(_db(tmp_path / "other.db", ["id", "value"]))
    assert finding.verdict == "unknown" and finding.hits == ()


def test_dsh_jsonl_header_recognized(tmp_path: Path):
    log = tmp_path / "session.jsonl"
    log.write_text(json.dumps({"type": "session", "version": 3, "id": "s1",
                               "createdAt": 1, "cwd": "/", "isSeeded": False,
                               "delegationDepth": 0}) + "\n", encoding="utf-8")
    assert probe_store(log).hits == ("dsh_session",)


def test_directory_is_scanned_per_store(tmp_path: Path):
    """一个目录里多个 store：识别单位是 store 不是目录。"""
    _db(tmp_path / "history.db", QWENPAW_COLS)
    (tmp_path / "session.jsonl").write_text(
        json.dumps({"type": "session", "version": 3, "id": "s", "createdAt": 1}) + "\n",
        encoding="utf-8")
    findings = probe_store(tmp_path) if isinstance(probe_store(tmp_path), list) else None
    assert findings is not None and len(findings) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_probe.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'neurova.memory_ingest.probe'`

- [ ] **Step 3: 实现 probe.py**

```python
# neurova/memory_ingest/probe.py
"""来源识别：结构断言，不是文件名猜测（设计 §5）。

指纹只写"可核实的结构事实"：表名+必需列集合、JSONL 首行键集合。未识别不是失败——
返回 structure 摘要供新增指纹，绝不用最像的格式硬导。私有方言（qwenpaw_memory* 等，
公开来源零命中）有意不在表内。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")


@dataclass(frozen=True)
class Handprint:
    name: str
    matches: Callable[[Path], bool]
    applies_to: str            # "sqlite" | "jsonl"


@dataclass(frozen=True)
class StoreFinding:
    path: str
    kind: str                  # "sqlite" | "jsonl" | "directory"
    hits: Tuple[str, ...]
    verdict: str               # unique | conflict | unknown
    structure: Dict[str, object]


def _sqlite_tables(path: Path) -> List[str]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()


def _columns(path: Path, table: str) -> List[str]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _first_json_line_keys(path: Path) -> List[str]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    return sorted(json.loads(line).keys())
                except json.JSONDecodeError:
                    return []
    return []


def _has_columns(table: str, required: Tuple[str, ...]) -> Callable[[Path], bool]:
    def _matches(path: Path) -> bool:
        return table in _sqlite_tables(path) and set(required) <= set(_columns(path, table))
    return _matches


_HANDPRINTS: Tuple[Handprint, ...] = (
    Handprint("qwenpaw_history",
              _has_columns("conversation_history", (
                  "seq", "session_id", "kind", "role", "content",
                  "tool_call_id", "created_at", "dedup_key")), "sqlite"),
    Handprint("dsh_session",
              lambda p: {"type", "version", "id", "createdAt"} <= set(_first_json_line_keys(p)),
              "jsonl"),
)


def _kind_of(path: Path) -> Optional[str]:
    if path.is_dir():
        return "directory"
    if path.suffix.lower() in _DB_SUFFIXES:
        return "sqlite"
    if path.suffix.lower() == ".jsonl":
        return "jsonl"
    return None


def _structure(path: Path, kind: str) -> Dict[str, object]:
    if kind == "sqlite":
        return {"tables": _sqlite_tables(path)}
    if kind == "jsonl":
        return {"first_line_keys": _first_json_line_keys(path)}
    return {"entries": sorted(p.name for p in path.iterdir())[:40]}


def _probe_one(path: Path) -> StoreFinding:
    kind = _kind_of(path) or "unknown"
    candidates = [h for h in _HANDPRINTS
                  if h.applies_to == kind and _safe_match(h, path)]
    hits = tuple(h.name for h in candidates)
    verdict = "unique" if len(hits) == 1 else ("conflict" if hits else "unknown")
    return StoreFinding(str(path), kind, hits, verdict,
                        _structure(path, kind) if kind != "unknown" else {})


def _safe_match(handprint: Handprint, path: Path) -> bool:
    """指纹求值失败（坏库/无权限）即视为不命中，让 structure 去说明情况。"""
    try:
        return bool(handprint.matches(path))
    except Exception:
        return False


def probe_store(path) -> object:
    """单个 store → StoreFinding；目录 → 逐 store 的 list（识别单位是 store）。"""
    target = Path(path)
    if target.is_dir():
        return [_probe_one(child) for child in sorted(target.rglob("*"))
                if child.is_file() and _kind_of(child) in ("sqlite", "jsonl")]
    return _probe_one(target)


def register_handprint(handprint: Handprint) -> None:
    """转换器注册自己的指纹（同一处注册，避免指纹表与转换器分叉）。"""
    _HANDPRINTS.append(handprint)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_probe.py -q`
Expected: PASS（6 条）

- [ ] **Step 5: 提交**

```bash
git add neurova/memory_ingest/probe.py tests/unit/memory_ingest/test_probe.py
git commit -m "feat(ingest): 结构指纹识别与三态判定（未识别给结构摘要）"
```

---

### Task 5: QwenPaw 会话族转换器 + 无损申报

**Files:**
- Create: `neurova/memory_ingest/converters/__init__.py`
- Create: `neurova/memory_ingest/converters/qwenpaw_history.py`
- Test: `tests/unit/memory_ingest/test_converter_qwenpaw.py`

**Interfaces:**
- Consumes: `probe_store`、`TranscriptRecord`、`validate_bundle`
- Produces: `convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest`

- [ ] **Step 1: 写失败测试（字段全部落住 + dropped 申报）**

```python
# tests/unit/memory_ingest/test_converter_qwenpaw.py
import json
import sqlite3
from pathlib import Path

import pytest

from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.memory_ingest.converters.qwenpaw_history import convert

COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
        "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    db = tmp_path / "history.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE conversation_history (" + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.executemany(
        f"INSERT INTO conversation_history VALUES ({','.join('?' * len(COLS))})",
        [(1, "sA", "凯", "user_message", "user", "用户", "问题", None, None, None, None, None,
          None, "2026-05-01T10:00:00", "k1"),
         (2, "sA", "凯", "assistant_message", "assistant", "凯", "回答", None, None, None,
          "要点", json.dumps([{"type": "thinking", "thinking": "想一想"}]), None,
          "2026-05-01T10:00:01", "k2"),
         (3, "sA", "凯", "tool_result", "tool", "fs_read", "结果", "tc1", None, "ok",
          None, None, None, "2026-05-01T10:00:02", "k3")])
    conn.commit(); conn.close()
    return db


def test_convert_produces_valid_bundle(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported_kai")
    assert validate_bundle(out) == []


def test_convert_keeps_headline_tool_state_and_reasoning(tmp_path: Path, src: Path):
    """现脚本丢掉的 headline/tool_state/agent_id/metadata 必须补回（设计 §7 验收）。"""
    out = tmp_path / "bundle"
    convert(src, out, agent_name="imported_kai")
    rows = [json.loads(x) for x in (out / "transcripts.jsonl").read_text(encoding="utf-8").splitlines()]
    by_kind = {r["kind"]: r for r in rows}

    assert by_kind["assistant_message"]["extra"]["headline"] == "要点"
    assert by_kind["tool_result"]["tool_state"] == "ok"
    assert by_kind["assistant_message"]["reasoning_state"] == "text"
    assert by_kind["assistant_message"]["reasoning_text"] == "想一想"


def test_convert_declares_every_dropped_field(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    manifest = convert(src, out, agent_name="imported_kai")
    assert manifest.dropped == ()          # 这支转换器自认无损，空数组即承诺


def test_convert_counts_match_manifest(tmp_path: Path, src: Path):
    out = tmp_path / "bundle"
    manifest = convert(src, out, agent_name="imported_kai")
    assert manifest.counts["transcripts"] == 3 and manifest.counts["memories"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_converter_qwenpaw.py -q`
Expected: FAIL —— `ModuleNotFoundError: ... converters.qwenpaw_history`

- [ ] **Step 3: 实现转换器**

```python
# neurova/memory_ingest/converters/qwenpaw_history.py
"""公开 QwenPaw 会话族 → Ingest Bundle。只读源、只产包（设计 §4）。

identity_key 直接用源的 dedup_key（它本来就是幂等列），加上 session 前缀防跨会话撞键。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from neurova.memory_ingest.bundle.manifest import BundleManifest
from neurova.memory_ingest.probe import Handprint, _columns, _has_columns  # noqa: F401 注册用

CONVERTER_NAME = "qwenpaw_history"
CONVERTER_VERSION = "1"


def _iso(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else datetime.now(timezone.utc).isoformat()


def _blocks(raw: Any) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw) if raw else []
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return parsed if isinstance(parsed, list) else []


def _map_row(row: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(row.get("kind") or "user_message")
    blocks = _blocks(row.get("blocks"))
    thinking = "".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
    session_id, seq = str(row.get("session_id")), row.get("seq")
    record = {
        "session_id": session_id, "seq": int(seq or 0), "kind": kind,
        "ts": _iso(row.get("created_at")),
        "identity_key": f"{session_id}#{row.get('dedup_key') or seq}",
        "role": str(row.get("role") or ""), "tool_call_id": str(row.get("tool_call_id") or ""),
        "tool_name": str(row.get("name") or ""), "tool_state": str(row.get("tool_state") or ""),
        "content_blocks": [{"type": "text", "text": str(row.get("content") or "")}]
                          if row.get("content") else [],
        "reasoning_state": "text" if thinking else "absent", "reasoning_text": thinking,
        # 源里有、契约字段无对应的，原样带走，不静默丢
        "extra": {"headline": row.get("headline"), "agent_id": row.get("agent_id"),
                  "tool_input": row.get("tool_input"), "source_metadata": row.get("metadata")},
    }
    return {k: v for k, v in record.items() if v not in (None, "", {}, [])}


def convert(store: Path, out_dir: Path, *, agent_name: str) -> BundleManifest:
    store, out_dir = Path(store), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{store.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM conversation_history ORDER BY session_id, seq")]
    finally:
        conn.close()

    records = [_map_row(r) for r in rows]
    # to_session_message 需要的字段名与 bundle 记录一致；写盘前剔掉非契约键由校验器把关
    with (out_dir / "transcripts.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (out_dir / "memories.jsonl").write_text("", encoding="utf-8")

    manifest = BundleManifest(
        schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
        agent_name=agent_name, source={"converter": CONVERTER_NAME, "version": CONVERTER_VERSION},
        counts={"transcripts": len(records), "memories": 0, "relations": 0},
        dropped=(), stores=({"path": str(store), "handprint": CONVERTER_NAME}
```

(截断处按计划续写：manifest 落盘 + 返回。)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_converter_qwenpaw.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add neurova/memory_ingest/converters/ tests/unit/memory_ingest/test_converter_qwenpaw.py
git commit -m "feat(ingest): QwenPaw 会话族转换器（补回被丢字段、无损申报）"
```

---

#### Task 5 落地时的实测修正（源 E:/项目/Kai/history.db，242 行，只读跑通）

1. **一轮多调用是主流形态，不是边角**：`model_turn` 的 `blocks` 里最多含 6 个 `tool_call`
   （另有 40+ 调用的极端轮），而平列 `tool_call_id`/`tool_input`/`name` 只留最后一个。
   按平列转换只能拿到 21 个调用，按块展开拿到 179 个——与 179 条 `tool_result` 行的
   `tool_call_id` 全配上（未匹配 0）。现脚本走的正是平列读法，所以它的工具链是断的。
2. **`content` 等于各 `text` 块以换行拼接**（实测 seq 2/12/43 的差异只在拼接换行处），
   所以 model_turn 行按块展开不会丢正文；`blocks` 为空或只有 thinking 的旧式行退回平列读法。
3. **源 `seq` 是全局流水号**（242 行 242 个值，单会话可从 127 起），而校验器要求会话内 1..n，
   因此转换器必须按会话重编号，源 seq 留在 `extra.source_seq`。
4. **真实源只剩一处丢失**：`blocks:data` 1 条（base64 图块）。包内 media 内容寻址存储未落地，
   按"未知即申报"写进 `manifest.dropped`，不塞进会话文件也不静默扔。
5. **对 Task 6 的硬约束**：bundle 是扁平事件流，而运行期 `_step_save_session` 写的是
   **一条 assistant 消息带 `metadata.tool_calls` 列表**（`post_chat_pipeline.py:890`），
   前端步骤卡也按这个形状读（`collaborationRoom.ts:112` → `normalizeToolMessages`）。
   把 508 条扁平事件一行一条写进会话文件，形状就和运行期产物不一致，工具轨迹在 UI 上看不见。
   所以 intake 写会话前必须加一层轮形装配。

- [ ] **Step 6: 补轮形装配（原计划漏项，依上述第 5 条）**

**Files:**
- Create: `neurova/memory_ingest/bundle/turns.py`
- Test: `tests/unit/memory_ingest/test_bundle_turns.py`

**Interfaces:**
- Consumes: `TranscriptRecord`
- Produces: `to_turn_messages(records: Sequence[TranscriptRecord]) -> List[Dict[str, Any]]`
  —— 连续的 `assistant_message`/`tool_call`/`tool_result` 合成一条轮形消息，`user_message`/
  `system`/`compact_summary` 各自一条；输出形状对齐 `_collect_tool_messages()` 的条目键
  （`type`/`tool_name`/`params`/`result`/`timestamp`），并带 `metadata.ingest`（`identity_key`
  取该轮首条事件的 key，幂等据此跳过）。

### Task 6: intake 编排（plan / apply / undo）

**Files:**
- Create: `neurova/memory_ingest/intake.py`
- Test: `tests/unit/memory_ingest/test_intake.py`

**Interfaces:**
- Consumes: `validate_bundle`、`read_transcripts`/`read_memories`、Task 2/3 的两个入口
- Produces:
  - `plan_bundle(root: Path) -> IngestPlan`
  - `apply_bundle(root: Path, *, agent_id: str, manager, sessions, run_id: str|None=None) -> IngestReport`
  - `undo_bundle_report(report: IngestReport, *, manager, sessions) -> tuple`
  - 数据类 `IngestPlan`、`IngestReport(run_id, memories_added, memories_skipped, messages_added, messages_skipped, sessions_touched, dropped)`

- [ ] **Step 1: 写失败测试（含"不 --apply 就不写库"这条姿态）**

```python
# tests/unit/memory_ingest/test_intake.py
import json
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord
from neurova.memory_ingest.intake import apply_bundle, plan_bundle
from neurova.session_manager import SessionManager

_ROWS = [
    {"session_id": "sA", "seq": 1, "kind": "user_message", "ts": "2026-05-01T10:00:00+00:00",
     "identity_key": "a", "role": "user", "content_blocks": [{"type": "text", "text": "问题"}]},
    {"session_id": "sA", "seq": 2, "kind": "tool_result", "ts": "2026-05-01T10:00:01+00:00",
     "identity_key": "b", "role": "tool", "tool_call_id": "tc1",
     "content_blocks": [{"type": "text", "text": "结果"}]},
]
_MEM = {"identity_key": "m1", "content": "记忆", "memory_type": "semantic",
        "category": "general", "origin": "owner", "importance": 50.0,
        "ts": "2026-05-01T10:00:00+00:00"}


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"; root.mkdir()
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "imported", "source": {"converter": "x", "version": "1"},
        "counts": {"transcripts": len(_ROWS), "memories": 1, "relations": 0},
        "dropped": [{"store": "s", "field": "usage", "reason": "源无该列", "count": 2}],
        "stores": []}), encoding="utf-8")
    (root / "transcripts.jsonl").write_text("\n".join(json.dumps(r) for r in _ROWS), encoding="utf-8")
    (root / "memories.jsonl").write_text(json.dumps(_MEM), encoding="utf-8")
    return root


@pytest.fixture()
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield SessionManager()
    SessionManager._instance = None


def test_plan_reports_without_touching_stores(bundle, manager, sessions):
    plan = plan_bundle(bundle)
    assert plan.counts["transcripts"] == 2 and plan.dropped[0]["field"] == "usage"
    assert manager._memories == {}


def test_apply_writes_both_throats(bundle, manager, sessions):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    assert (report.memories_added, report.messages_added) == (1, 2)
    assert any(m.content == "记忆" for m in manager._memories.values())


def test_apply_twice_is_idempotent(bundle, manager, sessions):
    first = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    second = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    assert (first.memories_added, second.memories_added, second.memories_skipped) == (1, 0, 1)


def test_undo_removes_exactly_the_batch(bundle, manager, sessions):
    report = apply_bundle(bundle, agent_id="default", manager=manager, sessions=sessions)
    manager.remember(content="运行期记忆", category="general")

    mem_removed, msg_removed = report.undo(manager=manager, sessions=sessions)

    assert (mem_removed, msg_removed) == (1, 2)
    assert any(m.content == "运行期记忆" for m in manager._memories.values())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_intake.py -q`
Expected: FAIL —— `ModuleNotFoundError: ... intake`

- [ ] **Step 3: 实现 intake.py**

```python
# neurova/memory_ingest/intake.py
"""编排：校验 → 只读出计划（plan）→ 显式写库（apply）→ 按批次撤销（undo）。

写库需显式 --apply 的姿态在这里落地：plan_bundle 全程只读，apply_bundle 才调咽喉。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.memory_ingest.bundle.manifest import BundleError, load_manifest
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord
from neurova.memory_ingest.bundle.validate import validate_bundle

MAX_RECORDS = 200_000          # 误指大目录的兜底闸


@dataclass(frozen=True)
class IngestPlan:
    agent_name: str
    source: Dict[str, Any]
    counts: Dict[str, int]
    dropped: Tuple[Dict[str, Any], ...]


@dataclass
class IngestReport:
    run_id: str
    agent_id: str
    memories_added: int = 0
    memories_skipped: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    sessions_touched: int = 0
    dropped: Tuple[Dict[str, Any], ...] = ()

    def undo(self, *, manager, sessions) -> Tuple[int, int]:
        """返回 (撤销记忆条数, 撤销消息条数)。只删本批，不碰运行期数据。"""
        return (manager.delete_ingested_memories(self.run_id),
                sessions.delete_ingested_messages(self.agent_id, self.run_id))


def _load(root: Path) -> Tuple[List[TranscriptRecord], List[MemoryRecord], Any]:
    errors = validate_bundle(root)
    if errors:
        raise BundleError("包校验未通过：" + "；".join(errors))
    manifest = load_manifest(root / "manifest.json")
    transcripts: List[TranscriptRecord] = []
    tpath = root / "transcripts.jsonl"
    if tpath.exists():
        for line in tpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                transcripts.append(TranscriptRecord(**json.loads(line)))
    memories: List[MemoryRecord] = []
    mpath = root / "memories.jsonl"
    if mpath.exists():
        for line in mpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                memories.append(MemoryRecord(**json.loads(line)))
    total = len(transcripts) + len(memories)
    if total > MAX_RECORDS:
        raise BundleError(f"条目数 {total} 超上限 {MAX_RECORDS}，拒绝（疑似指错目录）")
    return transcripts, memories, manifest


def plan_bundle(root: Path) -> IngestPlan:
    """只读：给调用方出报告用，不触碰任何 store。"""
    transcripts, memories, manifest = _load(Path(root))
    return IngestPlan(agent_name=manifest.agent_name, source=dict(manifest.source),
                      counts={"transcripts": len(transcripts), "memories": len(memories)},
                      dropped=tuple(manifest.dropped))


def apply_bundle(root: Path, *, agent_id: str, manager, sessions,
                 run_id: Optional[str] = None) -> IngestReport:
    transcripts, memories, manifest = _load(Path(root))
    report = IngestReport(run_id=run_id or f"nvimp-{uuid.uuid4().hex[:12]}",
                         agent_id=agent_id, dropped=tuple(manifest.dropped))

    report.memories_added, report.memories_skipped = manager.import_memories(
        memories, ingest_run_id=report.run_id)

    by_session_date: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for record in transcripts:
        date = record.ts[:10]
        by_session_date.setdefault((record.session_id, date), []).append(
            record.to_session_message())
    for (session_id, date), msgs in sorted(by_session_date.items()):
        added, skipped = sessions.import_session_messages(
            agent_id, session_id, date, msgs, ingest_run_id=report.run_id)
        report.messages_added += added
        report.messages_skipped += skipped
        report.sessions_touched += 1
    return report
```

- [ ] **Step 4: 跑全套 ingest 测试 + 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest tests/unit/memory tests/unit/api -q`
Expected: PASS，且 `tests/unit/api` 失败数与基线 15 一致

- [ ] **Step 5: 提交**

```bash
git add neurova/memory_ingest/intake.py tests/unit/memory_ingest/test_intake.py
git commit -m "feat(ingest): intake 编排（只读出计划、显式写库、按批次撤销）"
```

---

### Task 7: CLI 三态与显式确认

**Files:**
- Create: `scripts/ingest_memory.py`
- Test: `tests/unit/memory_ingest/test_cli.py`

**Interfaces:** Consumes `probe_store`/`convert`/`plan_bundle`/`apply_bundle`；Produces `main(argv: Sequence[str]) -> int`，退出码 `0 成功 / 2 未识别或冲突 / 3 校验失败 / 4 报告态（未接受 --apply）`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/memory_ingest/test_cli.py
import json
import sqlite3
from pathlib import Path

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.cli_errors import EXIT_REPORT_ONLY, EXIT_UNRECOGNIZED
from neurova.session_manager import SessionManager
from scripts.ingest_memory import main

COLS = ["seq", "session_id", "agent_id", "kind", "role", "name", "content", "tool_call_id",
        "tool_input", "tool_state", "headline", "blocks", "metadata", "created_at", "dedup_key"]


def _qwenpaw_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE conversation_history ("
                 + ", ".join(f"{c} TEXT" for c in COLS) + ")")
    conn.execute("INSERT INTO conversation_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (1, "sA", "凯", "user_message", "user", "用户", "问题", None, None, None,
                  None, None, None, "2026-05-01T10:00:00", "k1"))
    conn.commit(); conn.close()
    return path


def test_detect_prints_verdicts_and_writes_nothing(tmp_path: Path, capsys):
    db = _qwenpaw_db(tmp_path / "history.db")
    assert main(["detect", str(db)]) == 0
    out = capsys.readouterr().out
    assert "qwenpaw_history" in out and "唯一命中" in out
    assert not (tmp_path / "bundle").exists()


def test_unrecognized_source_exits_2(tmp_path: Path, capsys):
    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE unrelated (id TEXT)")
    conn.commit(); conn.close()
    assert main(["detect", str(tmp_path / "x.db")]) == EXIT_UNRECOGNIZED


def test_apply_without_yes_is_report_only(tmp_path: Path):
    db = _qwenpaw_db(tmp_path / "history.db")
    manager = MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))
    sessions_dir = tmp_path / "sessions"
    code = main(["apply", str(db), "--agent-id", "default", "--sessions-dir", str(sessions_dir)])
    assert code == EXIT_REPORT_ONLY
    assert sessions_dir.exists() is False or not list(sessions_dir.glob("**/session_*.json"))
    assert manager._memories == {}


def test_apply_with_yes_writes(tmp_path: Path):
    db = _qwenpaw_db(tmp_path / "history.db")
    manager = MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))
    code = main(["apply", str(db), "--agent-id", "default",
                 "--sessions-dir", str(tmp_path / "sessions"), "--yes"])
    assert code == 0 and len(manager._memories) == 0      # 会话源不产记忆
    assert list((tmp_path / "sessions").glob("**/session_*.json"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_cli.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'scripts.ingest_memory'`

- [ ] **Step 3: 实现 `neurova/memory_ingest/cli_errors.py`（退出码常量，测试与实现共用一处）**

```python
# neurova/memory_ingest/cli_errors.py
"""CLI 退出码：调用方（含 CI 脚本）据此分支，不靠解析文案。"""
EXIT_OK = 0
EXIT_UNRECOGNIZED = 2      # 未识别或多指纹冲突
EXIT_INVALID_BUNDLE = 3    # 包校验未通过
EXIT_REPORT_ONLY = 4       # 未接受 --yes，只出报告
```

- [ ] **Step 4: 实现 `scripts/ingest_memory.py`（薄壳，无业务逻辑）**

```python
#!/usr/bin/env python
"""外部 agent 数据导入 CLI：detect（只读报告）→ apply（需 --yes）→ undo。"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.memory_ingest.cli_errors import (  # noqa: E402
    EXIT_INVALID_BUNDLE, EXIT_OK, EXIT_REPORT_ONLY, EXIT_UNRECOGNIZED)
from neurova.memory_ingest.intake import apply_bundle, plan_bundle  # noqa: E402
from neurova.memory_ingest.probe import probe_store  # noqa: E402


def _detect(path: Path) -> int:
    findings = probe_store(path)
    findings = findings if isinstance(findings, list) else [findings]
    for finding in findings:
        label = {"unique": "唯一命中", "conflict": "多指纹冲突", "unknown": "未识别"}[finding.verdict]
        print(f"[{label}] {finding.path} 命中={finding.hits or '无'} 结构={finding.structure}")
    return EXIT_OK if all(f.verdict == "unique" for f in findings) else EXIT_UNRECOGNIZED


def _apply(path: Path, agent_id: str, sessions_dir: str, confirmed: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="ingest-") as staging:
        findings = probe_store(path)
        findings = findings if isinstance(findings, list) else [findings]
        if any(f.verdict != "unique" for f in findings):
            return _detect(path)
        bundle = Path(staging) / "bundle"
        from neurova.memory_ingest.converters.qwenpaw_history import convert
        convert(Path(path), bundle, agent_name=agent_id)
        plan = plan_bundle(bundle)
        print(f"计划：会话事件 {plan.counts['transcripts']} 条、记忆 {plan.counts['memories']} 条、"
              f"降级申报 {len(plan.dropped)} 项")
        if not confirmed:
            print("未写库（报告态）。确认请加 --yes")
            return EXIT_REPORT_ONLY

        from neurova.cognitive_layers.memory_layer.manager import get_memory_manager
        from neurova.session_manager import SessionManager

        os.environ["NEUROVA_SESSIONS_DIR"] = sessions_dir
        manager = get_memory_manager(agent_id)
        report = apply_bundle(bundle, agent_id=agent_id, manager=manager,
                              sessions=SessionManager())
        print(f"已写入 run_id={report.run_id}：记忆 +{report.memories_added}/跳过 "
              f"{report.memories_skipped}，消息 +{report.messages_added}/跳过 "
              f"{report.messages_skipped}，会话文件 {report.sessions_touched} 个")
        return EXIT_OK


def main(argv) -> int:
    parser = argparse.ArgumentParser(prog="ingest_memory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    det = sub.add_parser("detect"); det.add_argument("source")
    app = sub.add_parser("apply")
    app.add_argument("source"); app.add_argument("--agent-id", default="default")
    app.add_argument("--sessions-dir", default="sessions")
    app.add_argument("--yes", action="store_true", help="确认写库（缺省只出报告）")
    und = sub.add_parser("undo")
    und.add_argument("--agent-id", required=True); und.add_argument("--run-id", required=True)
    und.add_argument("--sessions-dir", default="sessions")
    args = parser.parse_args(argv)

    if args.cmd == "detect":
        return _detect(Path(args.source))
    if args.cmd == "apply":
        return _apply(Path(args.source), args.agent_id, args.sessions_dir, args.yes)
    return _undo(args.agent_id, args.run_id, args.sessions_dir)


def _undo(agent_id: str, run_id: str, sessions_dir: str) -> int:
    import os

    os.environ["NEUROVA_SESSIONS_DIR"] = sessions_dir
    from neurova.cognitive_layers.memory_layer.manager import get_memory_manager
    from neurova.session_manager import SessionManager

    manager = get_memory_manager(agent_id)
    removed = (manager.delete_ingested_memories(run_id),
               SessionManager().delete_ingested_messages(agent_id, run_id))
    print(f"已撤销 run_id={run_id}：记忆 {removed[0]} 条、消息 {removed[1]} 条")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/memory_ingest/test_cli.py -q`
Expected: PASS（5 条）

- [ ] **Step 6: 提交**

```bash
git add scripts/ingest_memory.py neurova/memory_ingest/cli_errors.py tests/unit/memory_ingest/test_cli.py
git commit -m "feat(ingest): 导入 CLI（detect 只读、apply 需 --yes、undo 按批次）"
```

**执行注意（写码前先看，三个坑都在上面代码块里）**
1. `_apply`/`_undo` 用了 `os.environ` —— 模块顶部必须 `import os`（上面代码块漏了）。
2. `SessionManager` 是类级单例且 `_initialized` 只认首次构造，`NEUROVA_SESSIONS_DIR` 必须在**任何**
   `SessionManager()` 之前设置；测试里要先 `SessionManager._instance = None`（同 Task 3 夹具做法），
   否则 `--sessions-dir` 静默失效、文件落到仓库 `sessions/`（那就是我们刚修完的那类污染）。
3. `get_memory_manager(agent_id)` 是按作用域缓存的工厂（`manager.py:3520+`），跨用例会复用同一个库；
   CLI 测试必须显式 `--agent-id` 用唯一 id，或改为向 `main` 注入 manager/sessions（优先后者：
   `main(argv, *, manager=None, sessions=None)`，缺省才自己装配 —— 测试因此不需要碰缓存）。
4. `EXIT_INVALID_BUNDLE` 要在 `apply_bundle` 抛 `BundleError` 时被 `main` 捕获返回，否则常量是死码。

---

### Task 8: 仓库处置与等价验收

**Files:**
- Modify: `.gitignore`（删 `/scripts/import_kai_to_neurova.py`、`/tests/unit/migration/` 两行）
- Delete: `scripts/import_kai_to_neurova.py`（等价验收通过后）
- Move: `tests/unit/migration/test_kai_import.py` → `tests/unit/memory_ingest/test_kai_parity.py`（改指向新 API）

- [ ] **Step 1:** 先跑真实 `Kai/history.db` 的等价对照（旧脚本 vs 新转换器：会话数与消息数一致，且新侧多出 `headline`/`tool_state`/`reasoning` 三项补回），记录数字。
- [ ] **Step 2:** 迁移既有 560 行测试：改 import 到新 API，全部合成夹具保持；跑通。
- [ ] **Step 3:** `.gitignore` 删两行；`git add -f tests/unit/migration/...` 前先解忽略，确认新路径被跟踪。
- [ ] **Step 4:** 删本地脚本；`grep -rn "import_kai_to_neurova" .` 确认无悬挂引用。
- [ ] **Step 5:** 提交并复核：他人在途 hunk 未被带走。

---

## 执行结果（2026-09-20，Task 1-7 完成，Task 8 部分完成）

Task 1-7 全部按 TDD 落库（8 个提交，110 条 ingest 用例绿）。三源等价对照的实测数字：

| 源 | 现脚本 | 新链 | 差异说明 |
|----|--------|------|----------|
| history.db 会话表 | 7 会话 / 61 条消息 | 7 会话 / 63 条 | +2 是纯工具轮（旧脚本把无正文轮的调用顺延或丢弃）；工具调用 21 → 179，与 179 条结果行全配 |
| workspace/dialog | 40 会话 / 6642 条 / 1853477 字符 / 工具条目 0 | 40 会话 / 2899 条 / 1856480 字符 / 工具条目 10561 | 条数因轮形装配减少（一轮一条 assistant 消息）；旧脚本不认 `tool_use`/`tool_result` 块，一万多个工具事件静默丢失 |
| workspace/sessions（1.x） | 31 会话 / 1718 条 / 258378 字符 / 工具条目 1353 | 31 会话 / 618 条 / 258857 字符 / 工具条目 2706 | 同上；结果行（role=toolResult）旧脚本整行不看 |

Task 8 未完成的两项，都是要人拍板的，不是漏项：

1. **`.gitignore` 两行不删、本地脚本不退役**。三源里只有"聊天"这条链等价了；脚本还管着
   记忆库、session_contexts 快照、reme 笔记、身份文件四类，前三种属本机私有方言（口径已定：
   不在本轮），身份文件按已定方案不并入。现在删脚本＝砍掉四类还在用的能力。
2. **`tests/unit/migration/test_kai_import.py` 不整体搬迁**。15 条用例里只有会话族那几条
   能对应到新 API（已在 `tests/unit/memory_ingest/` 下按合成夹具重写并加真实形状回归），
   其余 11 条测的是上面那些未并入的来源；而这两份文件被忽略的注记写的是"本地工具，不入库"，
   里面还带私有事物的具名——把它解忽略既是能力决定也是合规决定，需要单独立项。

下一轮待办（按依赖序）：包内 media 内容寻址（file/image 块，实测 12+23+1 处）→ 记忆类来源的
公开方言转换器 → 通道侧会话 id 冒号问题（见 fix 提交说明里的预存缺陷登记）→ 脚本退役与测试归位。

---

## 第二轮补做（同日，Task 8 之后）

第一轮收口时留了三处"半条路"，本轮逐个做完，全部按 TDD 且真实数据活体验证：

1. **轮形装配**（`bundle/turns.py`）：导入产物与运行期 `_step_save_session` 同形，工具轨迹在
   前端步骤卡里看得见。会话表 508 事件 → 63 条轮形消息；三源合计 3580 条（63 + 2899 + 618）。
2. **包内 media**（`bundle/media.py`）：base64/file://裸路径三类载体按 sha256 前 32 位内容寻址
   落包，整包校验加"引用在包内 + 文件在 + 摘要相符"三道闸；写侧落 `agent_workspaces/<id>/media/`
   并给出与注册处同一算法的 `metadata.artifacts` 条目。真实数据 32 个媒体文件落包，
   `blocks:*`/`media:不可达` 申报全部归零；undo 后媒体清零（22 个 / 4132KB 实测）。
3. **会话号归一**（`session_manager.normalize_store_key`）：冒号在 Windows 根本开不出文件
   （实测 `.tmp` 改名 OSError，绕过原子写则内容进 NTFS 数据流、glob 看不见），斜杠可越目录，
   方括号破坏按 id 拼的 glob。写侧归一、读侧字面兜底并续写老文件，11 处取路径点收进一处。
4. **CLI 目录姿态**：整目录源认得出的写、认不出的逐条报且一字节不写，收尾给非零码；未识别
   单独成 `UnrecognizedSourceError`（退 2 换源）与包不合规（退 3 修包）分开。撤销只留
   `undo_run` 一条口径，删消息前扫出这批引用的媒体名，删完清掉已无人引用的。

未做（要人拍板或另开批次）：本地一次性脚本退役、`tests/unit/migration/` 解忽略、通道侧带备份的
重命名收敛、artifact 注册表持久化、产出记忆的第二家真实来源。细节见 spec §9。

---

## Self-Review 结论

- 覆盖：设计 §3 契约(T1) · §4 组件与两入口(T1-3,5,6) · §5 识别(T4,5) · §6 失败与撤销(T2,3,6,7) · §7 测试(T1-7 内建 + T8 真实对照) · §8 顺序(T8)。§1 非目标与 §9 缺口不产生任务，正确。
- 占位符：T6/T7 的步骤描述需在执行时补齐为真实代码块（执行者是我，且接口已定；subagent 执行时先补步骤内容再动手）。
- 类型一致性：`ingest_run_id` 全程同名；`identity_key` 与 `metadata.ingest.identity_key` 一致；`TranscriptRecord.tool_state` 与转换器键 `tool_state` 一致（Bundle 侧多出的非契约键由校验器白名单放行 —— 执行时需在 T1 Step 7 的 `_check_required` 之外确认不判为错误，已用 `extra`/`tool_state` 允许透传）。
