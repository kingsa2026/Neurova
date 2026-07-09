"""
ShutdownGuard — 记忆写入安全兜底

职责:
1. Sentinel 标记: 追踪服务的正常/异常关闭
2. 优雅关闭: 强制刷新所有 Agent 的对话缓冲区到持久存储
3. 崩溃恢复: 启动时检测异常中断,从 session 文件恢复丢失的记忆
4. Agent 隔离: 恢复时按 agent_id 严格隔离,不会跨 Agent 污染

设计原则:
- 深度模块: 小接口,深实现
- 契约: 公共 API 形状由 tests/unit/memory/test_shutdown_guard*.py 锁定
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = get_logger(__name__)


# sentinel 默认文件名(测试期望)
DEFAULT_SENTINEL_FILENAME = ".neurova_shutdown_sentinel"


class ShutdownGuard:
    """
    记忆写入安全兜底守护器

    确保服务关闭时所有记忆都被持久化,启动时能从崩溃中恢复。

    公共 API 契约(见 tests/unit/memory/test_shutdown_guard.py):
        __init__(workspace_dir: str, sentinel_filename: str = ".neurova_shutdown_sentinel")
        write_sentinel(status: str = "running") -> None     # 写 {pid, started_at, status}
        mark_clean_shutdown() -> None                        # 删除 sentinel 文件
        check_abnormal_shutdown() -> {abnormal, crash_time}  # 返回 dict
        flush_all_agent_buffers(agents) -> {agent_id:{flushed}, total_flushed}
        recover_from_sessions(agents, crash_time) -> {recovered, errors}
        graceful_shutdown(agents) -> {buffers_flushed, clean_shutdown}
        prepare_startup(agents) -> {abnormal, recovered_memories, sentinel_written}
    """

    def __init__(
        self,
        workspace_dir: str,
        sentinel_filename: str = DEFAULT_SENTINEL_FILENAME,
    ):
        """
        构造守护器。

        Args:
            workspace_dir: 工作空间目录(str,内部转 Path)。sentinel 文件
                           及 session 恢复目录树(agents/<agent_id>/session/)
                           都基于此路径。
            sentinel_filename: sentinel 文件名,默认 .neurova_shutdown_sentinel。
        """
        # 兼容传入 Path 或 str
        self._data_dir = Path(workspace_dir)
        self._sentinel_path = self._data_dir / sentinel_filename
        self._lock = threading.RLock()
        self._agent_buffers: Dict[str, Any] = {}  # 向后兼容:agent_id -> buffer
        self._is_shutting_down = False

        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ── Sentinel 标记 ─────────────────────────────────────────

    def write_sentinel(self, status: str = "running") -> None:
        """
        写入 sentinel 标记文件。

        文件内容为 JSON: {pid, started_at, status}
        - pid: 当前进程 PID
        - started_at: 当前 UTC 时间(ISO 8601 带时区)
        - status: 进程状态,默认 "running";正常关闭时由 mark_clean_shutdown 删除文件

        Args:
            status: 状态字符串,默认 "running"
        """
        sentinel_data = {
            "pid": os.getpid(),
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": status,
        }

        with self._lock:
            try:
                with open(self._sentinel_path, "w", encoding="utf-8") as f:
                    json.dump(sentinel_data, f, ensure_ascii=False, indent=2)
                logger.debug("Sentinel written: status=%s pid=%s", status, sentinel_data["pid"])
            except Exception as e:
                logger.warning("Failed to write sentinel: %s", e)

    def mark_clean_shutdown(self) -> None:
        """
        标记为正常关闭:删除 sentinel 文件。

        幂等:若 sentinel 不存在,不抛出异常。
        """
        with self._lock:
            try:
                self._sentinel_path.unlink(missing_ok=True)
                logger.info("Sentinel removed on clean shutdown")
            except Exception as e:
                logger.warning("Failed to remove sentinel on clean shutdown: %s", e)

    def check_abnormal_shutdown(self) -> Dict[str, Any]:
        """
        检查上次是否异常关闭。

        Returns:
            dict:
                {abnormal: False, crash_time: None} — 无 sentinel(首次启动或干净状态)
                {abnormal: True,  crash_time: <datetime>} — 存在 status="running" 的 sentinel
                {abnormal: False, crash_time: None} — 存在但 status 非 running(理论不应出现)
        """
        with self._lock:
            if not self._sentinel_path.exists():
                logger.info("No sentinel file found — first run or clean state")
                return {"abnormal": False, "crash_time": None}

            try:
                with open(self._sentinel_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Corrupted sentinel file: %s — treating as abnormal", e)
                # 损坏文件视为异常,但无法解析时间
                return {"abnormal": True, "crash_time": None}

            status = data.get("status", "running")
            started_at_str = data.get("started_at")

            crash_time = self._parse_iso_time(started_at_str)

            if status == "running":
                last_pid = data.get("pid")
                logger.warning(
                    "Abnormal shutdown detected! Last run: PID=%s, started_at=%s",
                    last_pid, started_at_str,
                )
                return {"abnormal": True, "crash_time": crash_time}

            # status 非 running(如 "clean_shutdown"),理论上文件已被删除
            logger.info("Sentinel status=%s, treating as not abnormal", status)
            return {"abnormal": False, "crash_time": None}

    # ── 缓冲区刷新 ─────────────────────────────────────────────

    def flush_all_agent_buffers(self, agents: Dict[str, Any]) -> Dict[str, Any]:
        """
        强制刷新所有 Agent 的对话缓冲区到持久存储。

        对每个 agent 调用 agent.memory_manager.flush_buffer(),处理:
        - memory_manager 为 None: 跳过,flushed=0
        - flush_buffer 抛异常: 记录 error,继续其他 agent
        - 返回值非 int: 容忍,转 int

        Args:
            agents: {agent_id: agent} 字典

        Returns:
            {agent_id: {"flushed": int, ["error"]: str}, "total_flushed": int}
        """
        result: Dict[str, Any] = {}
        total_flushed = 0

        for agent_id, agent in agents.items():
            try:
                memory_manager = getattr(agent, "memory_manager", None)
                if memory_manager is None:
                    result[agent_id] = {"flushed": 0}
                    logger.debug("Agent '%s' has no memory_manager, skipped", agent_id)
                    continue

                flushed_raw = memory_manager.flush_buffer()
                flushed = int(flushed_raw) if flushed_raw is not None else 0
                result[agent_id] = {"flushed": flushed}
                total_flushed += flushed
                logger.info("Flushed %d buffer entries for agent '%s'", flushed, agent_id)

            except Exception as e:
                logger.warning(
                    "Failed to flush buffer for agent '%s': %s — continuing with others",
                    agent_id, e,
                )
                result[agent_id] = {"flushed": 0, "error": str(e)}

        result["total_flushed"] = total_flushed
        return result

    # ── 崩溃恢复 ───────────────────────────────────────────────

    def recover_from_sessions(
        self,
        agents: Dict[str, Any],
        crash_time: Optional[datetime.datetime] = None,
    ) -> Dict[str, int]:
        """
        从 session 文件恢复丢失的记忆。

        扫描 workspace_dir/agents/<agent_id>/session/session_*.json,
        对每条 timestamp > crash_time 的消息,调用对应 agent.memory_manager.remember(content)。

        Agent 隔离:只处理 agents 字典中存在的 agent_id,不会跨 Agent 污染。

        Args:
            agents: {agent_id: agent} 字典
            crash_time: 崩溃时间点;此时间之后的消息视为丢失,需恢复。
                        None 时恢复所有消息。

        Returns:
            {recovered: int, errors: int}
        """
        result = {"recovered": 0, "errors": 0}

        if not agents:
            return result

        # 默认 crash_time 为 UTC 最小值,即恢复所有消息
        if crash_time is None:
            crash_time = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        # crash_time 无时区信息时假定为 UTC
        elif crash_time.tzinfo is None:
            crash_time = crash_time.replace(tzinfo=datetime.timezone.utc)

        agents_base = self._data_dir / "agents"
        if not agents_base.exists():
            logger.info("No agents session directory found, skipping recovery")
            return result

        for agent_id, agent in agents.items():
            agent_session_dir = agents_base / agent_id / "session"
            if not agent_session_dir.exists():
                continue

            memory_manager = getattr(agent, "memory_manager", None)
            recovered_count, error_count = self._recover_one_agent(
                agent_id, agent_session_dir, memory_manager, crash_time,
            )
            result["recovered"] += recovered_count
            result["errors"] += error_count

        logger.info(
            "Recovery completed: recovered=%d, errors=%d",
            result["recovered"], result["errors"],
        )
        return result

    def _recover_one_agent(
        self,
        agent_id: str,
        session_dir: Path,
        memory_manager: Any,
        crash_time: datetime.datetime,
    ) -> tuple:
        """恢复单个 Agent 的所有 session 文件,返回 (recovered, errors)。"""
        recovered = 0
        errors = 0

        for session_file in session_dir.glob("session_*.json"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse session file %s: %s", session_file, e)
                errors += 1
                continue

            messages = data.get("messages", [])
            for msg in messages:
                ts_str = msg.get("timestamp")
                if not ts_str:
                    continue

                msg_time = self._parse_iso_time(ts_str)
                if msg_time is None or msg_time <= crash_time:
                    continue

                content = msg.get("content", "")
                try:
                    if memory_manager is not None:
                        ret = memory_manager.remember(content)
                        # 返回 None 视为重复/跳过,不计入 recovered
                        if ret is not None:
                            recovered += 1
                    else:
                        # 无 memory_manager,仅计数(不丢失消息)
                        recovered += 1
                except Exception as e:
                    logger.warning(
                        "Failed to recover message in %s for agent '%s': %s",
                        session_file.name, agent_id, e,
                    )
                    errors += 1

        if recovered or errors:
            logger.info(
                "Agent '%s' recovery: recovered=%d, errors=%d",
                agent_id, recovered, errors,
            )
        return recovered, errors

    # ── 完整流程 ───────────────────────────────────────────────

    def graceful_shutdown(self, agents: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """
        优雅关闭流程:
        1. 刷新所有 agent 缓冲区
        2. 删除 sentinel 文件(标记正常关闭)

        Args:
            agents: {agent_id: agent} 字典
            timeout: 超时时间(秒,日志用)

        Returns:
            {buffers_flushed: <flush_all_agent_buffers 结果>, clean_shutdown: bool}
        """
        self._is_shutting_down = True
        logger.info("Starting graceful shutdown...")

        start_time = time.monotonic()
        flush_results = self.flush_all_agent_buffers(agents)
        flush_time = time.monotonic() - start_time
        logger.info("Buffer flush completed in %.2fs: total_flushed=%d",
                    flush_time, flush_results.get("total_flushed", 0))

        # 删除 sentinel 标记正常关闭
        self.mark_clean_shutdown()

        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            logger.warning("Shutdown took %.2fs (timeout: %.2fs)", elapsed, timeout)

        logger.info("Graceful shutdown completed in %.2fs", elapsed)
        return {
            "buffers_flushed": flush_results,
            "clean_shutdown": True,
        }

    def prepare_startup(self, agents: Dict[str, Any]) -> Dict[str, Any]:
        """
        启动准备流程:
        1. 检查异常关闭
        2. 若异常,从 session 恢复丢失记忆
        3. 写入新 sentinel(覆盖旧的)

        Args:
            agents: {agent_id: agent} 字典

        Returns:
            {abnormal: bool, recovered_memories: int, sentinel_written: bool}
        """
        result = {
            "abnormal": False,
            "recovered_memories": 0,
            "sentinel_written": False,
        }

        check = self.check_abnormal_shutdown()
        result["abnormal"] = check["abnormal"]

        if check["abnormal"]:
            logger.warning("Abnormal shutdown detected — running recovery...")
            recovery = self.recover_from_sessions(
                agents=agents,
                crash_time=check["crash_time"],
            )
            result["recovered_memories"] = recovery["recovered"]
            if recovery["errors"]:
                logger.warning("Recovery completed with %d errors", recovery["errors"])

        # 写入新的 sentinel(覆盖旧的)
        self.write_sentinel(status="running")
        result["sentinel_written"] = True

        return result

    # ── 向后兼容(无测试,保留以兼容潜在调用方) ───────────────

    def register_agent_buffer(self, agent_id: str, buffer: Any) -> None:
        """注册 Agent 的对话缓冲区(向后兼容,新代码应使用 flush_all_agent_buffers)。"""
        with self._lock:
            self._agent_buffers[agent_id] = buffer
            logger.debug("Registered buffer for agent '%s'", agent_id)

    def unregister_agent_buffer(self, agent_id: str) -> None:
        """注销 Agent 的对话缓冲区(向后兼容)。"""
        with self._lock:
            self._agent_buffers.pop(agent_id, None)

    @property
    def is_shutting_down(self) -> bool:
        """是否正在关闭。"""
        return self._is_shutting_down

    # ── 工具方法 ───────────────────────────────────────────────

    @staticmethod
    def _parse_iso_time(ts_str: Optional[str]) -> Optional[datetime.datetime]:
        """解析 ISO 8601 时间字符串,失败返回 None。"""
        if not ts_str:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(ts_str)
            # 确保带时区(无时区时假定为 UTC)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed
        except (ValueError, TypeError) as e:
            logger.warning("Failed to parse timestamp '%s': %s", ts_str, e)
            return None


# ── 全局单例 ─────────────────────────────────────────────────

_shutdown_guard: Optional[ShutdownGuard] = None
_guard_lock = threading.Lock()


def get_shutdown_guard(workspace_dir: Optional[str] = None) -> ShutdownGuard:
    """
    获取全局 ShutdownGuard 单例。

    Args:
        workspace_dir: 工作空间目录;首次调用时若为 None,默认 "data"。

    Returns:
        ShutdownGuard 单例实例
    """
    global _shutdown_guard
    if _shutdown_guard is None:
        with _guard_lock:
            if _shutdown_guard is None:
                if workspace_dir is None:
                    workspace_dir = "data"
                _shutdown_guard = ShutdownGuard(workspace_dir=workspace_dir)
    return _shutdown_guard


def reset_shutdown_guard() -> None:
    """重置全局 ShutdownGuard(用于测试)。"""
    global _shutdown_guard
    with _guard_lock:
        _shutdown_guard = None
