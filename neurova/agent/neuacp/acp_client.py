# -*- coding: utf-8 -*-
"""NeuacpClient：ACP v1 JSON-RPC over stdio 客户端。

职责（设计文档 §4.3）：子进程拉起（环境白名单）、换行分隔 JSON-RPC 2.0
帧收发（UTF-8、单帧上限 fail-closed）、initialize 版本协商（不兼容即
terminate）、request 按 id 配对、通知回调（session/update 等）、崩溃
回调、terminate。帧内协议是 ACP；帧层/监督骨架对齐 channels/runner_bridge。
"""
import json
import queue
import shutil
import subprocess
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_FRAME_LIMIT = 1_000_000
_DEFAULT_REQUEST_TIMEOUT = 30.0
_TERMINATE_WAIT_S = 5.0


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
        transport: str = "stdio",
        remote: Optional[dict] = None,
    ) -> None:
        self._command = [str(part) for part in command]
        self._cwd = cwd
        self._env_extra = dict(env_extra or {})
        self._on_event = on_event
        self._on_crash = on_crash
        self._request_timeout = request_timeout
        self._frame_limit = frame_limit
        # 传输形态（§4.8）：stdio 本机直拉；ssh 经 SSH 隧道在远端拉起同一命令。
        self._transport = str(transport or "stdio")
        self._remote = remote if isinstance(remote, dict) else None

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._next_id = 0
        self._waiters: Dict[int, "queue.Queue"] = {}
        self._closed = False
        self._crash_reported = False
        self._stderr_tail: deque = deque(maxlen=50)
        self._write_lock = threading.Lock()
        self._request_handlers: Dict[str, Callable[[dict], dict]] = {}
        # P1 移交清偿（二次 chat 会话复用）：initialize 握手结果缓存 +
        # start 序列互斥锁（握手期不持 self._lock，泵线程可正常派发应答）。
        self._handshake: Optional[dict] = None
        self._start_lock = threading.Lock()
        # F2 帧留痕（§3.2）：frame_key 未绑定（None）一律不落盘（无主会话不留痕）；
        # _exit_observed 保证每个进程代际只记一条 observed/exited（不猜退出码）。
        self._frame_key: Optional[str] = None
        self._exit_observed = False

    # ---------- 生命周期 ----------

    @property
    def started(self) -> bool:
        """握手完成且进程存活（复用判定单点）。"""
        return self._handshake is not None and self.is_alive

    def start(self, *, protocol_version: str = "1", client_capabilities: Optional[dict] = None) -> dict:
        """拉起子进程并完成 initialize 握手；版本不兼容 fail-closed。

        幂等：已启动（握手完成且进程存活）直接返回已存握手结果，不重复
        initialize（P1 移交清偿——验收回炉轮会对同一执行体二次 chat）；
        进程已死（崩溃/terminate 后）则惰性重建并重新握手。
        """
        handshake = self._handshake
        if handshake is not None and self.is_alive:
            return handshake
        with self._start_lock:
            handshake = self._handshake
            if handshake is not None and self.is_alive:
                return handshake
            return self._startLocked(protocol_version, client_capabilities)

    def setFrameKey(self, key: Optional[str]) -> None:
        """绑定帧账本键（通常为 subagent_id，§3.2/F5）。

        未绑定（None/空串）时一律不落盘——管理面 /test 握手等无主会话不留痕。
        池复用件每次 start 重设，随取用方切换。
        """
        text = str(key or "").strip()
        self._frame_key = text or None

    def _startLocked(self, protocol_version: str, client_capabilities: Optional[dict]) -> dict:
        self._handshake = None
        self._closed = False
        self._crash_reported = False
        self._exit_observed = False
        env = self._childEnvironment()
        # Windows：PATH 里的 npx/qoder 等实为 .cmd/.bat，Popen 不做 PATHEXT
        # 解析——用 shutil.which 把首词解析成可执行全路径（解析不到原样保留）。
        # transport=ssh：先包装成 ssh 前缀命令（§4.8，缺 remote/凭据 fail-closed），
        # ssh.exe 本身在 PATH，同样走 which 解析。
        command = list(self._command)
        if self._transport != "stdio":
            from neurova.agent.neuacp.ssh_transport import resolveSpawnCommand

            command = resolveSpawnCommand(command, self._transport, self._remote)
        resolved_head = shutil.which(command[0]) if command else None
        if resolved_head:
            command[0] = resolved_head
        try:
            self._process = subprocess.Popen(
                command,
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
        self._handshake = result or {}
        return self._handshake

    def terminate(self, wait_s: float = _TERMINATE_WAIT_S) -> None:
        """关闭子进程；正常关闭不触发 on_crash。幂等。"""
        with self._lock:
            self._closed = True
            self._handshake = None
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
        # 退出观测点（§3.2）：EOF/terminate/失败收口都经这里，落 observed/exited。
        self._observeExit(proc)

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

    def setTransport(self, transport: str, remote: Optional[dict]) -> None:
        """构造后补设传输形态（§4.8，swarm 名册透传入口）。

        须在 spawn（start）之前调用；进程已启动后变更一律 fail-closed，
        防止同一进程的传输语义被中途改写。
        """
        if self._process is not None:
            raise NeuacpError("外部代理进程已启动，不能再变更 transport/remote（fail-closed）")
        self._transport = str(transport or "stdio")
        self._remote = remote if isinstance(remote, dict) else None

    def setEventHandlers(
        self,
        *,
        on_event: Optional[Callable[[str, dict], None]] = None,
        on_crash: Optional[Callable[[str], None]] = None,
    ) -> None:
        """重绑通知/崩溃回调（P1 移交清偿：池复用进程时，回调随取用方执行体重绑）。

        传 None 保持原回调不动；泵线程每帧读取实例属性，重绑对后续帧即刻生效。
        """
        if on_event is not None:
            self._on_event = on_event
        if on_crash is not None:
            self._on_crash = on_crash

    # ---------- 内部实现 ----------

    def _sendFrame(self, message: dict) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise NeuacpError("neuacp client not running")
        payload = json.dumps(message, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(payload.encode("utf-8"))
                # 先记 out 再 flush（§3.2 保序）：泵线程最早也要等 flush 后才可能
                # 读到应答，保证 out 的 seq 恒早于其应答 in，时序可判定。
                self._recordFrame("out", message)
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
                # 入站消息在派发前留痕（§3.2）；超限/坏帧不入账本（honest fail-closed）。
                self._recordFrame("in", message)
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

    # ---------- F2 帧留痕（§3.2） ----------

    def _recordFrame(self, direction: str, frame: dict) -> None:
        """帧留痕钩子：fail-open，绝不阻断泵/发送；未绑定 frame_key 一律不落盘。"""
        key = self._frame_key
        if not key:
            return
        try:
            from neurova.agent.neuacp.frame_log import appendFrame

            appendFrame(key, direction, frame)
        except Exception as exc:  # noqa: BLE001 - 留痕故障只记日志，不进协议链路
            logger.debug("帧留痕失败（fail-open）: %s", exc)

    def _observeExit(self, proc: Optional[subprocess.Popen]) -> None:
        """进程退出观测点：能拿到 exit_code 就带，拿不到只记 type，不猜。

        每个进程代际只记一条（_exit_observed 旗标，_startLocked 重置）；
        EOF/terminate/失败收口都汇聚到 terminate → 这里。
        """
        if proc is None:
            return
        with self._lock:
            if self._exit_observed:
                return
            self._exit_observed = True
        payload: dict = {"type": "exited"}
        try:
            code = proc.poll()
        except Exception:  # noqa: BLE001 - 观测失败不猜测退出码
            code = None
        if code is not None:
            payload["exit_code"] = code
        self._recordFrame("observed", payload)

    def _childEnvironment(self) -> dict:
        return buildChildEnvironment(self._env_extra)
