# -*- coding: utf-8 -*-
"""ACP 真实 transcript 回放器（G2）。

把录制得到的 JSON fixture 按帧序喂给**真** :class:`NeuacpClient` 管线
（真分帧 / 真 dispatch / 真 frame_log / 真脱敏），并回放同一份场景步骤
脚本，产出行为记录（握手结果 / 步骤结果 / 事件回调序列 / 帧账本转录）
供契约测试断言「回放行为与录制时一致」。

实现选择——**注入 transport，而非子进程喂帧**：

- ``NeuacpClient`` 对进程表面只有几条 IO 假设：``proc.stdout`` 可迭代出
  UTF-8 字节行、``proc.stdin`` 可 ``write``/``flush``/``close``，治理路径
  用 ``poll``/``pid``/``kill``/``wait``。:class:`ScriptedTransport` 实现同一
  表面，并在 ``replay`` 期间把 ``acp_client.subprocess.Popen`` 打补丁指向
  它——客户端代码零改动，分帧/dispatch/frame_log/脱敏全部走真实实现。
- 不选「真子进程喂帧」：那会把被测对象从「客户端管线」扩大成「进程治理」，
  Windows 的 .cmd 垫片解析、树杀时序、管道缓冲都会把不稳定因素带进契约
  断言；本回放的被测对象是客户端管线本身，fixture 已是真实 CLI 的一手
  transcript，无需再起真进程。

帧供给时序（保因果序）：fixture 里每个 in 帧记录它之前出现过多少个 out 帧
（out 阈值）；回放时该帧只有当客户端真实写出足量 out 帧后才会被供给——
「请求先于应答」的因果序被完整保留，按 id 配对不会因提前供帧而失配。
供帧停顿超过 :data:`DEFAULT_STALL_TIMEOUT_S` 视为 fixture 与步骤脚本不自洽，
诚实 fail-closed（对应真机的 agent 无响应）。

本模块是「场景步骤脚本」的**唯一解释器**：录制侧
（``scripts/neuacp_record_fixture.py``）与回放侧共用 :func:`runScenarioSteps`，
保证同一份步骤在录制与回放两侧语义一致（单一事实源，不造第二套解释器）。
"""
from __future__ import annotations

import json
import threading
import time
import types
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from neurova.agent.neuacp.redaction import redactFrame

#: in 帧等待 out 阈值的默认上限（秒）：超过即视为回放停滞，fail-closed。
DEFAULT_STALL_TIMEOUT_S = 15.0

#: 会话 id 占位符：步骤参数中出现即替换为 state 里的真实 sessionId。
SESSION_ID_PLACEHOLDER = "$session_id"

#: 工作目录占位符：录制时的 cwd，随 fixture 存取，回放原样复用。
CWD_PLACEHOLDER = "$cwd"


# ---------- 场景步骤解释器（录制 / 回放共用的唯一实现） ----------

def substituteParams(params: Any, state: Dict[str, Any]) -> Any:
    """深拷贝替换步骤参数里的占位符。

    ``$session_id`` → 最近一次 session/new 应答里的 sessionId；
    ``$cwd`` → state["cwd"]（录制时为录制工作目录，随 fixture 复用）。
    占位符命中但 state 缺值时诚实抛错，不静默填空串。
    """
    if isinstance(params, dict):
        return {key: substituteParams(value, state) for key, value in params.items()}
    if isinstance(params, list):
        return [substituteParams(value, state) for value in params]
    if isinstance(params, str):
        if params == SESSION_ID_PLACEHOLDER:
            if "session_id" not in state or not state["session_id"]:
                raise ValueError("步骤参数引用 $session_id，但此前没有任何 session/new 应答提供 sessionId")
            return state["session_id"]
        if params == CWD_PLACEHOLDER:
            if "cwd" not in state or not state["cwd"]:
                raise ValueError("步骤参数引用 $cwd，但 state 未提供 cwd")
            return state["cwd"]
    return params


def _outcomeError(outcome: dict, exc: Exception) -> dict:
    """把步骤异常如实记进行结果：异常类名 + 消息前缀（截断）。"""
    outcome["ok"] = False
    outcome["error_class"] = type(exc).__name__
    outcome["error_contains"] = str(exc)[:300]
    return outcome


def runScenarioSteps(
    client: Any,
    steps: List[dict],
    *,
    state: Optional[Dict[str, Any]] = None,
    on_step: Optional[Callable[[dict], None]] = None,
) -> List[dict]:
    """按步骤脚本驱动一个（真）NeuacpClient，逐步返回结果记录。

    步骤语言（与 fixture["steps"] 同一数据形态）：
    - ``{"op": "start", "protocol_version": "1", "client_capabilities": {}}``
      → ``client.start(...)``，结果记 ``handshake``；版本不兼容等失败如实记
      ``error_class``/``error_contains``。
    - ``{"op": "request", "method": ..., "params": ..., "timeout": ...}``
      → ``client.request(...)``，结果记 ``result``；应答含 ``sessionId`` 时
      存入 state 供后续 ``$session_id`` 替换。
    - ``{"op": "notify", "method": ..., "params": ...}`` → ``client.notify(...)``。
    - ``{"op": "cancel_soon", "after_s": 4, "method": ..., "params": ...}``
      → 起定时线程延迟发 notify（用于「prompt 在飞时发中断」——请求会阻塞
        当前线程，取消必须由旁路线程送出）。
    - ``{"op": "set_permission_handler", "choice": "allow"|"deny"}``
      → 注册 ``session/request_permission`` 处理器，固定回该裁决。
    - ``{"op": "sleep", "seconds": 2}`` → 真实等待。
    - ``{"op": "terminate"}`` → ``client.terminate()``（幂等）。

    任一步骤抛异常只记入该步结果，不中断后续步骤（terminate 总能执行）。
    """
    state = state if state is not None else {}
    outcomes: List[dict] = []
    for step in steps:
        op = str((step or {}).get("op") or "")
        outcome: Dict[str, Any] = {"op": op}
        try:
            if op == "start":
                handshake = client.start(
                    protocol_version=step.get("protocol_version", "1"),
                    client_capabilities=step.get("client_capabilities") or {},
                )
                outcome["ok"] = True
                outcome["handshake"] = handshake or {}
            elif op == "request":
                method = str(step["method"])
                params = substituteParams(step.get("params") or {}, state)
                result = client.request(method, params, step.get("timeout"))
                outcome["ok"] = True
                outcome["method"] = method
                outcome["result"] = result or {}
                sessionId = (result or {}).get("sessionId")
                if sessionId:
                    state["session_id"] = sessionId
            elif op == "notify":
                method = str(step["method"])
                params = substituteParams(step.get("params") or {}, state)
                client.notify(method, params)
                outcome["ok"] = True
                outcome["method"] = method
            elif op == "cancel_soon":
                method = str(step["method"])
                params = substituteParams(step.get("params") or {}, state)
                delay = float(step.get("after_s", 3.0))

                def _fireLater(method=method, params=params, delay=delay):
                    time.sleep(delay)
                    try:
                        client.notify(method, params)
                    except Exception:
                        pass  # 取消旁路失败不影响主步骤结果（主请求自有超时兜底）

                threading.Thread(target=_fireLater, daemon=True).start()
                outcome["ok"] = True
                outcome["method"] = method
                outcome["scheduled_after_s"] = delay
            elif op == "set_permission_handler":
                choice = str(step.get("choice", "deny"))

                def _decide(_params, _choice=choice):
                    return {"outcome": {"choice": _choice}}

                client.setRequestHandler("session/request_permission", _decide)
                outcome["ok"] = True
                outcome["choice"] = choice
            elif op == "sleep":
                seconds = float(step.get("seconds", 1.0))
                time.sleep(seconds)
                outcome["ok"] = True
                outcome["seconds"] = seconds
            elif op == "terminate":
                client.terminate()
                outcome["ok"] = True
            else:
                raise ValueError(f"未知步骤 op: {op!r}")
        except Exception as exc:  # noqa: BLE001 - 步骤失败如实入册，继续执行后续步骤
            _outcomeError(outcome, exc)
        outcomes.append(outcome)
        if on_step is not None:
            on_step(outcome)
    return outcomes


# ---------- 注入式 transport ----------

class ScriptedTransport:
    """以 fixture 帧序喂 ``NeuacpClient`` 的假进程（真客户端零改动）。

    - ``stdin``：收集客户端真实写出的每一帧（按行解析为 dict）。
    - ``stdout``：按预设阈值逐行供给 in 帧——每个 in 帧等到客户端写出
      足量 out 帧后才放行，保因果序；in 帧供完后保持存活直到 ``close``，
      模拟「agent 还活着但不再发帧」（此时客户端请求走真实超时路径）。
    - ``stderr``：恒空（真机 stderr 只进诊断尾，不入契约）。
    - ``poll``：未关闭返回 ``None``（存活），关闭后返回 0。
    """

    def __init__(self, feed: List[Tuple[dict, int]], *, stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S):
        self._feed = list(feed)
        self._stall_timeout_s = float(stall_timeout_s)
        self._lock = threading.Lock()
        self._out_frames: List[dict] = []
        self._pending = b""
        self._closed = threading.Event()
        # 治理路径表面：taskkill /T /F 打不中假 pid 会走 proc.kill() 兜底
        self.pid = 0

    # ----- stdin 表面 -----
    @property
    def stdin(self) -> "ScriptedTransport":
        return self

    def write(self, data: bytes) -> int:
        # 真管道语义：write 只进缓冲，flush 后对端才可读——客户端 _sendFrame
        # 「先记 out 再 flush」的保序前提依赖这一点，这里必须同构。
        self._pending += bytes(data)
        return len(data)

    def flush(self) -> None:
        pending, self._pending = self._pending, b""
        frames: List[dict] = []
        for line in pending.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line.decode("utf-8")))
            except Exception:  # noqa: BLE001 - 坏行也留痕（与真泵的入账口径一致）
                frames.append({"_unparsed": line.decode("utf-8", "replace")[:200]})
        if frames:
            with self._lock:
                self._out_frames.extend(frames)

    def close(self) -> None:
        self.flush()
        self._closed.set()

    # ----- stdout / stderr 表面 -----
    @property
    def stdout(self):
        return self._stdoutGen()

    def _stdoutGen(self):
        for frame, out_threshold in self._feed:
            deadline = time.monotonic() + self._stall_timeout_s
            while self._outCount() < out_threshold:
                if self._closed.is_set():
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"回放供给停滞：客户端已写出 {self._outCount()} 个 out 帧，"
                        f"未达下一 in 帧的阈值 {out_threshold}（fixture 与步骤脚本不自洽）"
                    )
                time.sleep(0.005)
            yield (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
        # in 帧供完：保持存活直到 terminate 关闭（期间客户端请求走真实超时）
        while not self._closed.wait(timeout=0.05):
            pass
        return

    @property
    def stderr(self):
        return iter(())

    # ----- 治理表面 -----
    def poll(self) -> Optional[int]:
        return 0 if self._closed.is_set() else None

    def kill(self) -> None:
        self._closed.set()

    def terminate(self) -> None:
        self._closed.set()

    def wait(self, timeout: Optional[float] = None) -> int:
        self._closed.set()
        return 0

    # ----- 观测 -----
    def _outCount(self) -> int:
        with self._lock:
            return len(self._out_frames)

    def outFrames(self) -> List[dict]:
        with self._lock:
            return list(self._out_frames)


# ---------- 回放入口 ----------

def replay(
    fixture: dict,
    client_factory: Callable[[], Any],
    *,
    stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
    record_frames: bool = True,
) -> dict:
    """按 fixture 帧序回放，返回行为记录供契约断言。

    ``client_factory()`` 须返回**未启动**的真 :class:`NeuacpClient`（命令只是
    占位——Popen 已被替换，不会真拉起进程；超时/回调等按测试需要配置）。
    回放期间客户端的帧留痕键自动绑定一个一次性键，结束后从帧账本读回
    转录（真 frame_log + 真脱敏链路），用后即删临时账本文件。

    返回 dict：
    - ``step_outcomes``：场景步骤逐条结果（含握手/请求结果或错误分类）；
    - ``events``：on_event 回调序列 ``[{"method", "params"}]``；
    - ``crashes``：on_crash 回调序列（fail-closed 事件）；
    - ``transcript``：帧账本读回的 ``[{"seq","direction","frame"}]``；
    - ``out_frames``：transport 侧收集到的客户端出站帧（与 transcript 互证）。
    """
    frames = (fixture or {}).get("frames") or []
    feed: List[Tuple[dict, int]] = []
    out_seen = 0
    for record in frames:
        direction = record.get("direction")
        if direction == "in":
            feed.append((record.get("frame") or {}, out_seen))
        elif direction == "out":
            out_seen += 1
        # direction == "observed"：客户端自身在 terminate 时产生，不喂

    transport = ScriptedTransport(feed, stall_timeout_s=stall_timeout_s)

    import neurova.agent.neuacp.acp_client as acp_module

    real_subprocess = acp_module.subprocess

    def _fakePopen(*_args, **_kwargs):
        return transport

    acp_module.subprocess = types.SimpleNamespace(PIPE=real_subprocess.PIPE, Popen=_fakePopen)

    family = str((fixture or {}).get("family") or "unknown")
    scenario = str((fixture or {}).get("scenario") or "unknown")
    frame_key = f"replay-{family}-{scenario}-{uuid4().hex[:8]}"
    events: List[dict] = []
    crashes: List[str] = []
    client = client_factory()
    client.setEventHandlers(
        on_event=lambda method, params: events.append({"method": method, "params": params or {}}),
        on_crash=crashes.append,
    )
    if record_frames:
        client.setFrameKey(frame_key)
    try:
        step_outcomes = runScenarioSteps(
            client,
            (fixture or {}).get("steps") or [],
            state={"cwd": (fixture or {}).get("cwd") or ""},
        )
    finally:
        acp_module.subprocess = real_subprocess
        try:
            client.terminate()
        except Exception:  # noqa: BLE001 - 收尾幂等
            pass
    transcript = []
    if record_frames:
        try:
            from neurova.agent.neuacp.frame_log import readFrames

            transcript = readFrames(frame_key)
        finally:
            _dropLedgerFile(frame_key)
    return {
        "step_outcomes": step_outcomes,
        "events": events,
        "crashes": crashes,
        "transcript": transcript,
        "out_frames": transport.outFrames(),
    }


def _dropLedgerFile(frame_key: str) -> None:
    """回放用后即删临时帧账本（fail-open：删不掉不留痕患）。"""
    try:
        from neurova.core.data_root import dataPath

        safe = "".join(ch for ch in frame_key if ch.isalnum() or ch in "._-")
        path = dataPath("swarm_runs") / f"{safe}.frames.jsonl"
        if path.exists():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


# ---------- 契约断言 ----------

def normalizeFrame(frame: Any) -> Any:
    """对比前归一一帧：双侧统一再脱敏（幂等），不区分录制/回放来源。"""
    return redactFrame(frame if isinstance(frame, dict) else {})


def _normalizePair(direction: str, frame: Any) -> Tuple[str, dict]:
    """单帧对比形态：observed 帧去掉 ``exit_code``（两侧同规），其余脱敏归一。

    observed 的 ``exit_code`` 不是本契约的被测对象：录制侧是真进程被树杀
    （退出码 0/1/无，视时序而定），回放侧是注入 transport（恒 0）；
    ``type=exited`` 的「进程收口有观测」才是要钉住的契约。
    """
    if not isinstance(frame, dict):
        frame = {}
    if direction == "observed":
        frame = {key: value for key, value in frame.items() if key != "exit_code"}
    return direction, normalizeFrame(frame)


def transcriptPairs(transcript: List[dict]) -> List[Tuple[str, dict]]:
    """把帧账本记录压成 ``(direction, frame)`` 对比序列。"""
    return [
        _normalizePair(str(record.get("direction")), record.get("frame"))
        for record in transcript
    ]


def assertReplayMatchesFixture(fixture: dict, result: dict) -> None:
    """断言回放行为与录制 fixture 一致（握手 / 步骤 / 事件 / 转录帧序）。

    任何一条不一致都以 AssertionError 指名差异位置——变异注入的「变红」
    判据就是本函数对被变异 fixture 抛错。
    """
    expected = (fixture or {}).get("expected") or {}

    # 1) 场景步骤逐条对比（op / ok / 结果载荷 / 错误分类）
    expected_steps = expected.get("steps") or []
    actual_steps = result.get("step_outcomes") or []
    assert len(expected_steps) == len(actual_steps), (
        f"步骤数不一致：期望 {len(expected_steps)}，实际 {len(actual_steps)}"
    )
    for index, (want, got) in enumerate(zip(expected_steps, actual_steps)):
        where = f"步骤[{index}] op={want.get('op')}"
        assert want.get("op") == got.get("op"), f"{where}: op 不一致（{got.get('op')}）"
        assert bool(want.get("ok")) == bool(got.get("ok")), (
            f"{where}: 成败不一致，期望 ok={want.get('ok')}，实际 {got}"
        )
        if want.get("ok"):
            for key in ("handshake", "result"):
                if key in want:
                    assert normalizeFrame(got.get(key) or {}) == normalizeFrame(want.get(key) or {}), (
                        f"{where}: {key} 载荷与录制时不一致"
                        f"\n 期望={json.dumps(want.get(key), ensure_ascii=False)[:400]}"
                        f"\n 实际={json.dumps(got.get(key), ensure_ascii=False)[:400]}"
                    )
        else:
            assert got.get("error_class") == want.get("error_class"), (
                f"{where}: 错误分类不一致，期望 {want.get('error_class')}，实际 {got.get('error_class')}"
            )
            want_text = str(want.get("error_contains") or "")[:120]
            got_text = str(got.get("error_contains") or "")
            assert want_text in got_text, (
                f"{where}: 错误消息不含期望前缀\n 期望含={want_text!r}\n 实际={got_text[:200]!r}"
            )

    # 2) 事件回调序列（方法名 + 脱敏后参数）
    expected_events = expected.get("events") or []
    actual_events = [
        {"method": item.get("method"), "params": normalizeFrame(item.get("params") or {})}
        for item in (result.get("events") or [])
    ]
    normalized_expected_events = [
        {"method": item.get("method"), "params": normalizeFrame(item.get("params") or {})}
        for item in expected_events
    ]
    assert actual_events == normalized_expected_events, (
        f"事件回调序列与录制时不一致：\n 期望={json.dumps(normalized_expected_events, ensure_ascii=False)[:600]}"
        f"\n 实际={json.dumps(actual_events, ensure_ascii=False)[:600]}"
    )

    # 3) 转录帧序（双向帧按序：direction + 载荷；observed 只看收口不看退出码）
    fixture_pairs = [
        _normalizePair(str(record.get("direction")), record.get("frame"))
        for record in ((fixture or {}).get("frames") or [])
    ]
    actual_pairs = transcriptPairs(result.get("transcript") or [])
    assert actual_pairs == fixture_pairs, (
        f"转录帧序与录制时不一致：期望 {len(fixture_pairs)} 帧，实际 {len(actual_pairs)} 帧"
        f"\n 期望={[d for d, _ in fixture_pairs]}"
        f"\n 实际={[d for d, _ in actual_pairs]}"
    )
