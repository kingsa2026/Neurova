# -*- coding: utf-8 -*-
"""端口可用性判据 —— 全仓唯一实现。

为什么要有这个模块：判断"这个端口能不能起服务"此前有两套互不相干的实现
（`scripts/port_utils.check_port` 用 connect 探活，`start_server.py` 干脆不判、
等 uvicorn 在装配完之后死），于是同一台机器上 `start.py` 与容器/桌面入口对
"端口被占"的反应完全不同——一处提前提示，一处跑完 8 秒全量装配再倒在倒数第二行。

判据选型：**以"本进程能不能在该端点 bind 成功"为准**，而不是"有没有人连着"。
理由是可证伪的——uvicorn 起服务做的就是 `setsockopt(SO_REUSEADDR)` + `bind`；
一个只被 bind、尚未 listen 的端口，connect 探活说"空闲"，而真正的服务起不来。
判据与实际动作同形，才不会出现"预检说没事、启动却失败"。

落点在 `neurova/` 而不是 `scripts/`：生产容器只拷 `neurova/` + `start_server.py`
（见 Dockerfile 与 `scripts/desktop/bundle_backend.py`），判据必须在入口拿得到的包里。
`scripts/port_utils.py` 改为委托本模块，不再是第二份判据。

`findPortListeners` 是纯观测面（错误信息里点名占用者），不在这里杀进程：
释放端口是启动器的策略选择，不是判据该干的事。
"""

from __future__ import annotations

import errno
import socket
from typing import List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: IPv4/IPv6 双栈探测端点：服务可能只监听其中一个（`0.0.0.0` 与 `::` 在部分
#: 系统上互不冲突）。两个都试，"任一个 bind 不了"才算被占。
_WILDCARD_ENDPOINTS: Tuple[str, ...] = ("0.0.0.0", "::")

#: bind 失败里属于"本机不支持该地址族/该地址"的，跳过而不是判占用——
#: 那是探测能力不足，不是端口被占（不许把"测不出"记成"测出有问题"）。
_PROBE_UNAVAILABLE = frozenset(
    errno for errno in (
        getattr(errno, "EAFNOSUPPORT", None),
        getattr(errno, "EADDRNOTAVAIL", None),
        getattr(errno, "EPROTONOSUPPORT", None),
    ) if errno is not None
)


class PortUnavailableError(RuntimeError):
    """端口不可用（被占用）。携带端口与占用者，便于调用方原样报出。"""

    def __init__(self, host: str, port: int, pids: Optional[List[int]] = None):
        self.host = host
        self.port = port
        self.pids = list(pids or [])
        detail = f"，占用进程 {self.pids}" if self.pids else "（占用者进程未知，可能属其它用户或已名进程）"
        super().__init__(
            f"端口 {port} 已被占用{detail}——服务未启动。"
            f"请先释放该端口（{host}:{port}）或改用 NEUROVA_PORT 指定其它端口。"
        )


def _bindAttempt(target: str, port: int) -> Optional[OSError]:
    """尝试在 target:port 上按 uvicorn 的同一手法 bind。能 bind 返回 None。"""
    family = socket.AF_INET6 if ":" in target else socket.AF_INET
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError as exc:  # 地址族不可用
        return exc
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((target, port))
        return None
    except OSError as exc:
        return exc
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _connectProbe(targets: Tuple[str, ...], port: int) -> bool:
    """兜底探活（bind 判不出来时用）：有监听者即视为占用。"""
    for target in targets:
        family = socket.AF_INET6 if ":" in target else socket.AF_INET
        host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def isPortOccupied(port: int, host: str = "") -> bool:
    """端口能否被本进程按 uvicorn 的手法绑定（不能即"被占用"）。

    参数:
        port: 端口号
        host: 目标监听地址；缺省时按通配地址（`0.0.0.0` / `::`）双栈探测
    """
    targets = (host,) if host else _WILDCARD_ENDPOINTS
    for target in targets:
        failure = _bindAttempt(target, port)
        if failure is None:
            continue
        if failure.errno in _PROBE_UNAVAILABLE:
            continue  # 该地址族探测不了，换下一个/兜底
        if failure.errno == errno.EADDRINUSE:
            return True
        return True  # 其它 bind 失败（权限等）一律按"不可用"处理，不假报可用
    # 所有地址族都探测不了（罕见）：退回 connect 探活，宁可给出一个可用的判据，
    # 也不假装"端口空闲"（假阴性会直接把故障推到装配之后）。
    return _connectProbe(_WILDCARD_ENDPOINTS, port)


def findPortListeners(port: int) -> List[int]:
    """占用该端口的进程 PID（尽力而为；取不到返回空表，不抛错）。

    psutil 在 CI 与运行时都已声明（`requirements.txt` / `requirements-ci.txt`）；
    缺席时退回系统命令，再不行就返回空表——观测面缺失不该阻断启动。
    """
    pids: List[int] = []
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            if laddr and laddr.port == int(port) and conn.pid:
                if conn.pid not in pids:
                    pids.append(int(conn.pid))
        return pids
    except Exception as exc:  # noqa: BLE001 - 观测面降级
        logger.debug("端口占用者查询降级（psutil 不可用）: %s", exc)
    return pids


def preflightPortAvailable(host: str, port: int) -> None:
    """启动前的端口预检：不可用即抛 `PortUnavailableError`（点名端口与占用者）。

    调用点必须在重型装配**之前**——本项目全量装配（Agent / LLM providers / DB /
    torch 预检）实测约 8 秒，装配完才在 uvicorn 的 bind 上失败，等于把唯一有用的
    信息埋在日志尾部，还顺带触发一次完整关机整理。
    """
    if isPortOccupied(port, host):
        raise PortUnavailableError(host, port, findPortListeners(port))
