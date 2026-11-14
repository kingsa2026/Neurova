"""OTLP/HTTP JSON 负载构造与导出（P2-13）。

只依赖标准库（urllib）：自托管 Neurova 不该为遥测引重依赖。
负载为 OTLP logs 服务的 JSON 编码（``resourceLogs``/``scopeLogs``/``logRecords``），
导出失败由调用方计数（fail-open），本模块不重试不阻塞。
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def buildOtlpLogsPayload(entries: List[Dict[str, Any]], serviceName: str) -> Dict[str, Any]:
    """把脱敏后的条目编成 OTLP logs JSON 负载。

    条目约定字段：``error_type``/``message``/``timestamp``（其余键进 attributes）。
    """
    records: List[Dict[str, Any]] = []
    now_nano = time.time_ns()
    for entry in entries:
        body = json.dumps(entry, ensure_ascii=False, default=str)
        attributes = []
        for key, value in entry.items():
            if key in ("error_type", "message", "timestamp"):
                continue
            attributes.append({"key": str(key), "value": {"stringValue": str(value)}})
        records.append(
            {
                "timeUnixNano": str(now_nano),
                "observedTimeUnixNano": str(now_nano),
                "severityText": "ERROR",
                "body": {"stringValue": body},
                "attributes": attributes,
            }
        )
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": serviceName}}]
                },
                "scopeLogs": [
                    {"scope": {"name": "neurova.telemetry"}, "logRecords": records}
                ],
            }
        ]
    }


def exportOtlpLogs(endpoint: str, payload: Dict[str, Any], timeout: float = 3.0) -> bool:
    """POST OTLP 负载到 ``endpoint``；2xx 视为成功。失败仅记 debug（fail-open）。"""
    if not endpoint:
        return False
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception as e:  # noqa: BLE001 - 网络失败由调用方计数，不抛
        logger.debug("OTLP 导出失败（fail-open）: %s", e)
        return False
