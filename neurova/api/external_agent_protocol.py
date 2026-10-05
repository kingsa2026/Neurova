# -*- coding: utf-8 -*-
"""外部 Agent 接入协议的判据层

只做**无状态判定**：版本协商、载荷上限、在线态派生。限流不在这里——
速率额度的唯一事实源是 `neurova.core.firewall`，本模块不另造第二把尺子。

由来：被退役的 `neurova/api/communication_protocol.py` 里
`max_message_size` 只在握手响应中回显、全文件从无拒绝路径，版本协商则绑在一个
零消费者的进程内状态机上。这里只把其中真正缺位的判据抽成可测的纯函数。
"""

import json
from typing import Any, Dict, List, Optional, Tuple

#: 服务端协议版本。握手回显与协商判定共用此单源，禁止在端点侧写字面量。
PROTOCOL_VERSION = "1.0"

#: 单条消息载荷的序列化字节上限（超限 → 413）。
MAX_MESSAGE_BYTES = 1024 * 1024

#: 外部 Agent 视为在线的活动窗口；达到窗口即判 idle。
ONLINE_WINDOW_SECONDS = 300


def validateProtocolVersion(supportedVersions: Optional[List[str]]) -> Tuple[bool, Optional[str]]:
    """握手版本协商。

    未声明版本按「渐进」口径放行——存量客户端不能被新判据当场打断；
    声明了却不含服务端版本才拒，并点名实际收到的版本。
    """
    if not supportedVersions:
        return True, None
    if PROTOCOL_VERSION in supportedVersions:
        return True, None
    return False, f"不支持的协议版本: {supportedVersions}（服务端协议版本 {PROTOCOL_VERSION}）"


def negotiationMode(supportedVersions: Optional[List[str]]) -> str:
    """协商结果标记：negotiated=客户端确实声明过；legacy=沉默放行。

    两者必须可区分——把沉默客户端也报成 negotiated，会让服务端以为对方协商过。
    """
    return "negotiated" if supportedVersions else "legacy"


def validateMessageSize(content: Dict[str, Any], limit: int = MAX_MESSAGE_BYTES) -> Tuple[bool, int]:
    """按序列化后的真实 UTF-8 字节数判载荷上限，返回 (是否放行, 实际字节数)。"""
    size = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    return size <= limit, size


def deriveAgentStatus(lastSeenAt: Optional[float], now: float) -> str:
    """由最近活动时间派生在线态，不额外落存储。

    现役记录曾在握手时写死 status="online" 且此后无人更新，超时判定会把所有 Agent
    集体判成离线；改为纯派生后该字段不再需要被写入（写而不读即断点）。
    """
    if not lastSeenAt or now - lastSeenAt >= ONLINE_WINDOW_SECONDS:
        return "idle"
    return "online"
