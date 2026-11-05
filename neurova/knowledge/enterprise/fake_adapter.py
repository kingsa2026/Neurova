"""fake adapter（B14 测试替身）：进程内行集，不联网、不接真实 DB。

实现 EnterpriseSourceAdapter Protocol；游标按行偏移推进；
health 可注入故障形状供判据测。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from .protocols import ChangeBatch, SourceCursor, SourceHealth, SourceSchema


class FakeEnterpriseAdapter:
    def __init__(self, sourceId: str = "fake_src", rows: Optional[List[Dict[str, Any]]] = None,
                 healthStatus: str = "ok", healthReason: str = "",
                 failOnFetch: bool = False) -> None:
        self._sourceId = sourceId
        self._rows = list(rows or [])
        self._healthStatus = healthStatus
        self._healthReason = healthReason
        self._failOnFetch = failOnFetch
        self._offset = 0
        self.closed = False

    async def describeSchema(self) -> SourceSchema:
        return SourceSchema(sourceId=self._sourceId, sourceType="sql",
                            tables=[{"table": "orders",
                                     "columns": ["order_id", "status", "channel_code",
                                                 "updated_at"]}])

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        if self._failOnFetch:
            raise RuntimeError("源连接失败（注入）")
        offset = int(cursor.token) if cursor and cursor.token else self._offset
        batchRows = self._rows[offset:offset + int(limit)]
        nextOffset = offset + len(batchRows)
        self._offset = nextOffset
        return ChangeBatch(
            rows=batchRows,
            nextCursor=SourceCursor(token=str(nextOffset)),
            hasMore=nextOffset < len(self._rows),
            fetchedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    async def health(self) -> SourceHealth:
        return SourceHealth(status=self._healthStatus, reason=self._healthReason)

    async def close(self) -> None:
        self.closed = True
