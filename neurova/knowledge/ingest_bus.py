"""知识入站事件总线：MQTT 主题契约 + 进程内兜底。

生产可接 MQTT；未配置 broker 时保留进程内发布/订阅，测试与单机部署不依赖外部服务。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

KB_INGEST_WECOM_TOPIC = "kb/ingest/wecom"
KB_INGEST_RESULT_TOPIC = "kb/ingest/result"
KB_CONFLICT_NOTIFY_TOPIC = "kb/conflict/notify"


class KnowledgeIngestBus:
    """最小发布/订阅面；handler 同步调用，异常不打断其它订阅者。"""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: Dict[str, Any]) -> int:
        with self._lock:
            handlers = list(self._subs.get(topic, []))
        delivered = 0
        for handler in handlers:
            try:
                handler(dict(payload))
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - 单订阅者故障不打断其它
                logger.warning("知识总线订阅者失败 topic=%s: %s", topic, exc)
        return delivered

    def subscriberCount(self, topic: Optional[str] = None) -> int:
        """订阅者数：审计面用它区分"没人消费"与"消费失败"。"""
        with self._lock:
            if topic is None:
                return sum(len(handlers) for handlers in self._subs.values())
            return len(self._subs.get(topic, []))

    @staticmethod
    def encode(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)


_bus: Optional[KnowledgeIngestBus] = None
_bus_lock = threading.Lock()


def get_ingest_bus() -> KnowledgeIngestBus:
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = KnowledgeIngestBus()
        return _bus
