# -*- coding: utf-8 -*-
"""转换器共用的落包机制：源事件 → 带会话内 seq 的记录 → 包目录。

三家转换器各自要写的只有"源方言 → 事件"这一段；编号、幂等键、manifest 落盘是同一套规则，
各写一份就会从第二家开始漂移（包内 seq 是否连续、一行多事件时 identity_key 怎么追加）。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.memory_ingest.bundle.manifest import BundleManifest, dump_manifest
from neurova.memory_ingest.bundle.records import (VALID_ROLE_KINDS, MemoryRecord,
                                                  TranscriptRecord)


@dataclass(frozen=True)
class SourceEvent:
    """一条待落包事件：kind 用包内规范词，字段与 TranscriptRecord 对齐。"""
    kind: str
    ts: str
    role: str = ""
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_state: str = ""
    reasoning: str = ""
    reasoning_state: str = ""       # 源里推理正文是密文时显式标 opaque，不用空串冒充 absent
    blocks: Tuple[Dict[str, Any], ...] = ()   # 内容寻址媒体引用（排在正文之后）
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in VALID_ROLE_KINDS:
            raise ValueError(f"未知事件 kind: {self.kind!r}")


def ensure_offset(ts: str, zone: Optional[tzinfo] = None) -> str:
    """把源里的时间字符串定标成带显式偏移的 ISO；**定不出来返回空串**。

    契约要求 ts 带时区：包内靠它做日期分桶，读侧要能 fromisoformat（3.10 连 "Z" 都不认）。
    源里没写偏移时才用 zone（各家口径见转换器注释），缺省按 UTC。

    空串是"这条没有可靠时刻"的唯一表达，调用方据此申报并跳过该行。造一个当前时刻会把
    回填的历史写进今天的会话文件（分桶按 ts 的日期），包内还看不出区别——宁可拒绝也不猜。
    """
    text = str(ts or "").strip().replace(" ", "T")
    if not text:
        return ""
    try:
        parsed = (datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
                  if text.endswith("Z") else datetime.fromisoformat(text))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone or timezone.utc)
    return parsed.isoformat()


def materialize(groups: Sequence[Tuple[str, Sequence[Tuple[str, Sequence[SourceEvent]]]]]
                ) -> List[TranscriptRecord]:
    """[(会话, [(该源行的幂等前缀, [事件])])] → 会话内 1..n 编号的记录列表。"""
    records: List[TranscriptRecord] = []
    for session_id, rows in groups:
        seq = 0
        for base_key, events in rows:
            for index, event in enumerate(events):
                seq += 1
                suffix = "" if len(events) == 1 else f"#{index}"
                records.append(_record(session_id, seq, f"{base_key}{suffix}", event))
    return records


def write_bundle(out_dir: Path, records: Sequence[TranscriptRecord], *, agent_name: str,
                 source: Dict[str, Any], dropped: Sequence[Dict[str, Any]],
                 stores: Sequence[Dict[str, Any]],
                 memories: Sequence[MemoryRecord] = ()) -> BundleManifest:
    """只写包：transcripts/memories/manifest 三件套，返回同一份 manifest。

    会话与记忆是两支族但同属一个 store（一家源库里两张表都有的情况真实存在），所以一支包
    可以两者都有；给了几条就记几条，计数与落盘条数不符就是校验器要拦的半包。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "transcripts.jsonl", records)
    _write_jsonl(out_dir / "memories.jsonl", memories)
    relations = _line_count(out_dir / "relations.jsonl")   # 转换器暂不产它，但第三方包可能带

    manifest = BundleManifest(
        schema_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        agent_name=agent_name,
        source=dict(source),
        counts={"transcripts": len(records), "memories": len(memories), "relations": relations},
        dropped=tuple(dropped),
        stores=tuple(stores),
    )
    dump_manifest(manifest, out_dir / "manifest.json")
    return manifest


def _line_count(path: Path) -> int:
    """非空行数：登记用的计数，与校验器核的是同一口径。"""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def dropped_entries(declared: Counter, reasons: Dict[str, str]) -> List[Dict[str, Any]]:
    """申报的唯一口径：字段名原样带出，原因先按整名后按前缀查，都查不到用本族的兜底文案。

    六族各写一份时，同一个未预期键会被说成不同的原因（"type"/"payload"/"event"/"part"…），
    报告就不可比较了；reasons 必须带 "__fallback__" 键。
    """
    entries = []
    for field, count in sorted(declared.items()):
        if count <= 0:
            continue
        entries.append({"field": field, "count": count,
                        "reason": reasons.get(field) or reasons.get(field.split(":")[0])
                                  or reasons["__fallback__"]})
    return entries


def _write_jsonl(path: Path, records: Sequence[Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def _blocks(event: SourceEvent) -> Tuple[Dict[str, Any], ...]:
    text = ({"type": "text", "text": event.text},) if event.text else ()
    return text + tuple(event.blocks)


def _record(session_id: str, seq: int, identity_key: str, event: SourceEvent) -> TranscriptRecord:
    return TranscriptRecord(
        session_id=session_id, seq=seq, kind=event.kind, ts=event.ts,
        identity_key=identity_key, role=event.role,
        content_blocks=_blocks(event),
        tool_call_id=event.tool_call_id, tool_name=event.tool_name,
        tool_state=event.tool_state,
        reasoning_state=event.reasoning_state or ("text" if event.reasoning else "absent"),
        reasoning_text=event.reasoning,
        extra={key: value for key, value in event.extra.items() if value is not None},
    )
