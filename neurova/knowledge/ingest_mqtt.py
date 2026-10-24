"""入站作业的 MQTT 传输（可选，跨进程/多节点）。

生产者把 `{dedupe_key, payload}` 发到 `kb/ingest/wecom/jobs`；消费者订阅后
写入本地 SQLite 入站队列，由常驻 worker 处理，结果回 `kb/ingest/result`。
未装 paho 或未启用时保持进程内路径，不静默降级。
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

TRANSPORT_ENV = "NEUROVA_KB_INGEST_TRANSPORT"
JOB_TOPIC = "kb/ingest/wecom/jobs"
RESULT_TOPIC = "kb/ingest/result"
QOS = 1


class MqttIngestTransport:
    def __init__(
        self,
        client: Any = None,
        *,
        host: str = "",
        port: int = 0,
        username: str = "",
        password: str = "",
        jobTopic: str = JOB_TOPIC,
        resultTopic: str = RESULT_TOPIC,
    ) -> None:
        self._client = client
        self._host = host or os.environ.get("NEUROVA_MQTT_HOST") or "127.0.0.1"
        self._port = int(port or os.environ.get("NEUROVA_MQTT_PORT") or 1883)
        self._username = username or os.environ.get("NEUROVA_MQTT_USERNAME") or ""
        self._password = password or os.environ.get("NEUROVA_MQTT_PASSWORD") or ""
        self._jobTopic = jobTopic
        self._resultTopic = resultTopic
        self._handler: Optional[Callable[[Dict[str, Any]], None]] = None
        self._connected = False

    def _ensureClient(self) -> Any:
        if self._client is not None:
            try:
                self._client.on_message = self._onMessage
            except Exception:  # noqa: BLE001
                pass
            return self._client
        try:
            import paho.mqtt.client as mqtt
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("MQTT 入站传输需要 paho-mqtt（可选依赖）") from exc
        client = mqtt.Client()
        client.on_connect = self._onConnect
        client.on_message = self._onMessage
        if self._username:
            client.username_pw_set(self._username, self._password or None)
        client.connect(self._host, self._port, keepalive=30)
        client.loop_start()
        self._connected = True
        return client

    def _onConnect(self, client, userdata, flags, rc, *args):
        client.subscribe(self._jobTopic, qos=QOS)

    def _onMessage(self, client, userdata, message):
        try:
            body = json.loads(message.payload.decode("utf-8"))
        except (ValueError, AttributeError, UnicodeDecodeError):
            logger.warning("MQTT 入站作业不是合法 JSON，已丢弃")
            return
        handler = self._handler
        if handler is None:
            return
        try:
            handler(body)
        except Exception as exc:  # noqa: BLE001 - 单条回调失败不拖垮客户端
            logger.warning("MQTT 入站作业回调失败: %s", exc)

    def publishJob(self, dedupeKey: str, payload: Dict[str, Any]) -> None:
        client = self._ensureClient()
        body = {"dedupe_key": str(dedupeKey), "payload": payload}
        client.publish(self._jobTopic, json.dumps(body, ensure_ascii=False), qos=QOS)

    def publishResult(self, body: Dict[str, Any]) -> None:
        client = self._ensureClient()
        client.publish(self._resultTopic, json.dumps(body, ensure_ascii=False), qos=QOS)

    def subscribeJobs(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._handler = handler
        self._ensureClient()

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            logger.debug("MQTT 入站客户端关闭失败", exc_info=True)


def ingestTransportMode() -> str:
    return str(os.environ.get(TRANSPORT_ENV) or "local").strip().lower()


def buildIngestTransport() -> Optional[MqttIngestTransport]:
    """local → None（进程内）；mqtt → 传输实例（依赖缺失在发送时显式报错）。"""
    return MqttIngestTransport() if ingestTransportMode() == "mqtt" else None
