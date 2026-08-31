"""camofox-browser 进程监管器 + 临时缓存清理

- 首次 agent 调用时拉起 npx -y @askjo/camofox-browser
- 轮询 /health 等待 ready
- 后台线程定期检查 idle,超时 SIGTERM
- 杀进程前清理临时痕迹(只删 traces + uploads),保留登录态(profiles + cookies)和 Camoufox 二进制
- FastAPI shutdown 时一并清理
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from neurova.core.config import get as env_get, get_int as env_int, get_bool as env_bool
from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_COMMAND = ["npx", "-y", "@askjo/camofox-browser"]
DEFAULT_URL = "http://localhost:9377"
DEFAULT_STARTUP_TIMEOUT = 90
DEFAULT_IDLE_TIMEOUT = 300
DEFAULT_KILL_GRACE = 5
DEFAULT_CHECK_INTERVAL = 30
DEFAULT_HEALTH_PROBE_INTERVAL = 1.0
DEFAULT_TRACE_TTL_HOURS = 24


class CamofoxSupervisor:
    """长生命周期 camofox-browser 进程监管 + 临时痕迹清理"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cmd_env = env_get("NEUROVA_CAMOFOX_COMMAND", "")
        self._command: List[str] = (
            cfg.get("command") or (cmd_env.split() if cmd_env else DEFAULT_COMMAND)
        )
        self._url: str = cfg.get("url") or env_get("NEUROVA_CAMOFOX_URL", DEFAULT_URL)
        self._user_id: str = cfg.get("user_id") or env_get("NEUROVA_CAMOFOX_USER", "neurova")
        self._startup_timeout: int = int(
            cfg.get("startup_timeout")
            or env_int("NEUROVA_CAMOFOX_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT)
        )
        self._idle_timeout: int = int(
            cfg.get("idle_timeout")
            or env_int("NEUROVA_CAMOFOX_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)
        )
        self._kill_grace: int = int(
            cfg.get("kill_grace")
            or env_int("NEUROVA_CAMOFOX_KILL_GRACE", DEFAULT_KILL_GRACE)
        )
        self._check_interval: int = int(
            cfg.get("check_interval")
            or env_int("NEUROVA_CAMOFOX_CHECK_INTERVAL", DEFAULT_CHECK_INTERVAL)
        )
        self._autostart: bool = bool(
            cfg.get("autostart")
            if cfg.get("autostart") is not None
            else env_bool("NEUROVA_CAMOFOX_AUTOSTART", True)
        )
        self._enabled: bool = bool(
            cfg.get("enabled")
            if cfg.get("enabled") is not None
            else env_bool("NEUROVA_CAMOFOX_SUPERVISOR", True)
        )
        self._cleanup_on_stop: bool = bool(
            cfg.get("cleanup_on_stop")
            if cfg.get("cleanup_on_stop") is not None
            else env_bool("NEUROVA_CAMOFOX_CLEANUP_ON_STOP", True)
        )
        self._trace_ttl_hours: int = int(
            cfg.get("trace_ttl_hours")
            or env_int("NEUROVA_CAMOFOX_TRACE_TTL_HOURS", DEFAULT_TRACE_TTL_HOURS)
        )

        # 运行时状态
        self._process: Optional[subprocess.Popen] = None
        self._tracked_pids: List[int] = []  # Windows 下需要跟踪所有子进程
        self._last_activity: float = 0.0
        self._start_lock = threading.Lock()
        self._monitor_running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._managed_by_supervisor = False
        self._stop_requested: threading.Event = threading.Event()
        # 三层隔离:跟踪最近用过的 userId,stop() 时按列表清理 traces
        self._fallback_user_id: str = cfg.get("user_id") or env_get("NEUROVA_CAMOFOX_USER", "neurova")
        self._tracked_user_ids: set = set()
        self._tracked_user_ids_lock = threading.Lock()

    # ── 属性 ──

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self.is_running else None

    # ── 启动入口 ──

    async def ensure_started(self) -> bool:
        if not self._enabled:
            return await self._probe_health()
        if self.is_running:
            self._record_activity()
            return True
        if not self._autostart:
            logger.info("autostart 关闭,服务未在跑——失败")
            return False
        with self._start_lock:
            if self.is_running:
                return True
            ok = await self._spawn_and_wait_ready()
            if ok:
                self._managed_by_supervisor = True
                self._start_monitor()
            return ok

    def record_activity(self) -> None:
        if self.is_running:
            self._record_activity()

    def _record_activity(self) -> None:
        self._last_activity = time.time()

    def track_user_id(self, user_id: Optional[str]) -> None:
        """记录最近使用过的 userId(用于 stop() 时按列表清理 traces)

        三层隔离:Neurova 进程可能服务多 user,每个 user 的 traces 都在
        ~/.camofox/traces/<sha256(userId)[:32]>/。stop() 时必须清理所有已用
        user 的 traces,否则遗漏的 user 累积泄漏。
        """
        if not user_id:
            return
        with self._tracked_user_ids_lock:
            self._tracked_user_ids.add(user_id)

    async def _spawn_and_wait_ready(self) -> bool:
        try:
            logger.info("启动 camofox-browser: %s", " ".join(self._command))
            # Windows 下:用 cmd.exe /c 解析 .cmd/.bat(必需),但记录启动后所有子进程 PID
            # 用于 stop() 时杀整组(因为 cmd 死后子进程会脱离控制)
            if sys.platform == "win32":
                self._process = subprocess.Popen(
                    ["cmd.exe", "/c", *self._command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                self._process = subprocess.Popen(
                    self._command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            # 注意:_tracked_pids 将在 health ready 后填(那时 Camoufox 已起)
            self._tracked_pids = []
        except FileNotFoundError as e:
            logger.error("找不到可执行文件:%s", e)
            self._process = None
            return False
        except Exception as e:
            logger.error("启动失败:%s", e)
            self._process = None
            return False

        deadline = time.time() + self._startup_timeout
        while time.time() < deadline:
            if self._process.poll() is not None:
                logger.error(
                    "启动后立即退出,exit=%s", self._process.returncode
                )
                self._process = None
                return False
            ready = await self._probe_health_via_client()
            if ready:
                self._record_activity()
                # 在 health ready 时(此时 Camoufox 已启动完)收集所有后代 PID
                # 因为 cmd.exe 启动后 node 子进程可能延迟几秒
                await asyncio.sleep(1)
                self._tracked_pids = self._collect_descendant_pids(self._process.pid)
                logger.info(
                    "camofox-browser ready (pid=%s), tracked=%s",
                    self.pid, self._tracked_pids,
                )
                return True
            await asyncio.sleep(DEFAULT_HEALTH_PROBE_INTERVAL)
        logger.error("%ds 内未 ready,杀掉", self._startup_timeout)
        await self._kill_process()
        return False

    async def _probe_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self._url}/health")
                if r.status_code != 200:
                    return False
                return bool((r.json() or {}).get("ok"))
        except Exception:
            return False

    async def _probe_health_via_client(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self._url}/health")
                if r.status_code != 200:
                    return False
                data = r.json() or {}
                return bool(data.get("ok") and data.get("browserRunning"))
        except Exception:
            return False

    # ── 临时痕迹清理 ──

    def _user_dir_name(self, user_id: Optional[str] = None) -> str:
        """sha256(userId)[:32]——与 camofox persistence 插件的命名一致"""
        uid = user_id or self._fallback_user_id
        return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:32]

    def _cleanup_temp_traces(self) -> Dict[str, int]:
        """清理 ~/.camofox/traces/<user>/*.zip(超 TTL)+ ~/.camofox/uploads/*

        三层隔离:按 track_user_id 累积的 user 列表逐个清理 traces 目录;
        兜底清理 fallback_user_id(没有 track 记录时)。保留 ~/.camofox/profiles/(登录态,
        cookies 在 storage-state.json 里天然 per-user 隔离)、~/.camofox/cookies/(无此目录,
        见 lib/persistence.js)、Camoufox 二进制缓存(%LOCALAPPDATA%/camoufox/...)。
        uploads 是全局共享目录(无 per-user 隔离),只能整目录清理一次。
        """
        cleaned: Dict[str, int] = {"traces_zip": 0, "uploads": 0, "bytes": 0, "users": 0}
        if not self._cleanup_on_stop:
            return cleaned
        # 收集要清理的 user 列表
        with self._tracked_user_ids_lock:
            user_ids = list(self._tracked_user_ids) or [self._fallback_user_id]
        home = Path.home()
        traces_dir = home / ".camofox" / "traces"
        uploads_dir = home / ".camofox" / "uploads"
        for user_id in user_ids:
            cleaned["users"] += 1
            try:
                user_traces = traces_dir / self._user_dir_name(user_id)
                if user_traces.exists():
                    ttl_seconds = self._trace_ttl_hours * 3600
                    now = time.time()
                    for zip_path in user_traces.glob("*.zip"):
                        try:
                            age = now - zip_path.stat().st_mtime
                            if age >= ttl_seconds:
                                size = zip_path.stat().st_size
                                zip_path.unlink(missing_ok=True)
                                cleaned["traces_zip"] += 1
                                cleaned["bytes"] += size
                        except Exception as e:  # noqa: BLE001 - 单文件失败不阻断整体
                            logger.debug("trace 清理跳过 %s: %s", zip_path, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("traces[%s] 清理异常(非致命): %s", user_id, e)
        # uploads 仍全局共享,单一清理一次
        try:
            if uploads_dir.exists():
                size = sum(
                    f.stat().st_size for f in uploads_dir.rglob("*") if f.is_file()
                )
                shutil.rmtree(uploads_dir, ignore_errors=True)
                cleaned["uploads"] = 1
                cleaned["bytes"] += size
        except Exception as e:  # noqa: BLE001
            logger.warning("uploads 清理异常(非致命): %s", e)
        return cleaned

    # ── 后台监控线程 ──

    def _start_monitor(self) -> None:
        if self._monitor_running:
            return
        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="camofox-supervisor"
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while self._monitor_running:
            try:
                self._check_idle()
            except Exception as e:
                logger.error("monitor loop error: %s", e)
            for _ in range(int(self._check_interval)):
                if not self._monitor_running:
                    break
                time.sleep(1)

    def _check_idle(self) -> None:
        if not self.is_running:
            return
        idle = time.time() - self._last_activity
        if idle >= self._idle_timeout:
            logger.info(
                "空闲 %ds(阈值 %ds),触发停止事件", int(idle), self._idle_timeout
            )
            self._stop_requested.set()
            # 实际杀进程由 FastAPI shutdown / 下一次 stop() 调用负责
            # (后台线程里不能 await async stop,所以只 set 标志位)

    # ── 关闭接口 ──

    async def stop(self) -> None:
        """FastAPI shutdown 共用入口:清理临时痕迹 → 杀进程"""
        self._monitor_running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        if not (self._managed_by_supervisor and self.is_running):
            return
        # 1. 清理临时痕迹(必须在杀进程前,否则文件可能锁住)
        cleaned = self._cleanup_temp_traces()
        if sum(v for k, v in cleaned.items() if k != "bytes") > 0:
            logger.info(
                "清理临时痕迹:traces_zip=%s, uploads=%s, bytes=%s",
                cleaned["traces_zip"],
                cleaned["uploads"],
                cleaned["bytes"],
            )
        # 2. SIGTERM → grace → SIGKILL
        await self._kill_process()

    def _collect_descendant_pids(self, root_pid: int) -> List[int]:
        """收集 root_pid 的所有后代 PID(包括自己)。
        Windows:优先用 PowerShell Get-CimInstance(Win10+ 内置,wmic 在 Server 2025+ 已被移除);
        POSIX:用 ps。
        """
        pids: set = {root_pid}
        try:
            if sys.platform == "win32":
                # PowerShell CIM:跨 Win10/11/Server 2022/2025 全可用
                ps_cmd = (
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId, ParentProcessId | "
                    "Format-Table -HideTableHeaders -AutoSize"
                )
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=15,
                )
                children: Dict[int, List[int]] = {}
                for line in (out.stdout or "").splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        pid, ppid = int(parts[0]), int(parts[1])
                        children.setdefault(ppid, []).append(pid)
                # BFS 找所有后代
                queue = [root_pid]
                while queue:
                    cur = queue.pop(0)
                    for child in children.get(cur, []):
                        if child not in pids:
                            pids.add(child)
                            queue.append(child)
            else:
                # POSIX:ps -eo pid,ppid
                out = subprocess.run(
                    ["ps", "-eo", "pid,ppid"],
                    capture_output=True, text=True, timeout=10,
                )
                children = {}
                for line in out.stdout.splitlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        pid, ppid = int(parts[0]), int(parts[1])
                        children.setdefault(ppid, []).append(pid)
                queue = [root_pid]
                while queue:
                    cur = queue.pop(0)
                    for child in children.get(cur, []):
                        if child not in pids:
                            pids.add(child)
                            queue.append(child)
        except Exception as e:
            logger.warning("收集后代 PID 失败: %s", e)
        return sorted(pids)

    def _taskkill_all(self, pids: List[int]) -> None:
        """批量 taskkill /F 所有 PID(无需树形,因为已显式列出)"""
        for pid in pids:
            try:
                logger.info("taskkill /F /PID %s", pid)
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=5,
                )
            except Exception as e:
                logger.debug("taskkill %s 失败(可能已死): %s", pid, e)

    async def _kill_process(self) -> None:
        proc = self._process
        if not proc:
            return
        try:
            if sys.platform == "win32":
                # Windows 下:
                # 1) 先发 CTRL_BREAK 给 cmd(在 NEW_PROCESS_GROUP 下 terminate 发的是这个)
                # 2) 等 grace 期给 camofox gracefulShutdown 时间
                # 3) 不管 graceful 成败,都用启动时跟踪的 PIDs 批量 taskkill
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=self._kill_grace)
                    except subprocess.TimeoutExpired:
                        pass
                except Exception:
                    pass
                # 启动时已记录 cmd + 所有后代 PID,直接批量杀
                if self._tracked_pids:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._taskkill_all, list(self._tracked_pids)
                    )
                self._tracked_pids = []
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=self._kill_grace)
                except subprocess.TimeoutExpired:
                    logger.warning("grace %ds 满,kill -9", self._kill_grace)
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception as e:
            logger.error("kill error: %s", e)
        finally:
            self._process = None
            self._managed_by_supervisor = False


# ── 单例 ──

_supervisor_instance: Optional[CamofoxSupervisor] = None
_supervisor_lock = threading.Lock()


def get_camofox_supervisor(config: Optional[Dict[str, Any]] = None) -> CamofoxSupervisor:
    """获取全局 CamofoxSupervisor 实例"""
    global _supervisor_instance
    if _supervisor_instance is None:
        with _supervisor_lock:
            if _supervisor_instance is None:
                _supervisor_instance = CamofoxSupervisor(config)
    return _supervisor_instance


def reset_camofox_supervisor() -> None:
    """重置(用于测试)"""
    global _supervisor_instance
    with _supervisor_lock:
        _supervisor_instance = None