# -*- coding: utf-8 -*-
"""会话式 shell 执行器（P0-3，Codex unified_exec 对齐）。

语义（docs/Neurova_Codex代码级对比_2026-09-14.md §2.7）：
- exec_command：启动常驻进程，yield_time_ms 内未结束返回 session_id（running），
  已结束直接返回 exit_code（completed）——长任务不再卡死在一次性调用上
- write_stdin：向同一会话写输入并轮询新输出（chars 空串=纯轮询）
- 输出 head+tail 双端缓冲（HEAD 50k + TAIL 200k 字符），按 token 预算截断并
  显式标注 original_chars/truncated——模型永远知道被截了多少
- 会话上限 64（Codex MAX_UNIFIED_EXEC_PROCESSES 同值）；已完成会话按 TTL 回收；
  yield 钳位 [250ms, 30000ms]（Codex 同值）

实现说明：subprocess 管道 + 读线程（非 PTY）——跨平台一致（Windows 无 ConPTY
依赖）；交互语义以 stdin 写入 + 输出轮询承载，足够覆盖构建/测试/长脚本场景。
"""
from __future__ import annotations

import asyncio
import codecs
import os
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MAX_SESSIONS = 64
MIN_YIELD_TIME_MS = 250
MAX_YIELD_TIME_MS = 30_000
DEFAULT_YIELD_TIME_MS = 1_000
DEFAULT_MAX_OUTPUT_TOKENS = 10_000
_HEAD_CHARS = 50_000
_TAIL_CHARS = 200_000
_POLL_INTERVAL_S = 0.05
_DEFAULT_FINISHED_TTL_SECONDS = 1800


class _OutputBuffer:
    """线程安全 head+tail 双端缓冲：头部 50k + 尾部 200k，中段计数省略。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._head: List[str] = []
        self._head_len = 0
        self._tail: deque = deque()
        self._tail_len = 0
        self._total = 0

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._total += len(text)
            if self._head_len < _HEAD_CHARS:
                take = text[: _HEAD_CHARS - self._head_len]
                self._head.append(take)
                self._head_len += len(take)
                text = text[len(take):]
            if text:
                self._tail.append(text)
                self._tail_len += len(text)
                while self._tail_len > _TAIL_CHARS and self._tail:
                    dropped = self._tail.popleft()
                    self._tail_len -= len(dropped)

    def text(self) -> str:
        with self._lock:
            head = "".join(self._head)
            tail = "".join(self._tail)
            omitted = self._total - self._head_len - self._tail_len
        if omitted > 0:
            return head + f"\n…[中间省略 {omitted} 字符]…\n" + tail
        return head + tail

    @property
    def total_chars(self) -> int:
        with self._lock:
            return self._total


class _ShellSession:
    def __init__(self, session_id: int, command: str, cwd: Optional[str]) -> None:
        self.session_id = session_id
        self.command = command
        self.buffer = _OutputBuffer()
        self.finished = threading.Event()
        self.exit_code: Optional[int] = None
        self.created_at = time.time()
        self.finished_at: Optional[float] = None
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
        )
        self._reader = threading.Thread(
            target=self._read_loop, name=f"shell-session-{session_id}", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        fd = self.proc.stdout.fileno()
        try:
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                self.buffer.append(self.decoder.decode(chunk))
        finally:
            try:
                rest = self.decoder.decode(b"", final=True)
                if rest:
                    self.buffer.append(rest)
            except Exception:  # noqa: BLE001
                pass
            self.finished.set()
            self.finished_at = time.time()

    def write_stdin(self, chars: str) -> None:
        if not chars or self.proc.stdin is None:
            return
        # 行缓冲 shell 需要 \n 才消费输入：非换行结尾自动补齐（Ctrl+C 等
        # 控制字符补换行无副作用）
        if not chars.endswith("\n"):
            chars += "\n"
        try:
            self.proc.stdin.write(chars.encode("utf-8", "replace"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            logger.debug("write_stdin 写入失败（进程可能已退出）: session=%s", self.session_id)

    def terminate(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _rough_tokens(text: str) -> int:
    """粗 token 估算（CJK≈1:1、其余≈4:1 字符）。

    不用统一估算器 estimate_tokens：它是词级启发式，对无空格长文本
    （连续重复字符/压缩串）坍缩为 ~1 token，会把截断预算完全放大失效。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    other = len(text) - cjk
    return cjk + other // 4 + 1


def _clip_to_token_budget(text: str, max_output_tokens: int) -> tuple:
    """按 token 预算截断为 head+tail，返回 (文本, 是否截断)。"""
    if max_output_tokens <= 0 or not text:
        return text, False
    est = _rough_tokens(text)
    if est <= max_output_tokens:
        return text, False
    target_chars = max(200, int(len(text) * (max_output_tokens / max(est, 1)) * 0.9))
    head_len = int(target_chars * 0.6)
    tail_len = target_chars - head_len
    clipped = (
        text[:head_len]
        + f"\n…[输出过长已截断: 原始 {len(text)} 字符, 仅保留首尾]…\n"
        + (text[-tail_len:] if tail_len > 0 else "")
    )
    return clipped, True


class ShellSessionManager:
    """常驻 shell 会话注册表。单例经 get_shell_session_manager() 获取。"""

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self.max_sessions = max_sessions
        self.finished_ttl_seconds = _DEFAULT_FINISHED_TTL_SECONDS
        self._lock = threading.RLock()
        self._sessions: Dict[int, _ShellSession] = {}
        self._next_id = 1

    # ── 内部 ──────────────────────────────────────────────────────

    def _reap_expired_locked(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if s.finished_at is not None
            and now - s.finished_at >= self.finished_ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    def _active_count_locked(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.finished.is_set())

    @staticmethod
    def _clamp_yield(yield_time_ms: Optional[int]) -> float:
        try:
            y = int(yield_time_ms if yield_time_ms is not None else DEFAULT_YIELD_TIME_MS)
        except (TypeError, ValueError):
            y = DEFAULT_YIELD_TIME_MS
        return max(MIN_YIELD_TIME_MS, min(y, MAX_YIELD_TIME_MS)) / 1000.0

    async def _wait_for(self, session: _ShellSession, yield_s: float) -> None:
        deadline = time.monotonic() + yield_s
        while not session.finished.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_S)

    @staticmethod
    def _result(session: _ShellSession, max_output_tokens: int) -> Dict[str, Any]:
        output, truncated = _clip_to_token_budget(
            session.buffer.text(), max_output_tokens
        )
        exit_code = session.exit_code
        if exit_code is None and session.finished.is_set():
            exit_code = session.proc.poll()
        return {
            "session_id": session.session_id,
            "status": "completed" if session.finished.is_set() else "running",
            "exit_code": exit_code,
            "output": output,
            "truncated": truncated,
            "original_chars": session.buffer.total_chars,
        }

    # ── 对外接口 ──────────────────────────────────────────────────

    async def start_session(
        self,
        command: str,
        workdir: Optional[str] = None,
        yield_time_ms: Optional[int] = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> Dict[str, Any]:
        command = str(command or "").strip()
        if not command:
            return {"status": "rejected", "error": "缺少 command 参数"}
        yield_s = self._clamp_yield(yield_time_ms)
        with self._lock:
            self._reap_expired_locked()
            if self._active_count_locked() >= self.max_sessions:
                return {
                    "status": "rejected",
                    "error": f"会话数已达上限 {self.max_sessions}，请先结束或等待现有命令完成",
                }
            try:
                session = _ShellSession(self._next_id, command, workdir)
            except OSError as e:
                return {"status": "rejected", "error": f"进程启动失败: {e}"}
            self._sessions[self._next_id] = session
            self._next_id += 1
        await self._wait_for(session, yield_s)
        if session.finished.is_set():
            session.exit_code = session.proc.returncode
        return self._result(session, max_output_tokens)

    async def poll_session(
        self,
        session_id: int,
        chars: str = "",
        yield_time_ms: Optional[int] = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> Dict[str, Any]:
        yield_s = self._clamp_yield(yield_time_ms)
        with self._lock:
            session = self._sessions.get(int(session_id)) if session_id is not None else None
        if session is None:
            return {"status": "not_found", "error": f"会话 {session_id} 不存在或已回收"}
        if chars:
            session.write_stdin(str(chars))
        await self._wait_for(session, yield_s)
        if session.finished.is_set() and session.exit_code is None:
            session.exit_code = session.proc.returncode
        return self._result(session, max_output_tokens)

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "session_id": s.session_id,
                    "command": s.command,
                    "status": "completed" if s.finished.is_set() else "running",
                    "exit_code": s.exit_code,
                }
                for s in sorted(self._sessions.values(), key=lambda x: x.session_id)
            ]

    async def kill_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.terminate()
        await asyncio.sleep(0)  # 让出事件循环，读线程收尾


_MANAGER: Optional[ShellSessionManager] = None
_MANAGER_LOCK = threading.Lock()


def get_shell_session_manager() -> ShellSessionManager:
    """单例工厂（项目惯例：get_*/reset_* 成对）。"""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ShellSessionManager()
        return _MANAGER


def reset_shell_session_manager() -> None:
    """重置单例（测试/重载用；现有进程不强杀，交由进程退出回收）。"""
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = None
