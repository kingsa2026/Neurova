# -*- coding: utf-8 -*-
"""attempt 生命周期账本（R2，参照系 ad 追平批一）。

一次逻辑请求（chat/chat_stream）内的每次 (provider, model) 尝试记一条
AttemptRecord，结局五态封闭：
- COMPLETED：拿到有效载荷（内容/推理/工具调用任一）
- EMPTY：上游正常收流但零载荷（空响应——按可切换失败处理）
- INTERRUPTED：已吐出可见内容后中流死亡
- CANCELLED：消费方放弃/取消（预留；消费方中断路径本期未单独标定）
- FAILED：首可见内容前死亡

可见性：请求结束后挂在该客户端实例的 ``_lastAttemptLedger`` 上可查；
每次尝试的成败/错误类仍经既有 _archiveRequestAttempt 单点入档（不新造
第二套账）。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import List


class AttemptOutcome(enum.Enum):
    """单次尝试的结局（封闭集）。"""

    COMPLETED = "completed"
    EMPTY = "empty"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class AttemptRecord:
    """一次 (provider, model) 尝试的记录。"""

    index: int
    provider_id: str
    model: str
    outcome: AttemptOutcome = AttemptOutcome.FAILED
    error_kind: str = ""
    error_summary: str = ""
    started_at: float = field(default_factory=time.time)
    duration_ms: int = 0
    first_token_ms: int = 0


class AttemptLedger:
    """请求级 attempt 序列账本（每条逻辑请求一个实例）。"""

    def __init__(self) -> None:
        self.records: List[AttemptRecord] = []

    def start(self, client) -> AttemptRecord:
        """记录一次尝试开始（按序号追加）。

        client 按防御式提取（与 _archiveRequestAttempt 同契约）：观测面
        绝不因客户端形态（如闸门/指标测试的裸桩）炸掉调用链。
        """
        record = AttemptRecord(
            index=len(self.records),
            provider_id=str(getattr(getattr(client, "provider", None), "id", "") or ""),
            model=str(getattr(client, "model", "") or ""),
        )
        self.records.append(record)
        return record

    def finish(
        self,
        record: AttemptRecord,
        outcome: AttemptOutcome,
        *,
        error_kind: str = "",
        error_summary: str = "",
        duration_ms: int = 0,
        first_token_ms: int = 0,
    ) -> AttemptRecord:
        """落定一次尝试的结局。"""
        record.outcome = outcome
        record.error_kind = error_kind
        record.error_summary = error_summary
        record.duration_ms = duration_ms
        record.first_token_ms = first_token_ms
        return record

    @property
    def outcomes(self) -> List[str]:
        """按序的结局值列表（测试与读面用）。"""
        return [record.outcome.value for record in self.records]
