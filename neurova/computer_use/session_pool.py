"""进程内桌面会话池（CUA Phase 3 扩展 RS-3 核心，非 K8s）

把 Fleet 的 WarmPool/Claim 概念翻译成单进程内的预热/领用/归还/空闲回收。
provider 抽象隔离"会话从哪来"（Windows Sandbox / 容器 / RDP 直连），池只管生命周期。

per-user 隔离：一个会话归属一个用户，claim 只复用同用户的空闲会话。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DesktopSession:
    session_id: str
    base_url: str
    token: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    manager: Any = None  # RemoteComputerUseManager（claim 时惰性建）


class SessionProvider:
    """会话来源抽象（子类实现 create/destroy）。"""

    def create(self, user_id: str) -> DesktopSession:  # pragma: no cover - 接口
        raise NotImplementedError

    def destroy(self, session: DesktopSession) -> None:  # pragma: no cover - 接口
        raise NotImplementedError


class DesktopSessionPool:
    """进程内桌面会话池：claim/release + 空闲 TTL + 容量上限。"""

    def __init__(self, provider: SessionProvider, *, max_sessions: int = 8, idle_ttl: float = 600.0):
        self._provider = provider
        self._max = max_sessions
        self._idle_ttl = idle_ttl
        self._lock = threading.RLock()
        self._all: Dict[str, DesktopSession] = {}
        self._idle: List[str] = []  # 可复用的空闲 session_id
        self._busy: Dict[str, str] = {}  # session_id -> user_id（领用中）

    def claim(self, user_id: str) -> DesktopSession:
        """领用一个会话：优先复用该用户空闲会话，否则新建（受容量上限约束）。"""
        with self._lock:
            for sid in list(self._idle):
                s = self._all.get(sid)
                if s and s.user_id == user_id:
                    self._idle.remove(sid)
                    self._busy[sid] = user_id
                    s.last_used = time.time()
                    return s
            if len(self._all) >= self._max:
                raise RuntimeError(f"桌面会话池已满（max={self._max}）")
            s = self._provider.create(user_id)
            s.session_id = s.session_id or uuid.uuid4().hex[:12]
            self._all[s.session_id] = s
            self._busy[s.session_id] = user_id
            s.last_used = time.time()
            return s

    def release(self, session_id: str) -> None:
        with self._lock:
            s = self._all.get(session_id)
            if not s:
                return
            self._busy.pop(session_id, None)
            s.last_used = time.time()
            if session_id not in self._idle:
                self._idle.append(session_id)

    def reap_idle(self, now: Optional[float] = None) -> int:
        """回收超 TTL 的空闲会话，返回回收数。"""
        now = now if now is not None else time.time()
        reaped = 0
        with self._lock:
            for sid in list(self._idle):
                s = self._all.get(sid)
                if s and (now - s.last_used) >= self._idle_ttl:
                    self._idle.remove(sid)
                    self._all.pop(sid, None)
                    try:
                        self._provider.destroy(s)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("会话销毁失败 %s: %s", sid, e)
                    reaped += 1
        return reaped

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"total": len(self._all), "idle": len(self._idle), "busy": len(self._busy)}


# ── 默认池工厂（提供方名优先级：env 显式 > 设置 advanced.desktop_provider
#    （安全选项卡可配）> 空=无池；与治理设置 env>设置>默认 约定一致）──────────

_default_pool: Optional[DesktopSessionPool] = None
_default_pool_name: str = ""


def _resolve_provider_name() -> str:
    import os

    name = os.environ.get("NEUROVA_DESKTOP_PROVIDER", "").strip()
    if name:
        return name
    try:
        from neurova.core.app_settings import get_advanced_settings

        return str(get_advanced_settings().get("desktop_provider") or "").strip()
    except Exception:  # noqa: BLE001 - 设置不可读按未配置处理（fail-closed 无池）
        return ""


def build_provider(name: str) -> SessionProvider:
    """按名构造会话提供者（sandbox/rdp）。Linux/macOS 远程走 SSH 命令（ssh_exec
    工具），不再有 Linux GUI 容器后端。"""
    name = (name or "").strip().lower()
    if name == "sandbox":
        from neurova.computer_use.sandbox_provider import WindowsSandboxProvider

        return WindowsSandboxProvider()
    if name == "rdp":
        from neurova.computer_use.rdp_provider import RdpDirectProvider

        return RdpDirectProvider()
    raise ValueError(f"未知桌面会话后端: {name!r}（可选 sandbox/rdp）")


def get_default_desktop_pool() -> Optional[DesktopSessionPool]:
    """按配置构建进程内默认会话池；提供方未设/无法识别 → None
    （sandbox/auto 运行档在无池时 fail-closed 拒绝变更动作，不误跑本机）。
    提供方变更即重建（改设置免重启；旧池会话不再复用，由其空闲 TTL 回收）。"""
    global _default_pool, _default_pool_name

    name = _resolve_provider_name()
    if not name:
        return None
    if _default_pool is None or _default_pool_name != name:
        try:
            _default_pool = DesktopSessionPool(build_provider(name))
            _default_pool_name = name
        except Exception as e:  # noqa: BLE001
            logger.error("默认桌面会话池构建失败（provider=%s）: %s", name, e)
            return None
    return _default_pool


def reset_default_desktop_pool() -> None:
    global _default_pool, _default_pool_name
    _default_pool = None
    _default_pool_name = ""
