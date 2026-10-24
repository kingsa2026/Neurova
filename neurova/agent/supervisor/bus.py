"""Supervisor 与 Worker 的传输层。

- `InProcessWorkerBus`：复用 ACPRuntime 的注册/请求-响应/DLQ，单机默认；
- `MqttWorkerBus`：把同一份任务 JSON 发到 `agent/supervisor/task`，收
  `agent/worker/{id}/result`；paho 缺失时显式失败，不静默退化成"没人回"。

传输失败一律回 `WorkerResult(success=False)`，由编排层决定重试与隔离。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

from .contracts import SupervisorTask, WorkerResult

logger = get_logger(__name__)

TASK_TOPIC = "agent/supervisor/task"
RESULT_TOPIC_PATTERN = "agent/worker/+/result"
MEMORY_TOPIC = "agent/memory/update"
BUS_MODE_ENV = "NEUROVA_AGENT_BUS"


class SupervisorBusError(RuntimeError):
    """传输层配置故障（非单任务失败）。kind 供调用方如实透出。"""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


class InProcessWorkerBus:
    """进程内 Worker 总线：worker handler 注册进 ACP，supervisor 走 request/response。"""

    def __init__(self, runtime: Any = None):
        if runtime is None:
            from neurova.agent.protocols.acp_runtime import get_acp_runtime

            runtime = get_acp_runtime()
        self._runtime = runtime

    @property
    def runtime(self) -> Any:
        return self._runtime

    def register(self, workerId: str, handler: Any) -> bool:
        """handler: task dict -> dict（可 async）；返回 {success, items, result, ...}。"""
        return self._runtime.register_agent(workerId, self._wrap(handler))

    def unregister(self, workerId: str) -> bool:
        return self._runtime.unregister_agent(workerId)

    @staticmethod
    def _wrap(handler: Any) -> Any:
        async def _acpHandler(message: Any) -> Any:
            from neurova.agent.protocols.message_protocol import AgentMessage, MessageType

            payload = dict(message.data or {})
            payload.setdefault("task_id", (message.params or {}).get("task_id", ""))
            payload.setdefault("role", message.action or "retrieve")
            payload["trace_id"] = message.trace_id or ""
            try:
                outcome = handler(payload)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                if isinstance(outcome, dict):
                    data = dict(outcome)
                    data.setdefault("success", True)
                else:
                    data = {"success": True, "result": outcome}
            except Exception as exc:  # noqa: BLE001 - 单 worker 故障隔离为失败响应
                logger.warning("Worker handler 失败 (%s): %s", message.receiver_id, exc)
                data = {"success": False, "error": str(exc)}
            return AgentMessage(
                type=MessageType.TASK_RESULT,
                sender_id=message.receiver_id,
                receiver_id=message.sender_id,
                action=message.action,
                data=data,
                correlation_id=message.correlation_id,
                trace_id=message.trace_id,
            )

        return _acpHandler

    async def dispatch(self, workerId: str, task: SupervisorTask, timeout: float) -> WorkerResult:
        from neurova.agent.protocols.message_protocol import AgentMessage, MessageType

        started = time.monotonic()
        message = AgentMessage(
            type=MessageType.TASK_ASSIGNMENT,
            sender_id="supervisor",
            receiver_id=workerId,
            action=task.role or "retrieve",
            params={"task_id": task.task_id, "role": task.role},
            data=dict(task.payload),
            trace_id=task.trace_id or None,
            expires_at=time.time() + max(float(timeout), 0.001),
            max_retries=max(int(task.max_retries), 0),
        )
        reply = await self._runtime.request(message, timeout=timeout)
        duration = time.monotonic() - started
        if reply is None:
            return WorkerResult(
                task_id=task.task_id, worker_id=workerId, success=False,
                error="timeout_or_unavailable", duration=duration,
                trace_id=task.trace_id,
            )
        data = dict(reply.data or {})
        return WorkerResult(
            task_id=task.task_id,
            worker_id=workerId,
            success=bool(data.get("success")),
            items=_itemsOf(data),
            data=data,
            error=str(data.get("error") or ""),
            duration=duration,
            trace_id=task.trace_id,
        )


class MqttWorkerBus:
    """MQTT 传输：任务发到统一主题，结果按 worker 主题回传。

    `client` 可注入（测试用假客户端）；不传时惰性导入 paho，缺失即
    `SupervisorBusError(kind="dependency_missing")`——绝不把"没有消费者"
    伪装成超时。
    """

    def __init__(
        self,
        client: Any = None,
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        username: str = "",
        password: str = "",
        tlsCa: str = "",
        tlsCert: str = "",
        tlsKey: str = "",
        tlsInsecure: bool = False,
        qos: int = 1,
        taskTopic: str = TASK_TOPIC,
        resultPattern: str = RESULT_TOPIC_PATTERN,
    ):
        self._client = client
        self._host = host
        self._port = int(port)
        self._username = username
        self._password = password
        self._tlsCa = tlsCa
        self._tlsCert = tlsCert
        self._tlsKey = tlsKey
        self._tlsInsecure = bool(tlsInsecure)
        self._qos = int(qos)
        self._taskTopic = taskTopic
        self._resultPattern = resultPattern
        self._pending: Dict[str, asyncio.Future] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        self._clientInjected = client is not None

    def _ensureClient(self) -> Any:
        if self._client is not None:
            # 注入客户端（测试/外部已连接实例）只接管结果回调，不重复 connect
            try:
                self._client.on_message = self._onMessage
            except Exception:  # noqa: BLE001 - 假客户端可能不允许赋值
                pass
            self._applySecurity(self._client)
            return self._client
        try:
            import paho.mqtt.client as mqtt
        except Exception as exc:  # noqa: BLE001
            raise SupervisorBusError(
                "MQTT 传输需要 paho-mqtt（可选依赖）", kind="dependency_missing"
            ) from exc
        client = mqtt.Client()
        client.on_connect = self._onConnect
        client.on_message = self._onMessage
        self._applySecurity(client)
        client.connect(self._host, self._port, keepalive=30)
        client.loop_start()
        self._connected = True
        return client

    def _applySecurity(self, client: Any) -> None:
        if self._username:
            client.username_pw_set(self._username, self._password or None)
        if self._tlsCa or self._tlsCert or self._tlsKey:
            client.tls_set(
                ca_certs=self._tlsCa or None,
                certfile=self._tlsCert or None,
                keyfile=self._tlsKey or None,
            )
            if self._tlsInsecure:
                client.tls_insecure_set(True)

    def _onConnect(self, client, userdata, flags, rc, *args):
        client.subscribe(self._resultPattern, qos=self._qos)

    def _onMessage(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, AttributeError, UnicodeDecodeError):
            logger.warning("MQTT worker 结果不是合法 JSON，已丢弃")
            return
        taskId = str(payload.get("task_id") or "")
        if not taskId:
            return
        future = self._pending.get(taskId)
        if future is None or future.done():
            return
        loop = future.get_loop()
        loop.call_soon_threadsafe(future.set_result, payload)

    async def dispatch(self, workerId: str, task: SupervisorTask, timeout: float) -> WorkerResult:
        started = time.monotonic()
        self._loop = asyncio.get_running_loop()
        client = self._ensureClient()
        future = self._loop.create_future()
        self._pending[task.task_id] = future
        body = {
            "task_id": task.task_id,
            "trace_id": task.trace_id,
            "worker_id": workerId,
            "role": task.role,
            "payload": dict(task.payload),
            "deadline": float(task.deadline),
            "retry": int(task.max_retries),
            "reply_topic": "agent/worker/%s/result" % workerId,
        }
        try:
            client.publish(
                self._taskTopic, json.dumps(body, ensure_ascii=False), qos=self._qos
            )
            payload = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return WorkerResult(
                task_id=task.task_id, worker_id=workerId, success=False,
                error="timeout", duration=time.monotonic() - started,
                trace_id=task.trace_id,
            )
        except Exception as exc:  # noqa: BLE001 - 发布失败按单任务失败上报
            return WorkerResult(
                task_id=task.task_id, worker_id=workerId, success=False,
                error="publish_error:%s" % exc, duration=time.monotonic() - started,
                trace_id=task.trace_id,
            )
        finally:
            self._pending.pop(task.task_id, None)
        data = dict(payload or {})
        return WorkerResult(
            task_id=task.task_id,
            worker_id=workerId,
            success=bool(data.get("success")),
            items=_itemsOf(data),
            data=data,
            error=str(data.get("error") or ""),
            duration=time.monotonic() - started,
            trace_id=task.trace_id,
        )

    def publishMemoryUpdate(self, payload: Dict[str, Any]) -> None:
        """记忆更新广播（`agent/memory/update`），与任务通道分开。"""
        client = self._ensureClient()
        client.publish(MEMORY_TOPIC, json.dumps(payload, ensure_ascii=False), qos=self._qos)

    def close(self) -> None:
        if self._client is None:
            return
        try:
            if not self._clientInjected:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:  # noqa: BLE001 - 关闭失败不抛给调用方
            logger.debug("MQTT 客户端关闭失败", exc_info=True)


def buildWorkerBus(runtime: Any = None, mode: Optional[str] = None) -> Any:
    """按环境装配传输：默认进程内；`NEUROVA_AGENT_BUS=mqtt` 时走 MQTT。

    MQTT 保持可选：未装 paho 时由 `MqttWorkerBus` 显式报 `dependency_missing`，
    不会静默退化。broker 参数走同一组环境变量，不新增第二份配置体系。
    """
    import os

    selected = str(mode or os.environ.get(BUS_MODE_ENV) or "inproc").strip().lower()
    if selected in ("", "inproc", "in-process", "local"):
        return InProcessWorkerBus(runtime)
    if selected == "mqtt":
        return MqttWorkerBus(
            host=os.environ.get("NEUROVA_MQTT_HOST") or "127.0.0.1",
            port=int(os.environ.get("NEUROVA_MQTT_PORT") or 1883),
            username=os.environ.get("NEUROVA_MQTT_USERNAME") or "",
            password=os.environ.get("NEUROVA_MQTT_PASSWORD") or "",
            tlsCa=os.environ.get("NEUROVA_MQTT_TLS_CA") or "",
            tlsCert=os.environ.get("NEUROVA_MQTT_TLS_CERT") or "",
            tlsKey=os.environ.get("NEUROVA_MQTT_TLS_KEY") or "",
            tlsInsecure=str(
                os.environ.get("NEUROVA_MQTT_TLS_INSECURE") or ""
            ).lower() in ("1", "true", "on", "yes"),
            qos=int(os.environ.get("NEUROVA_MQTT_QOS") or 1),
            taskTopic=os.environ.get("NEUROVA_MQTT_TASK_TOPIC") or TASK_TOPIC,
            resultPattern=os.environ.get("NEUROVA_MQTT_RESULT_TOPIC") or RESULT_TOPIC_PATTERN,
        )
    raise SupervisorBusError(
        "未知 Agent 总线模式: %r（有效值: inproc / mqtt）" % selected,
        kind="invalid_mode",
    )


def _itemsOf(data: Dict[str, Any]) -> list:
    items = data.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []
