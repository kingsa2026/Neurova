"""脚本化工作流 journal（P3-14）：追加式 JSONL，重放/续跑的事实源。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class WorkflowJournal:
    """每次脚本执行一个 JSONL（<data>/workflow_journals/<run_id>.jsonl）。"""

    def __init__(self, runId: str):
        from neurova.core.data_root import resolveDataPath

        safe = "".join(c for c in str(runId) if c.isalnum() or c in "-_")[:80] or "run"
        self.runId = safe
        self.path = resolveDataPath("workflow_journals") / f"{safe}.jsonl"
        self._lock = threading.RLock()

    def append(self, row: Dict[str, Any]) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
            except Exception as e:  # noqa: BLE001 - journal 故障不阻断执行
                logger.warning("工作流 journal 落盘失败（run=%s）: %s", self.runId, e)

    def readRows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not self.path.exists():
            return rows
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
