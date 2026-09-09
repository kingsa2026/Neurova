#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kai（QwenPaw）→ Neurova 记忆与聊天导入器。

数据源（E:/项目/Kai）→ 目标（agent_workspaces/kai + sessions/kai）：

记忆：
  workspace/memory/human_thinking_memory_Kai.db  qwenpaw_memory 885 条（主库）
  workspace/memory/neural_memory.db              memories 874 条（旧库，仅补内容去重增量）
  两者 created_at 语义均为 UTC → 存储为显式 +00:00，原始时刻不动。

聊天（会话内必须时间升序，用户验收硬约束）：
  workspace/sessions/*.jsonl        QwenPaw 1.x 原生会话（Z=UTC → 转 +08:00）
  workspace/dialog/*.jsonl          每日对话 jsonl（本地时间 → 显式 +08:00）
  history.db                        QwenPaw 2.x 三渠道（console/wechat/xiaoyi，
                                    本地时间 → 显式 +08:00；context_msg 合并进
                                    user 轮、tool_result 折叠不丢 assistant 文本）

身份：
  SOUL.md → agent_workspaces/kai/memory/soul.md（Agent._load_identity 真实加载位）
  PROFILE.md → memory/personality.md + workspace 根留档
  MEMORY.md → workspace 根留档

幂等：记忆按 (agent_id, content, created_at) 去重；会话按消息
(metadata.kai_import.source, metadata.kai_import.ts) 去重，重跑零增量。

用法：
  python scripts/import_kai_to_neurova.py --kai-root E:/项目/Kai \
      --neurova-root E:/项目/Neurova [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

CN_TZ = timezone(timedelta(hours=8))  # 源本地时区 Asia/Shanghai
UTC = timezone.utc
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# QwenPaw memory_type → Neurova (memory_type, category) 映射（合法枚举闭集）
TYPE_MAP = {
    "fact": ("semantic", "knowledge"),
    "preference": ("semantic", "user_preference"),
    "emotion": ("emotional", "experience"),
    "conversation": ("episodic", "conversation"),
    "project_decision": ("semantic", "experience"),
    "system": ("semantic", "general"),
    "covenant": ("emotional", "experience"),
    "session_test": ("episodic", "general"),
    "general": ("episodic", "general"),
}


def _norm_ts(raw: str, tz: timezone) -> str:
    """归一时间戳为 ISO8601 带显式偏移；naive 视为 tz 时区，不改变时刻。"""
    s = str(raw).strip().replace(" ", "T")
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=UTC)
    else:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
    return dt.isoformat()


def _utc_to_cn(ts: str) -> str:
    """UTC 时间戳 → 本地 +08:00 同一时刻（仅时区换算，时刻不变）。"""
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=UTC)
    else:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(CN_TZ).isoformat()


def _safe_name(s: str) -> str:
    """会话 ID → 文件名安全段。"""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-") or "unnamed"


# 工具结果落盘截断阈值（字符）：Neurova 原生会话也不保全文，
# 保真优先保对话流；全量结果仍留在 Kai 源可回查
MAX_TOOL_RESULT = 8000
_TRUNC_SUFFIX = "…[截断]"


def _truncate_result(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT:
        return text
    return text[:MAX_TOOL_RESULT] + _TRUNC_SUFFIX


def _mk_msg(role: str, content: str, ts: str, source: str, src_ts: str,
            name: str = "", *, reasoning: str = "",
            tool_calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    m: Dict[str, Any] = {"role": role, "content": content, "timestamp": ts}
    if name:
        m["name"] = name
    meta: Dict[str, Any] = {"kai_import": {"source": source, "ts": src_ts}}
    if reasoning:
        meta["reasoning_content"] = reasoning
    if tool_calls:
        meta["tool_calls"] = tool_calls
    m["metadata"] = meta
    return m


def _split_blocks(content: Any) -> Tuple[str, str, List[Dict[str, Any]]]:
    """QwenPaw content 块数组 → (正文, 思考全文, tool_calls 原始调用列表)。

    Neurova 历史回放契约（useChat.ts）：metadata.reasoning_content = 思考全文、
    metadata.tool_calls = [{type: tool_call, tool_name, params, timestamp},
    {type: tool_result, tool_name, result}] 交替数组。
    """
    if isinstance(content, str):
        return content, "", []
    text_parts: List[str] = []
    think_parts: List[str] = []
    calls: List[Dict[str, Any]] = []
    if isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "text" and blk.get("text"):
                text_parts.append(blk["text"])
            elif t == "thinking" and blk.get("thinking"):
                think_parts.append(blk["thinking"])
            elif t == "toolCall":
                calls.append({
                    "type": "tool_call",
                    "tool_name": blk.get("name") or "",
                    "params": blk.get("arguments") or {},
                })
    return "\n".join(text_parts), "\n".join(think_parts), calls


def _msg_date(ts_iso: str) -> str:
    """ISO 时间戳 → 会话日期文件后缀（按已换算好的本地时间）。"""
    return ts_iso[:10]


# ══════════════════════════════════════════════════════════════════
# 记忆导入
# ══════════════════════════════════════════════════════════════════


def _ensure_persist_db(persist_db: Path) -> None:
    """建表（与 MemoryManager._init_persistence_db 同构，幂等）。"""
    persist_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(persist_db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL DEFAULT 'semantic',
            category TEXT NOT NULL DEFAULT 'general',
            lifecycle_stage TEXT NOT NULL DEFAULT 'active',
            perspective TEXT NOT NULL DEFAULT 'first_person',
            origin TEXT NOT NULL DEFAULT 'agent',
            emotion TEXT NOT NULL DEFAULT 'neutral',
            temperature REAL NOT NULL DEFAULT 100.0,
            importance REAL NOT NULL DEFAULT 50.0,
            access_count INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            agent_id TEXT NOT NULL DEFAULT 'default',
            neuser_id TEXT NOT NULL DEFAULT 'default',
            user_id TEXT NOT NULL DEFAULT 'default',
            shared INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT
        )"""
    )
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category)",
        "CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(memory_type)",
        "CREATE INDEX IF NOT EXISTS idx_mem_3tier ON memories(agent_id, neuser_id, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_mem_temperature ON memories(temperature)",
    ):
        conn.execute(stmt)
    conn.commit()
    conn.close()


def _load_existing_keys(conn: sqlite3.Connection) -> set:
    return {
        (r[0], r[1], r[2])
        for r in conn.execute("SELECT agent_id, content, created_at FROM memories").fetchall()
    }


def _insert_memory(conn: sqlite3.Connection, *, agent_id: str, content: str,
                   memory_type: str, category: str, importance: int,
                   created_at: str, updated_at: str, tags: list,
                   meta: dict, origin: str = "owner") -> str:
    """按与 MemoryManager.remember 相同的字段约定写入一行，返回新 id。

    id 由内容+时间派生（幂等键），非自增——重复导入命中同一 id。
    """
    import hashlib

    key = f"{agent_id}|{content}|{created_at}"
    mid = "kai-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    meta = dict(meta or {})
    if tags:
        meta["kai_tags"] = tags
    conn.execute(
        "INSERT OR IGNORE INTO memories (id, content, memory_type, category, lifecycle_stage,"
        " perspective, origin, emotion, temperature, importance, access_count, metadata,"
        " agent_id, neuser_id, user_id, shared, created_at, updated_at, last_accessed_at)"
        " VALUES (?, ?, ?, ?, 'active', 'first_person', ?, 'neutral', 100.0, ?, 0, ?,"
        " ?, 'default', 'default', 0, ?, ?, NULL)",
        (mid, content, memory_type, category, origin, float(importance) * 10.0,
         json.dumps(meta, ensure_ascii=False), agent_id, created_at, updated_at),
    )
    return mid


def import_memories(src_db: Path, persist_db: Path, agent_id: str = "kai") -> Dict[str, int]:
    """导入 qwenpaw_memory 主库（跳过 deleted_at 非空）。"""
    if not src_db.exists():
        return {"imported": 0, "skipped_deleted": 0, "skipped_dup": 0}
    _ensure_persist_db(persist_db)
    conn = sqlite3.connect(persist_db)
    existing = _load_existing_keys(conn)

    src = sqlite3.connect(f"file:{src_db.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT * FROM qwenpaw_memory WHERE deleted_at IS NULL ORDER BY created_at, id"
    ).fetchall()

    imported = dup = 0
    skipped_deleted = src.execute(
        "SELECT COUNT(*) FROM qwenpaw_memory WHERE deleted_at IS NOT NULL"
    ).fetchone()[0]
    for r in rows:
        created = _norm_ts(r["created_at"], UTC)
        updated = _norm_ts(r["updated_at"] or r["created_at"], UTC)
        key = (agent_id, r["content"], created)
        if key in existing:
            dup += 1
            continue
        mtype, cat = TYPE_MAP.get((r["memory_type"] or "general").strip(),
                                  ("episodic", "general"))
        tags = json.loads(r["tags"] or "[]") if (r["tags"] or "").startswith("[") else []
        try:
            meta = json.loads(r["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        meta["kai_source"] = {
            "db": "human_thinking_memory_Kai.db", "id": r["id"],
            "session_id": r["session_id"], "memory_tier": r["memory_tier"],
            "memory_category_raw": r["memory_category"], "memory_type_raw": r["memory_type"],
        }
        _insert_memory(conn, agent_id=agent_id, content=r["content"],
                       memory_type=mtype, category=cat,
                       importance=r["importance"] or 3,
                       created_at=created, updated_at=updated, tags=tags, meta=meta)
        existing.add(key)
        imported += 1

    conn.commit()
    conn.close()
    src.close()
    return {"imported": imported, "skipped_deleted": skipped_deleted, "skipped_dup": dup}


_INLINE_DATE_RE = re.compile(r"(2026-\d{2}-\d{2})(?:[ T](\d{2}:\d{2})(?::\d{2})?)?")


def _ctx_created_at(content: str, loaded_at: str) -> str:
    """快照记忆时间戳：优先取正文内嵌日期（如「2026-04-18 23:25:」），
    否则回退 loaded_at（快照加载时刻）。"""
    m = _INLINE_DATE_RE.search(content[:200])
    if m:
        return _norm_ts(f"{m.group(1)}T{(m.group(2) or '00:00')}:00", CN_TZ)
    return _norm_ts(loaded_at, UTC)


def import_context_snapshots(kai_root: Path, persist_db: Path,
                             agent_id: str = "kai") -> Dict[str, int]:
    """workspace/session_contexts/*.json 记忆快照（HumanThinking 时代契约记忆）。

    快照本身无创建时间：有正文内嵌日期用之，否则用 loaded_at；内容级去重
    与主库共用 (agent_id, content, created_at) 键。
    """
    ctx_dir = kai_root / "workspace" / "session_contexts"
    if not ctx_dir.exists():
        return {"imported": 0, "skipped_dup": 0}
    _ensure_persist_db(persist_db)
    conn = sqlite3.connect(persist_db)
    existing = _load_existing_keys(conn)
    existing_contents = {c for (_, c, _) in existing}

    imported = dup = 0
    for fp in sorted(ctx_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for m in data.get("memories", []):
            content = (m.get("content") or "").strip()
            if not content:
                continue
            created = _ctx_created_at(content, m.get("loaded_at") or "")
            if content in existing_contents or (agent_id, content, created) in existing:
                dup += 1
                continue
            mtype, cat = TYPE_MAP.get((m.get("type") or "general").strip().lower(),
                                      ("emotional", "experience"))
            try:
                tags = json.loads(m.get("tags") or "[]") if str(m.get("tags", "")).startswith("[") else []
            except json.JSONDecodeError:
                tags = []
            meta = {"kai_source": {"db": "session_contexts", "file": fp.name,
                                   "type_raw": m.get("type"),
                                   "importance_raw": m.get("importance"),
                                   "original_session": m.get("original_session"),
                                   "loaded_at": m.get("loaded_at")}}
            _insert_memory(conn, agent_id=agent_id, content=content,
                           memory_type=mtype, category=cat,
                           importance=int(m.get("importance") or 3),
                           created_at=created, updated_at=created, tags=tags, meta=meta)
            existing_contents.add(content)
            imported += 1

    conn.commit()
    conn.close()
    return {"imported": imported, "skipped_dup": dup}


def import_reme_notes(kai_root: Path, persist_db: Path,
                      agent_id: str = "kai") -> Dict[str, int]:
    """ReMe 日记 memory/<YYYY-MM-DD>/<note>.md（跳过索引 .md 与 interests.yaml）。

    created_at 取目录日期 00:00（UTC 落点 = 当日 08:00 北京时间，日历日不变）。
    """
    mem_root = kai_root / "memory"
    if not mem_root.exists():
        return {"imported": 0}
    _ensure_persist_db(persist_db)
    conn = sqlite3.connect(persist_db)
    existing = _load_existing_keys(conn)

    imported = 0
    for day_dir in sorted(p for p in mem_root.iterdir() if p.is_dir() and _DAY_RE.fullmatch(p.name)):
        day = day_dir.name
        for fp in sorted(day_dir.glob("*.md")):
            if fp.name == "interests.yaml":
                continue
            text = fp.read_text(encoding="utf-8").strip()
            if not text:
                continue
            # frontmatter 提取 description 作为摘要；正文与去重键保持同一形态
            # （键用 text、插入用 body 会让幂等检查永远失配，靠 INSERT OR IGNORE
            # 兜底 → imported 计数假阳性）
            desc = ""
            fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
            body = text
            if fm:
                dm = re.search(r"description:\s*(.+)", fm.group(1))
                if dm:
                    desc = dm.group(1).strip()
                body = text[fm.end():].strip()
            created = _norm_ts(f"{day}T00:00:00", UTC)
            if (agent_id, body, created) in existing:
                continue
            meta = {"kai_source": {"db": "reme_notes", "file": str(fp.relative_to(kai_root))}}
            if desc:
                meta["kai_summary"] = desc
            _insert_memory(conn, agent_id=agent_id, content=body,
                           memory_type="episodic", category="experience",
                           importance=4, created_at=created, updated_at=created,
                           tags=[], meta=meta)
            existing.add((agent_id, body, created))
            imported += 1

    conn.commit()
    conn.close()
    return {"imported": imported}


def import_neural_memory_delta(src_db: Path, persist_db: Path,
                               agent_id: str = "kai") -> Dict[str, int]:
    """旧神经记忆库增量：只补内容级去重后的新条目（大部分已迁移进 qwenpaw 主库）。"""
    if not src_db.exists():
        return {"imported": 0, "skipped_dup": 0}
    _ensure_persist_db(persist_db)
    conn = sqlite3.connect(persist_db)
    existing = _load_existing_keys(conn)
    existing_contents = {c for (_, c, _) in existing}

    src = sqlite3.connect(f"file:{src_db.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute("SELECT * FROM memories ORDER BY created_at").fetchall()

    imported = 0
    for r in rows:
        if r["content"] in existing_contents:
            continue
        created = _norm_ts(r["created_at"], UTC)
        mtype, cat = TYPE_MAP.get((r["memory_type"] or "general").strip().lower(),
                                  ("episodic", "general"))
        try:
            tags = json.loads(r["tags"] or "[]") if (r["tags"] or "").startswith("[") else []
        except json.JSONDecodeError:
            tags = []
        meta = {"kai_source": {"db": "neural_memory.db", "id": r["id"],
                               "session_id": r["session_id"]}}
        _insert_memory(conn, agent_id=agent_id, content=r["content"],
                       memory_type=mtype, category=cat,
                       importance=r["importance"] or 3,
                       created_at=created, updated_at=created, tags=tags, meta=meta)
        existing_contents.add(r["content"])
        imported += 1

    conn.commit()
    conn.close()
    src.close()
    return {"imported": imported, "skipped_dup": len(rows) - imported}


# ══════════════════════════════════════════════════════════════════
# 聊天导入
# ══════════════════════════════════════════════════════════════════

# 每个源的会话命名前缀（防跨源 session_id 冲突）
SRC_PREFIX = {"legacy": "kai-legacy", "dialog": "kai-dialog", "history": "kai-history"}


def _dedup_key(m: Dict[str, Any]) -> Tuple[str, str, str]:
    """会话消息幂等键：(源, 源时间戳, 角色+正文摘要哈希)。

    2.x 轮内各行共享 created_at，纯 ts 键在多 model_turn 同 ts 时会误吞消息，
    追加角色+正文哈希兜底。
    """
    ki = m.get("metadata", {}).get("kai_import", {})
    digest = hashlib.sha1(
        f"{m.get('role')}|{m.get('content', '')}".encode("utf-8")
    ).hexdigest()[:10]
    return (ki.get("source", ""), ki.get("ts", ""), digest)


def _derive_title(msgs: List[Dict[str, Any]]) -> str:
    """从首条用户消息派生可读标题；剥掉 untrusted metadata 包装块。"""
    for m in msgs:
        if m.get("role") != "user":
            continue
        text = m.get("content", "")
        if text.startswith("[cron:"):
            inner = text.split("]", 1)[0].replace("[cron:", "").strip()
            inner = re.sub(r"^[0-9a-f-]{36}\s*", "", inner)
            return ("[自进化] " + (inner or "定时任务"))[:40]
        skip_wrap = False
        for ln in text.splitlines():
            s = ln.strip()
            if s.startswith("```json"):
                skip_wrap = True
                continue
            if skip_wrap:
                if s == "```":
                    skip_wrap = False
                continue
            if not s or s.startswith(("Conversation info", "Sender (", "System (")):
                continue
            return s[:40]
    return "凯（导入）"


class _SessionWriter:
    """按日期分文件写 sessions/{agent}/session_{sid}_{date}.json，幂等。"""

    def __init__(self, agent_dir: Path, agent_id: str):
        self.agent_dir = agent_dir
        self.agent_id = agent_id
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}  # file_path → session_data
        self._existing_keys: Dict[str, set] = {}     # file_path → {(source, ts)}

    def _load(self, fp: Path) -> Optional[Dict[str, Any]]:
        if fp in self._cache:
            return self._cache[fp]
        if fp.exists():
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
            self._cache[fp] = data
            return data
        return None

    def append(self, session_id: str, msgs: List[Dict[str, Any]]) -> int:
        """把已按时间排序的消息按日期分桶落盘；返回实际新增条数。"""
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for m in msgs:
            by_date.setdefault(_msg_date(m["timestamp"]), []).append(m)
        written = 0
        for date, day_msgs in sorted(by_date.items()):
            fp = self.agent_dir / f"session_{session_id}_{date}.json"
            data = self._load(fp)
            if data is None:
                data = {
                    "agent_id": self.agent_id, "session_id": session_id,
                    "session_date": date, "messages": [],
                    "created_at": day_msgs[0]["timestamp"],
                    "total_messages": 0,
                }
                # 不写 user_id 字段：对齐 pipeline 原生落盘口径（mem_core.save_to_session
                # → add_message 不带 user_id），空值在 _collect_summaries 不过滤，
                # 任意登录用户均可见；写死 "anonymous"/"1" 反而会被按用户过滤拦掉。
                if day_msgs[0].get("metadata", {}).get("kai_import"):
                    data["title"] = _derive_title(
                        [m for m in msgs if _msg_date(m["timestamp"]) == date]
                        or day_msgs
                    )
            seen = self._existing_keys.setdefault(
                str(fp), {_dedup_key(m) for m in data.get("messages", [])}
            )
            for m in day_msgs:
                k = _dedup_key(m)
                if k in seen:
                    continue
                data["messages"].append(m)
                seen.add(k)
                written += 1
            if written and data["messages"]:
                data["messages"].sort(key=lambda x: x["timestamp"])
                data["updated_at"] = data["messages"][-1]["timestamp"]
                data["total_messages"] = len(data["messages"])
                fp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")
                self._cache[str(fp)] = data
        return written


def _extract_text(content: Any) -> str:
    """兼容入口：只要正文（旧调用方）。"""
    return _split_blocks(content)[0]


def _iter_legacy_sessions(sessions_dir: Path) -> Iterable[Tuple[str, List[Dict[str, Any]]]]:
    """QwenPaw 1.x workspace/sessions/*.jsonl → (会话名, 消息列表[已排序])。

    thinking 块 → metadata.reasoning_content；toolCall 块 → metadata.tool_calls
    （1.x 日志无工具结果，call-only）；纯工具轮保留为空正文消息。
    """
    if not sessions_dir.exists():
        return
    for fp in sorted(sessions_dir.glob("*.jsonl")):
        if ".deleted." in fp.name:
            continue
        msgs: List[Dict[str, Any]] = []
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "message":
                continue
            inner = d.get("message") or {}
            role = inner.get("role")
            if role not in ("user", "assistant"):
                continue
            ts = _utc_to_cn(d["timestamp"])  # Z=UTC → +08:00
            if role == "assistant":
                text, reasoning, calls = _split_blocks(inner.get("content"))
                for c in calls:
                    c["timestamp"] = ts
                if not (text.strip() or reasoning.strip() or calls):
                    continue
                msgs.append(_mk_msg(role, text, ts, "legacy", d["timestamp"],
                                    reasoning=reasoning, tool_calls=calls))
            else:
                text = _extract_text(inner.get("content"))
                if not text.strip():
                    continue
                msgs.append(_mk_msg(role, text, ts, "legacy", d["timestamp"]))
        msgs.sort(key=lambda x: x["timestamp"])
        yield fp.stem, msgs


def _iter_dialog_files(dialog_dir: Path) -> Iterable[Tuple[str, List[Dict[str, Any]]]]:
    """每日对话 jsonl（workspace/dialog）→ (会话名, 消息列表)。

    thinking 块 → metadata.reasoning_content（dialog 源无工具块）。
    """
    if not dialog_dir.exists():
        return
    for fp in sorted(dialog_dir.glob("*.jsonl")):
        day = fp.stem  # 2026-04-06
        msgs: List[Dict[str, Any]] = []
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = d.get("role")
            if role not in ("user", "assistant"):
                continue
            raw_ts = d.get("timestamp") or f"{day} 00:00:00"
            ts = _norm_ts(raw_ts, CN_TZ)  # 本地时间 → 显式 +08:00
            if role == "assistant":
                text, reasoning, calls = _split_blocks(d.get("content"))
                if not (text.strip() or reasoning.strip() or calls):
                    continue
                msgs.append(_mk_msg(role, text, ts, "dialog", raw_ts,
                                    name=d.get("name") or "",
                                    reasoning=reasoning, tool_calls=calls))
            else:
                text = _extract_text(d.get("content"))
                if not text.strip():
                    continue
                msgs.append(_mk_msg(role, text, ts, "dialog", raw_ts,
                                    name=d.get("name") or ""))
        msgs.sort(key=lambda x: x["timestamp"])
        yield day.replace("-", ""), msgs


def _parse_blocks_thinking(blocks_raw: Optional[str]) -> str:
    """2.x model_turn blocks JSON → thinking 全文。"""
    if not blocks_raw:
        return ""
    try:
        arr = json.loads(blocks_raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    parts = [b.get("thinking", "") for b in arr
             if isinstance(b, dict) and b.get("type") == "thinking" and b.get("thinking")]
    return "\n".join(parts)


def _parse_tool_input(tool_input: Optional[str]) -> Dict[str, Any]:
    """2.x tool_input JSON 字符串 → params dict；解析失败保底为 raw。"""
    if not tool_input:
        return {}
    try:
        v = json.loads(tool_input)
        return v if isinstance(v, dict) else {"raw": v}
    except (json.JSONDecodeError, TypeError):
        return {"raw": tool_input}


def _iter_history_db(db_path: Path) -> Iterable[Tuple[str, List[Dict[str, Any]]]]:
    """QwenPaw 2.x history.db → 按会话输出消息。

    契约（2026-09-09 升级）：
    - context_msg/user → user 消息
    - model_turn（有正文）→ assistant 消息；blocks thinking → reasoning_content；
      tool_call_id+tool_input+name → tool_call 条目（真实参数）
    - tool_result 行 → tool_result 条目，追加到本轮 assistant 消息的 tool_calls：
      tool_call_id 与某个 call 匹配则配对（result 紧随其 call，满足前端
      「result 挂到最近 call」语义），无匹配 call 的结果补一条 params={} 的
      占位 call（2.x 只记结果不记参数，避免前端连续 result 相互覆盖丢数据）
    - 空正文纯工具 model_turn（仅 21 行有此形态）的 call 顺延挂到下一条
      assistant 正文消息
    - 轮内各行共享 created_at，seq 为轮内唯一顺序
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT session_id, kind, role, name, content, tool_call_id, tool_input,"
        " blocks, created_at FROM conversation_history ORDER BY created_at, seq"
    ).fetchall()
    conn.close()

    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)

    for sid, srows in by_session.items():
        msgs: List[Dict[str, Any]] = []
        pending_calls: List[Dict[str, Any]] = []   # 空正文轮顺延的 call 条目
        current: Optional[Dict[str, Any]] = None   # 待落地的 assistant 消息

        def _flush() -> None:
            nonlocal current
            if current is None:
                return
            md = current["metadata"]
            if not md.get("tool_calls"):
                md.pop("tool_calls", None)
            msgs.append(current)
            # nonlocal 只声明变量绑定，dict 原地清空由外层负责
            # （current 置 None 在调用处）

        def _attach_result(entry: Dict[str, Any]) -> None:
            """把 tool_result 条目接到 current（或 pending）的调用序列。"""
            calls = (current["metadata"]["tool_calls"]
                     if current is not None else pending_calls)
            for i in range(len(calls) - 1, -1, -1):
                c = calls[i]
                if c.get("type") == "tool_call" and not c.get("_matched"):
                    cid = c.get("_id")
                    rid = entry.get("_rid")
                    if cid is None or rid is None or cid == rid:
                        c["_matched"] = True
                        calls.append(entry)
                        return
            # 无可配对 call → 占位 call（2.x 结果行不带参数）
            placeholder = {"type": "tool_call", "tool_name": entry.get("tool_name", ""),
                           "params": {}, "_matched": True}
            calls.append(placeholder)
            calls.append(entry)

        for r in srows:
            kind = r["kind"]
            ts = _norm_ts(r["created_at"], CN_TZ)
            if kind == "context_msg":
                _flush()
                current = None
                if (r["role"] or "").strip() == "user":
                    text = (r["content"] or "").strip()
                    if text:
                        msgs.append(_mk_msg("user", text, ts, "history",
                                            r["created_at"]))
                continue
            if kind == "model_turn":
                text = (r["content"] or "").strip()
                reasoning = _parse_blocks_thinking(r["blocks"])
                own_call = None
                if r["tool_call_id"]:
                    own_call = {"type": "tool_call", "tool_name": r["name"] or "",
                                "params": _parse_tool_input(r["tool_input"]),
                                "timestamp": ts, "_id": r["tool_call_id"]}
                if text:
                    _flush()
                    calls = pending_calls + ([own_call] if own_call else [])
                    md: Dict[str, Any] = {"kai_import": {"source": "history",
                                                         "ts": r["created_at"]}}
                    if reasoning:
                        md["reasoning_content"] = reasoning
                    if calls:
                        md["tool_calls"] = calls
                    current = {"role": "assistant", "content": text,
                               "timestamp": ts, "metadata": md}
                    pending_calls = []
                elif own_call:
                    pending_calls.append(own_call)
                continue
            if kind == "tool_result":
                text = r["content"] or ""
                if not text.strip():
                    continue
                _attach_result({"type": "tool_result", "tool_name": r["name"] or "",
                                "result": _truncate_result(text),
                                "timestamp": ts, "_rid": r["tool_call_id"]})

        _flush()
        for m in msgs:
            for c in m.get("metadata", {}).get("tool_calls", []):
                c.pop("_id", None)
                c.pop("_rid", None)
                c.pop("_matched", None)
        yield sid, msgs


def import_chats(kai_root: Path, sessions_dir: Path, agent_id: str = "kai") -> Dict[str, int]:
    """三源聊天导入主入口。返回统计。"""
    agent_dir = sessions_dir / agent_id
    writer = _SessionWriter(agent_dir, agent_id)
    kai_root = Path(kai_root)

    total = 0
    sessions_seen = set()
    legacy_n = dialog_n = hist_n = 0

    for name, msgs in _iter_legacy_sessions(kai_root / "workspace" / "sessions"):
        sid = f"{SRC_PREFIX['legacy']}-{_safe_name(name)}"
        n = writer.append(sid, msgs)
        total += n
        if n:
            legacy_n += 1
        sessions_seen.add(sid)

    for name, msgs in _iter_dialog_files(kai_root / "workspace" / "dialog"):
        sid = f"{SRC_PREFIX['dialog']}-{name}"
        n = writer.append(sid, msgs)
        total += n
        if n:
            dialog_n += 1
        sessions_seen.add(sid)

    for sid_raw, msgs in _iter_history_db(kai_root / "history.db"):
        sid = f"{SRC_PREFIX['history']}-{_safe_name(sid_raw)}"
        n = writer.append(sid, msgs)
        total += n
        if n:
            hist_n += 1
        sessions_seen.add(sid)

    return {
        "messages_written": total,
        "legacy_sessions": legacy_n,
        "dialog_sessions": dialog_n,
        "history_db_sessions": hist_n,
        "total_sessions": len(sessions_seen),
    }


# ══════════════════════════════════════════════════════════════════
# 身份文件
# ══════════════════════════════════════════════════════════════════


def import_identity(kai_root: Path, workspace: Path) -> Dict[str, int]:
    """SOUL.md → memory/soul.md；PROFILE.md → memory/personality.md + 根留档；
    MEMORY.md → 根留档。全部覆盖式同步（源即真相）。"""
    kai_root = Path(kai_root)
    workspace = Path(workspace)
    mem_dir = workspace / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    files = 0

    mapping = [
        (kai_root / "SOUL.md", mem_dir / "soul.md"),
        (kai_root / "PROFILE.md", mem_dir / "personality.md"),
        (kai_root / "PROFILE.md", workspace / "PROFILE.md"),
        (kai_root / "MEMORY.md", workspace / "MEMORY.md"),
    ]
    for src, dst in mapping:
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            files += 1
    return {"files": files}


# ══════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════


def main() -> int:
    ap = argparse.ArgumentParser(description="Kai → Neurova 记忆与聊天导入")
    ap.add_argument("--kai-root", default="E:/项目/Kai")
    ap.add_argument("--neurova-root", default="E:/项目/Neurova")
    ap.add_argument("--agent-id", default="kai")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-memories", action="store_true")
    ap.add_argument("--skip-chats", action="store_true")
    ap.add_argument("--skip-identity", action="store_true")
    args = ap.parse_args()

    kai_root = Path(args.kai_root)
    nv_root = Path(args.neurova_root)
    mem_dir = nv_root / "agent_workspaces" / args.agent_id / "memory"
    persist_db = mem_dir / "neurova_memories_persist.db"
    sessions_dir = nv_root / "sessions"

    print(f"Kai 源: {kai_root}")
    print(f"Neurova 目标: agent={args.agent_id} persist={persist_db}")

    if not args.skip_memories:
        stats = import_memories(
            kai_root / "workspace" / "memory" / "human_thinking_memory_Kai.db",
            persist_db, agent_id=args.agent_id,
        )
        print(f"[记忆主库] {stats}")
        delta = import_neural_memory_delta(
            kai_root / "workspace" / "memory" / "neural_memory.db",
            persist_db, agent_id=args.agent_id,
        )
        print(f"[神经记忆增量] {delta}")
        ctx = import_context_snapshots(kai_root, persist_db, agent_id=args.agent_id)
        print(f"[会话记忆快照] {ctx}")
        reme = import_reme_notes(kai_root, persist_db, agent_id=args.agent_id)
        print(f"[ReMe 日记] {reme}")

    if not args.skip_chats:
        chats = import_chats(kai_root, sessions_dir, agent_id=args.agent_id)
        print(f"[聊天] {chats}")

    if not args.skip_identity:
        ident = import_identity(kai_root, nv_root / "agent_workspaces" / args.agent_id)
        print(f"[身份] {ident}")

    if args.dry_run:
        print("(dry-run 模式：以上统计中记忆/聊天若为首次统计，真实执行才会落盘)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
