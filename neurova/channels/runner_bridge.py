# -*- coding: utf-8 -*-
"""渠道 Runner 宿主桥（QwenPaw 对照批 A1）。

把"渠道跑在独立子进程"包成本仓既有 `ChannelAdapter` 契约：
- `RunnerHost`：拉起子进程、握手核对（协议版本/源码版本/依赖审计，
  任一不满足即 fail-closed 终止）、帧收发、崩溃观测；
- `RunnerChannelAdapter`：实现 connect/disconnect/send_message，入站事件
  经既有事件回调通道回 `ChannelManager`——manager/router/台账零改动复用；
- `ChannelProcessSupervisor`：崩溃标记与有限重启。

边界：子进程只做平台 I/O；队列、策略、Agent 执行全部留在宿主主进程
（与 `channel_router` 既有切法一致）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import subprocess
import threading
import uuid
from typing import Any, Callable, Dict, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.runner_protocol import (
    DependencyAuditError,
    FrameProtocolError,
    readFrame,
    requireSatisfied,
    writeFrame,
)
from neurova.channels.runner_spec import LaunchSpec

logger = logging.getLogger(__name__)

#: 子进程环境白名单基项：够跑 Python 与输出编码即可，其余宿主环境不外泄。
_RUNNER_ENV_BASE_KEYS = frozenset({
    "PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "HOME", "PYTHONIOENCODING",
    "NEUROVA_SOURCE_REVISION",
})


def _childEnvironment(spec: LaunchSpec) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k in _RUNNER_ENV_BASE_KEYS or k in set(spec.private_env_keys)}
    env["PYTHONPATH"] = spec.code_root + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


class RunnerHost:
    """一个渠道子进程的宿主侧句柄：拉起、握手、帧收发、崩溃观测。"""

    def __init__(
        self,
        spec: LaunchSpec,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_crash: Optional[Callable[["RunnerHost"], None]] = None,
    ):
        self.spec = spec
        self.on_event = on_event
        self.on_crash = on_crash
        self.proc: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.hello: Dict[str, Any] = {}
        self._send_waiters: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}
        self._lock = threading.Lock()
        self._closed = False

    # -- 生命周期 ------------------------------------------------------

    def start(self) -> Dict[str, Any]:
        """拉起子进程并完成握手；审计不过 fail-closed（终止进程并抛错）。"""
        self.proc = subprocess.Popen(
            [self.spec.python_executable, "-m", "neurova.channels.runner_main",
             self.spec.to_json()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_childEnvironment(self.spec), cwd=self.spec.code_root,
        )
        self.pid = self.proc.pid
        threading.Thread(target=self._drainStderr, daemon=True, name="runner-stderr").start()

        # 握手期由当前线程**独占**读 stdout（pump 线程在 ready 之后再起，
        # 否则两线程抢同一帧流，hello 会被 pump 吃掉）
        hello = readFrame(self.proc.stdout)
        try:
            requireSatisfied(hello, self.spec)
        except DependencyAuditError:
            self.terminate()  # fail-closed：带病进程立即终止
            raise
        self.hello = hello
        writeFrame(self.proc.stdin, {"op": "ready"})
        threading.Thread(target=self._pumpStdout, daemon=True, name="runner-stdout").start()
        logger.info("渠道 runner 就绪：%s pid=%s", self.spec.channel_type, self.pid)
        return hello

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def terminate(self) -> None:
        self._closed = True
        if self.proc and self.proc.poll() is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass
            self.proc.terminate()
        if self.proc:
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    # -- 帧收发 --------------------------------------------------------

    def sendRequest(self, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """向子进程发请求帧并等对应回执（req_id 配对；超时抛 TimeoutError）。"""
        req_id = uuid.uuid4().hex[:16]
        waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        with self._lock:
            self._send_waiters[req_id] = waiter
        try:
            writeFrame(self.proc.stdin, {**payload, "req_id": req_id})
            result = waiter.get(timeout=timeout)
            if result.get("ok") is False:
                raise RuntimeError(f"runner 执行失败：{result.get('error') or '未知错误'}")
            return result
        finally:
            with self._lock:
                self._send_waiters.pop(req_id, None)

    def sendRaw(self, payload: Dict[str, Any]) -> None:
        writeFrame(self.proc.stdin, payload)

    # -- 内部 ----------------------------------------------------------

    def _pumpStdout(self) -> None:
        try:
            while True:
                frame = readFrame(self.proc.stdout)
                op = frame.get("op")
                if op == "event":
                    if self.on_event:
                        try:
                            self.on_event(str(frame.get("event_type") or ""),
                                          dict(frame.get("message") or {}))
                        except Exception as e:
                            logger.warning("事件回调异常（不阻断读取）：%s", e)
                elif op in ("send_result", "pong"):
                    waiter = self._send_waiters.get(str(frame.get("req_id") or ""))
                    if waiter is not None:
                        waiter.put(frame)
                elif op == "adapter_connected":
                    logger.info("runner 内适配器已连接：%s", self.spec.channel_type)
                # 未知 op 忽略（前向兼容）
        except Exception:
            pass  # EOF/协议终止——崩溃态由 poll() 与 on_crash 呈现
        finally:
            if not self._closed and self.on_crash is not None:
                try:
                    self.on_crash(self)
                except Exception as e:
                    logger.warning("崩溃回调异常：%s", e)

    def _drainStderr(self) -> None:
        try:
            for line in self.proc.stderr:
                logger.info("[runner:%s] %s", self.spec.channel_type,
                            line.decode("utf-8", "replace").rstrip())
        except Exception:
            pass


class RunnerChannelAdapter(ChannelAdapter):
    """把 RunnerHost 包成本仓 `ChannelAdapter` 契约——manager 零改动复用。"""

    def __init__(self, config: ChannelConfig, spec: LaunchSpec):
        super().__init__(config)
        self.spec = spec
        self.host: Optional[RunnerHost] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        #: 崩溃回调（supervisor 注入；未注入时只记日志置断连态）
        self._onHostCrash: Optional[Callable[[RunnerHost], None]] = None

    async def connect(self) -> bool:
        self._loop = asyncio.get_running_loop()
        self._startHost()
        return True

    def _startHost(self) -> None:
        """同步拉起子进程并握手（async connect 与崩溃重启共用这一份）。"""

        def _onEvent(event_type: str, message: Dict[str, Any]) -> None:
            msg = ChannelMessage(
                channel_type=str(message.get("channel_type") or self.spec.channel_type),
                message_id=str(message.get("message_id") or uuid.uuid4().hex[:12]),
                sender_id=str(message.get("sender_id") or ""),
                sender_name=str(message.get("sender_name") or ""),
                content=str(message.get("content") or ""),
                message_type=str(message.get("message_type") or "text"),
                chat_id=str(message.get("chat_id") or ""),
                chat_type=str(message.get("chat_type") or "p2p"),
                raw_event=dict(message.get("raw_event") or {}),
                metadata=dict(message.get("metadata") or {}),
            )
            et = ChannelEventType(event_type) if event_type in ChannelEventType._value2member_map_ \
                else ChannelEventType.MESSAGE_RECEIVED
            if self._event_callback and self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._event_callback(et, msg), self._loop)

        def _onCrash(host: RunnerHost) -> None:
            if self._onHostCrash is not None:
                self._onHostCrash(host)
                return
            logger.error("渠道 runner 崩溃：%s pid=%s（宿主不受影响）",
                         self.spec.channel_type, host.pid)
            self._connected = False

        self.host = RunnerHost(self.spec, on_event=_onEvent, on_crash=_onCrash)
        self.host.start()
        self._connected = True

    async def disconnect(self):
        if self.host:
            self.host.terminate()
        self._connected = False

    async def send_message(self, chat_id: str, content: str,
                           message_type: str = "text", **kwargs) -> Optional[str]:
        if not self.host or not self.host.is_alive():
            raise RuntimeError(f"渠道 runner 未运行：{self.spec.channel_type}")
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self.host.sendRequest(
                {"op": "send", "chat_id": chat_id, "content": content,
                 "message_type": message_type, "kwargs": kwargs},
                timeout=30.0,
            ),
        )
        return result.get("message_id") or None


class ChannelProcessSupervisor:
    """渠道子进程监督：登记 runner 适配器，崩溃时标记并有限重启。"""

    def __init__(self, max_restarts: int = 3):
        self.max_restarts = max_restarts
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def launch(self, spec: LaunchSpec, config: ChannelConfig) -> RunnerChannelAdapter:
        """登记并返回 runner 适配器（连接由调用方 `connect()` 触发）。"""
        adapter = RunnerChannelAdapter(config, spec)
        adapter._onHostCrash = self._makeCrashHandler(spec, adapter, 0)
        self._register(spec, adapter, restarts=0)
        return adapter

    def _register(self, spec: LaunchSpec, adapter: RunnerChannelAdapter, restarts: int) -> None:
        with self._lock:
            self._entries[spec.channel_type] = {
                "spec": spec, "adapter": adapter, "restarts": restarts,
                "crashed": False,
            }

    def _makeCrashHandler(self, spec: LaunchSpec, adapter: RunnerChannelAdapter,
                          restarts: int) -> Callable[[RunnerHost], None]:
        def _handle(host: RunnerHost) -> None:
            with self._lock:
                entry = self._entries.get(spec.channel_type) or {}
                entry["crashed"] = True
                done = restarts >= self.max_restarts
                if not done:
                    entry["restarts"] = restarts + 1
            logger.error("渠道 runner 崩溃：%s（第 %s/%s 次重启判定）",
                         spec.channel_type, restarts + 1, self.max_restarts)
            if restarts < self.max_restarts:
                try:
                    fresh = RunnerChannelAdapter(adapter.config, spec)
                    fresh._loop = adapter._loop  # 事件仍回宿主原 loop
                    fresh._onHostCrash = self._makeCrashHandler(spec, fresh, restarts + 1)
                    fresh._startHost()
                    self._register(spec, fresh, restarts + 1)
                    logger.info("渠道 runner 已重启：%s", spec.channel_type)
                except Exception as e:
                    logger.error("渠道 runner 重启失败：%s（%s）", spec.channel_type, e)
        return _handle

    def status(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                key: {
                    "pid": entry["adapter"].host.pid if entry["adapter"].host else None,
                    "alive": entry["adapter"].host.is_alive() if entry["adapter"].host else False,
                    "restarts": entry.get("restarts", 0),
                    "crashed": entry.get("crashed", False),
                    "source_revision": entry["spec"].source_revision,
                }
                for key, entry in self._entries.items()
            }
