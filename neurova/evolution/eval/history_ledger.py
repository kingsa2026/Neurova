"""编辑历史台账 — 逐候选（含被闸拒绝的）结局 JSONL 与已证伪假设回喂。

RRSI 对齐：进化搜索的记忆。每条候选一条记录（append-only + 定点 patch），
消费面两处：
  1. 变异器提示段——已证伪假设禁止重画（render_for_prompt）；
  2. 后续增益剪枝/归因分析的数据底座。

abort 墙治理：连续 gate 拒绝（约束闸/泄漏闸）超过 4 条时，recent() 只回
最近 4 条 + 一条 {"gate_wall": N} 汇总标记——一堵拒绝墙是反馈回路不是证据。

落点：<history_dir>/<sanitize(key)>.jsonl；key 为 skill_id 等业务键。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# gate 拒绝的 reject_reason 前缀（约束闸与泄漏闸）
_GATE_PREFIXES = ("constraints:", "leak:")
# abort 墙保留条数（对齐 rrsi history.render 的"墙只留最近几条"语义）
_GATE_WALL_KEEP = 4
_KEY_SAFE = re.compile(r"[^\w.-]")
_MAX_KEY_LEN = 80
_MAX_RECORDS = 500  # 单文件有界：只留最近 500 条


def sanitize_key(key: str) -> str:
    """业务键 → 文件安全名：路径字符全部替换，限长。"""
    cleaned = _KEY_SAFE.sub("_", str(key)).strip("._") or "_"
    return cleaned[:_MAX_KEY_LEN]


class EvolutionLedger:
    """逐 artifact 的候选结局台账（多实例同目录读写安全：短小原子重写）。"""

    def __init__(self, history_dir: Path | str):
        self._dir = Path(history_dir)

    # ── 存储 ──

    def _path(self, key: str) -> Path:
        return self._dir / f"{sanitize_key(key)}.jsonl"

    def _read(self, key: str) -> list[dict]:
        path = self._path(key)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
        return records

    def _write(self, key: str, records: list[dict]) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                encoding="utf-8")
        except OSError as e:
            logger.debug("编辑历史台账落盘失败: %s", e)

    def append(self, key: str, record: dict) -> int:
        """追加一条候选记录，返回其 seq（文件内单调递增）。"""
        records = self._read(key)
        seq = (records[-1].get("seq", -1) + 1) if records else 0
        entry = {"seq": seq, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **record}
        records.append(entry)
        self._write(key, records[-_MAX_RECORDS:])
        return seq

    def patch(self, key: str, seq: int, patch: dict) -> None:
        """定点更新某条记录（如胜者回填 delta_holdout）；seq 不存在则忽略。"""
        records = self._read(key)
        for r in records:
            if r.get("seq") == seq:
                r.update(patch)
                break
        else:
            return
        self._write(key, records)

    # ── 消费面 ──

    def recent(self, key: str, n: int = 12) -> list[dict]:
        """最近 n 条记录；其中任何超过保留额的连续 gate 拒绝墙压缩为
        最近 4 条 + 汇总标记 {"gate_wall": 墙长}（紧跟在被压缩墙之后）。"""
        records = self._read(key)[-n:]
        out: list[dict] = []
        run: list[dict] = []

        def _flush_run() -> None:
            nonlocal run
            if not run:
                return
            if len(run) > _GATE_WALL_KEEP:
                out.extend(run[-_GATE_WALL_KEEP:])
                out.append({"gate_wall": len(run)})
            else:
                out.extend(run)
            run = []

        for r in records:
            if r.get("accepted") is False and str(r.get("reject_reason", "")).startswith(_GATE_PREFIXES):
                run.append(r)
            else:
                _flush_run()
                out.append(r)
        _flush_run()
        return out

    @staticmethod
    def render_for_prompt(records: list[dict]) -> str:
        """渲染变异器提示段：已证伪假设禁止重画；已生效假设避免无谓重复。
        空记录（或只有墙标记）返回空串——提示词与旧版同形。"""
        real = [r for r in records if r.get("hypothesis")]
        wall = sum(r.get("gate_wall", 0) for r in records if "gate_wall" in r)
        falsified = [r for r in real if r.get("accepted") is False]
        accepted = [r for r in real if r.get("accepted")]
        if not falsified and not accepted and not wall:
            return ""
        lines: list[str] = ["【编辑历史】以下假设已在评测中实测："]
        if falsified:
            lines.append("已实测无效——**禁止重复提出**同类假设：")
            for r in falsified[-8:]:
                why = f"（拒绝原因: {r['reject_reason']}）" if r.get("reject_reason") else ""
                lines.append(f"- [{r.get('ts', '')}] {r['hypothesis']}{why}")
        if accepted:
            lines.append("已生效（勿做无谓回退）：")
            for r in accepted[-4:]:
                lines.append(f"- [{r.get('ts', '')}] {r['hypothesis']}")
        if wall:
            lines.append(f"另有 {wall} 条候选被闸门连续拒绝（摘要略）。")
        return "\n".join(lines)
