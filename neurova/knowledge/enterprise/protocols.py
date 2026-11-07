"""企业源适配器 Protocol（B14 §14.1）：把接入面固定为可测试契约。

真实连接器（DB/ERP API/事件流）另立项，必须实现同一 Protocol、输出同一
ChangeBatch、经同一 admission 写口——不得另造第二套摄取路径。
本模块只有契约与数据形状，无 IO：fetchBatch 是 async 由真实适配器实现，
核心层的 mapping/admission 是同步 SQLite 写，放 worker 线程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

#: 适配器 sourceType 白名单：注册表只收这些类型；默认不注册任何真实适配器。
#: 变体细分走描述符字段（file.format / sql.driver / erp_api.vendor / chat.vendor），
#: 闭集校验在 schema_mapping.VARIANT_CLOSED_SETS（2026-11-07 裁定 §2.3-1A）。
SOURCE_TYPES = ("sql", "erp_api", "event_stream", "file", "http_pull", "chat")


@dataclass
class SourceSchema:
    """逻辑表/列或事件 schema；只读元数据，不含凭据。"""

    sourceId: str
    sourceType: str
    tables: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SourceCursor:
    """不透明游标：由适配器解释，核心层不解析成 SQL。"""

    token: str = ""

    def isEmpty(self) -> bool:
        return not str(self.token or "").strip()


@dataclass
class ChangeBatch:
    """一批变更行。空批必须显式 `has_more=False`，不得用空列表冒充成功。"""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    nextCursor: Optional[SourceCursor] = None
    hasMore: bool = False
    fetchedAt: str = ""


@dataclass
class SourceHealth:
    """健康态：失败显式，不静默空批。"""

    status: str  # ok / degraded / error
    reason: str = ""


@runtime_checkable
class EnterpriseSourceAdapter(Protocol):
    """企业源只读适配器契约（§14.1）。"""

    async def describeSchema(self) -> SourceSchema: ...

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch: ...

    async def health(self) -> SourceHealth: ...

    async def close(self) -> None: ...
