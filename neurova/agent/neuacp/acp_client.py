# -*- coding: utf-8 -*-
"""NeuacpClient：ACP v1 JSON-RPC over stdio 客户端。

职责（设计文档 §4.3）：子进程拉起（环境白名单）、换行分隔 JSON-RPC 2.0
帧收发（UTF-8、单帧上限 fail-closed）、initialize 版本协商（不兼容即
terminate）、request 按 id 配对、通知回调（session/update 等）、崩溃
回调、terminate。帧内协议是 ACP；帧层/监督骨架对齐 channels/runner_bridge。
"""
import json
import os
import queue
import subprocess
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional

_DEFAULT_FRAME_LIMIT = 1_000_000
_DEFAULT_REQUEST_TIMEOUT = 30.0
_TERMINATE_WAIT_S = 5.0

# 子进程环境白名单：只带运行必需键，宿主代理变量（HTTP_PROXY 等）天然被排除。
_BASE_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "PROGRAMFILES",
    "ALLUSERSPROFILE",
    "HOME",
    "PYTHONIOENCODING",
)


class NeuacpError(Exception):
    """外部代理接入层基础错误。"""


class NeuacpProtocolError(NeuacpError):
    """协议帧/握手/版本错误（fail-closed 类）。"""


class NeuacpTimeoutError(NeuacpError):
    """请求超时。"""


class NeuacpClient:
    """驱动一个外部 ACP agent 子进程（stdio JSON-RPC 2.0）。

    on_event(method, params)：收到 agent 通知（如 session/update）时回调。
    on_crash(reason)：进程退出/EOF/坏帧等 fail-closed 事件回调（正常
    terminate 不触发）。
    """

    def __init__(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env_extra: Optional[Dict[str, str]] = None,
        on_event: Optional[Callable[[str, dict], None]] = None,
        on_crash: Optional[Callable[[str], None]] = None,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
        frame_limit: int = _DEFAULT_FRAME_LIMIT,
    ) -> None:
        self._command = [str(part) for part in command]
        self._cwd = cwd
        self._env_extra = dict(env_extra or {})
        self._on_event = on_event
        self._on_crash = on_crash
        self._request_timeout = request_timeout
        self._frame_limit = frame_limit

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._next_id = 0
        self._waiters: Dict[int, "queue.Queue"] = {}
        self._closed = False
        self._crash_reported = False
        self._stderr_tail: deque = deque(maxlen=50)
        self._write_lock = threading.Lock()
        self._request_handlers: Dict[str, Callable[[dict], dict]] = {}

    # ---------- 生命周期 ----------

    def start(self, *, protocol_version: str = "1", client_capabilities: Optional[dict] = None) -> dict:
        """拉起子进程并完成 initialize 握手；版本不兼容 fail-closed。"""
        if self._process is not None:
            raise NeuacpError("NeuacpClient already started")
        env = self._childEnvironment()
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self._cwd,
            )
        except OSError as exc:
            self._process = None
            raise NeuacpError(f"无法启动外部代理进程: {exc}") from exc

        self._startPumps()
        try:
            result = self.request(
                "initialize",
                {"protocolVersion": protocol_version, "clientCapabilities": client_capabilities or {}},
            )
        except NeuacpError:
            self.terminate()
            raise
        remote_version = str((result or {}).get("protocolVersion", ""))
        if remote_version != protocol_version:
            self.terminate()
            raise NeuacpProtocolError(
                f"ACP 版本协商失败: 期望 {protocol_version!r}，实际 {remote_version!r}"
            )
        return result or {}

    def terminate(self, wait_s: float = _TERMINATE_WAIT_S) -> None:
        """关闭子进程；正常关闭不触发 on_crash。幂等。"""
        with self._lock:
            self._closed = True
            proc = self._process
            self._process = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=wait_s)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            self._failWaiters(NeuacpError("neuacp client terminated"))

    @property
    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and proc.poll() is None

    @property
    def stderr_tail(self) -> tuple:
        """最近若干行 stderr（诊断用）。"""
        return tuple(self._stderr_tail)

    # ---------- 请求/通知 ----------

    def request(self, method: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        proc = self._process
        if proc is None or proc.poll() is not None:
            raise NeuacpError("neuacp client not running")
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            waiter: "queue.Queue" = queue.Queue()
            self._waiters[msg_id] = waiter
        try:
            self._sendFrame({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
        except NeuacpError:
            with self._lock:
                self._waiters.pop(msg_id, None)
            raise
        wait_s = self._request_timeout if timeout is None else timeout
        try:
            outcome = waiter.get(timeout=wait_s)
        except queue.Empty:
            with self._lock:
                self._waiters.pop(msg_id, None)
            raise NeuacpTimeoutError(f"ACP request timeout: {method}") from None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome or {}

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        self._sendFrame({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def setRequestHandler(self, method: str, handler: Callable[[dict], dict]) -> None:
        """注册 agent→client 方向的请求处理器（如 session/request_permission）。

        handler 在泵线程内同步调用，返回值作为 JSON-RPC result 回给 agent。
        """
        with self._lock:
            self._request_handlers[method] = handler

    # ---------- 内部实现 ----------

    def _sendFrame(self, message: dict) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise NeuacpError("neuacp client not running")
        payload = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(payload.encode("utf-8"))
                proc.stdin.flush()
        except OSError as exc:
            raise NeuacpError(f"写入外部代理失败: {exc}") from exc

    def _startPumps(self) -> None:
        threading.Thread(target=self._pumpStdout, daemon=True).start()
        threading.Thread(target=self._pumpStderr, daemon=True).start()

    def _pumpStdout(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                if len(line) > self._frame_limit:
                    self._failClosed(f"frame limit exceeded: {len(line)} > {self._frame_limit}")
                    return
                try:
                    message = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    self._failClosed("invalid JSON-RPC frame")
                    return
                self._dispatch(message)
            self._failClosed(f"agent exited (code={proc.poll()})")
        except Exception as exc:  # 泵线程兜底：任何异常都按 fail-closed 上报
            self._failClosed(f"stdout pump error: {exc}")

    def _pumpStderr(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in proc.stderr:
                text = raw.decode("utf-8", "replace").rstrip()
                if text:
                    self._stderr_tail.append(text)
        except Exception:
            pass

    def _dispatch(self, message: dict) -> None:
        msg_id = message.get("id")
        method = message.get("method")
        if msg_id is not None:
            with self._lock:
                waiter = self._waiters.pop(msg_id, None)
            if waiter is not None:
                if message.get("error"):
                    error = message["error"]
                    waiter.put(NeuacpError(f"ACP error {error.get('code')}: {error.get('message')}"))
                else:
                    waiter.put(message.get("result") or {})
                return
        if not method:
            return
        with self._lock:
            handler = self._request_handlers.get(method)
        if handler is not None and msg_id is not None:
            try:
                result = handler(message.get("params") or {})
                response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(exc)}}
            try:
                self._sendFrame(response)
            except NeuacpError:
                pass
            return
        if self._on_event is not None:
            try:
                self._on_event(method, message.get("params") or {})
            except Exception:
                pass

    def _failClosed(self, reason: str) -> None:
        with self._lock:
            if self._crash_reported or self._closed:
                return
            self._crash_reported = True
        self._failWaiters(NeuacpProtocolError(f"external agent fail-closed: {reason}"))
        if self._on_crash is not None:
            try:
                self._on_crash(reason)
            except Exception:
                pass
        self.terminate()

    def _failWaiters(self, error: Exception) -> None:
        with self._lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for waiter in waiters:
            waiter.put(error)

    def _childEnvironment(self) -> dict:
        env = {}
        for key in _BASE_ENV_KEYS:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["PYTHONIOENCODING"] = "utf-8"
        for key, value in self._env_extra.items():
            env[key] = value
        return env
