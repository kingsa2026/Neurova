# -*- coding: utf-8 -*-
"""AIGC 生成任务持久账本（B2-b，QwenPaw 对齐）。

已提交的异步生成任务（视频为主）落盘 JSON，重启后可恢复轮询——
结果 URL 临时有效（Ark 24h / BFL 10min），成功后必须立即下载本地化。

线程安全 + 原子写（tmp→replace）；默认 data/generation_tasks.json。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_LEDGER_PATH = Path("data") / "generation_tasks.json"


@dataclass
class TaskRecord:
    """一条已提交的生成任务。"""

    task_id: str = ""
    kind: str = "video"  # image / video
    provider_id: str = ""
    protocol: str = ""
    model: str = ""
    base_url: str = ""
    status: str = "submitted"  # submitted / running / succeeded / failed
    remote_task_id: str = ""
    poll_url: str = ""
    result_url: str = ""
    local_path: str = ""
    error: str = ""
    prompt: str = ""
    submitted_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GenerationTaskLedger:
    """JSON 落盘的任务账本。"""

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path) if path else DEFAULT_LEDGER_PATH
        self._lock = threading.RLock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.is_file():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._tasks = data
        except Exception as e:  # noqa: BLE001 — 账本损坏不阻断服务
            logger.warning("任务账本加载失败（%s）：以空账本启动", e)
            self._tasks = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._tasks, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except Exception as e:  # noqa: BLE001
            logger.warning("任务账本写盘失败: %s", e)

    def add(self, record: TaskRecord) -> TaskRecord:
        if not record.task_id:
            record.task_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._tasks[record.task_id] = record.to_dict()
            self._save()
        return record

    def update(self, task_id: str, **fields: Any) -> Optional[TaskRecord]:
        with self._lock:
            entry = self._tasks.get(task_id)
            if entry is None:
                return None
            for key, value in fields.items():
                if key in entry:
                    entry[key] = value
            entry["updated_at"] = time.time()
            self._save()
            return TaskRecord(**entry)

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            entry = self._tasks.get(task_id)
            return TaskRecord(**entry) if entry else None

    def list(self, status: Optional[str] = None) -> List[TaskRecord]:
        with self._lock:
            entries = list(self._tasks.values())
        if status:
            entries = [e for e in entries if e.get("status") == status]
        entries.sort(key=lambda e: e.get("submitted_at", 0), reverse=True)
        return [TaskRecord(**e) for e in entries]

    def unfinished(self) -> List[TaskRecord]:
        """submitted/running 状态任务（重启恢复轮询的数据源）。"""
        with self._lock:
            entries = [
                e for e in self._tasks.values()
                if e.get("status") in ("submitted", "running") and e.get("remote_task_id")
            ]
        return [TaskRecord(**e) for e in entries]


_ledger: Optional[GenerationTaskLedger] = None
_ledger_lock = threading.Lock()


def get_generation_task_ledger() -> GenerationTaskLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = GenerationTaskLedger()
    return _ledger


def reset_generation_task_ledger() -> None:
    global _ledger
    with _ledger_lock:
        _ledger = None
