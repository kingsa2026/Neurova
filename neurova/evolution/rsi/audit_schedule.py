# -*- coding: utf-8 -*-
"""审计预定表（D2，survey §10.2）——独立审计只读预定时刻。

"看了测试分再挑点"是选点污染（§7.2）：审计者若能事后任选时刻取快照，
就总能挑到对自己有利的那个。本模块把审计点**预定**在迭代序列启动前：
步长固定的 checkpoint 序列落盘；事后审计只读预定时刻——表外请求被拒并
点名理由。预定时刻的快照由编排器在迭代命中时留存（sealed evidence＋
eval outcome＋cost vector 的时点封存）。

数据面：单文件 JSON（{scheduled, stride, snapshots}），env 可覆写路径
（单测零 IO 约定沿负债账本同款）；零 LLM、确定性。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 审计步长（每 N 轮一个预定时刻）——预定在序列启动前写死，运行中不改。
AUDIT_STRIDE = 10
#: 预定表长度上界（长跑部署的文件封顶）。
MAX_SCHEDULED = 50

AUDIT_SCHEDULE_ENV = "NEUROVA_RSI_AUDIT_SCHEDULE"

_LOCK = threading.Lock()


def resolve_schedule_path() -> Optional[Path]:
    env_path = os.environ.get(AUDIT_SCHEDULE_ENV)
    return Path(env_path) if env_path else None


class AuditSchedule:
    """预定表＋时点封存（单文件；env 未配置走进程内态）。"""

    def __init__(self, path: Optional[Path] = None, *, stride: int = AUDIT_STRIDE):
        self._path = path
        self._stride = max(1, int(stride))
        self._scheduled: List[int] = list(range(self._stride,
                                                self._stride * (MAX_SCHEDULED + 1),
                                                self._stride))
        self._snapshots: Dict[int, Dict[str, Any]] = {}
        if self._path is not None and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._scheduled = list(data.get("scheduled") or self._scheduled)
                self._snapshots = {int(k): v for k, v in
                                   (data.get("snapshots") or {}).items()}
            except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning("审计预定表读取失败，按新表处理: %s", e)

    def isScheduled(self, iteration_count: int) -> bool:
        return int(iteration_count) in self._scheduled

    def recordSnapshot(self, iteration_count: int, snapshot: Dict[str, Any]) -> bool:
        """命中预定时刻时封存快照；表外时刻拒绝（选点污染防线）。"""
        count = int(iteration_count)
        if not self.isScheduled(count):
            return False
        with _LOCK:
            self._snapshots[count] = dict(snapshot or {})
            if self._path is not None:
                self._write()
            return True

    def readAuditSnapshot(self, iteration_count: int) -> Dict[str, Any]:
        """独立审计读点：**只读预定时刻**——表外请求被拒并点名理由。"""
        count = int(iteration_count)
        if not self.isScheduled(count):
            raise KeyError(
                f"迭代 {count} 不在预定审计表（步长 {self._stride}）——"
                "事后挑点是选点污染（§7.2），只读预定时刻")
        snapshot = self._snapshots.get(count)
        if snapshot is None:
            return {
                "state": "unevidenced",
                "reason": f"预定时刻 {count} 尚未到达（迭代还没跑到）",
            }
        return {"state": "measured", "iteration": count, "snapshot": snapshot}

    def scheduledPoints(self) -> List[int]:
        return list(self._scheduled)

    def _write(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"scheduled": self._scheduled, "stride": self._stride,
                        "snapshots": {str(k): v for k, v in self._snapshots.items()}},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def resolve_audit_schedule() -> AuditSchedule:
    return AuditSchedule(resolve_schedule_path())
