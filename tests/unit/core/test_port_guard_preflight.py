# -*- coding: utf-8 -*-
"""启动端口预检（Issue #189）：端口占用必须在重型装配之前判定并诚实报出。

根因（实测）：`start_server.py` 直接 `uvicorn.run`，而 uvicorn 的启动次序是
`lifespan.startup()` **先跑完**再 `loop.create_server()`（uvicorn `Server.startup`）。
于是 4 个 Agent / LLM providers / DB / torch 预检 / 1253 行日志全部装配完毕，
才在最后一步死于 `EADDRINUSE`——真正的失败信息埋在日志尾部，且失败路径还要再跑
一遍完整关机（每 Agent 一次睡眠整理写回）。

同时 `scripts/port_utils.py` 早已有 `check_port()` 且被 `start.py:54` 使用——
两套启动器对"端口占用"这件事的判据不一致（一份在 `scripts/` 里，容器/桌面入口
根本拿不到：打包只带 `neurova/` + `start_server.py`）。

本文件钉两件事：
- 判据单一事实源 `neurova/core/port_guard.py`（scripts 侧委托过来，不是第二份）；
- `start_server.py` 的预检必须**先于** `create_app()`——结构判据（AST 行号），
  不用墙钟上界（那种判据在 CI 共享负载下会误红）。
"""
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
START_SERVER = PROJECT_ROOT / "start_server.py"


def _listeningSocket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


class TestPortGuardIsSingleSource:
    """端口占用判据只允许一份实现，且落点在 `neurova/`（容器入口拿得到）。"""

    def test_free_port_is_not_occupied(self):
        from neurova.core.port_guard import isPortOccupied

        sock = _listeningSocket()
        port = sock.getsockname()[1]
        sock.close()
        assert isPortOccupied(port) is False

    def test_listening_port_is_occupied(self):
        from neurova.core.port_guard import isPortOccupied

        sock = _listeningSocket()
        try:
            assert isPortOccupied(sock.getsockname()[1]) is True
        finally:
            sock.close()

    def test_listenerPidsReportsTheRealOwner(self):
        import os

        from neurova.core.port_guard import findPortListeners

        sock = _listeningSocket()
        try:
            pids = findPortListeners(sock.getsockname()[1])
            assert os.getpid() in pids, f"占用者 PID 未识别出来: {pids}"
        finally:
            sock.close()

    def test_scripts_port_utils_delegates_to_the_same_judgement(self):
        """`scripts/port_utils.check_port` 不得是第二份判据。"""
        import io

        src = io.open(PROJECT_ROOT / "scripts" / "port_utils.py", encoding="utf-8").read()
        assert "neurova.core.port_guard" in src, (
            "scripts/port_utils.check_port 仍是自成一体的第二份占用判据——"
            "两套启动器的行为一致性无从保证（Issue #189 主诉）。"
        )


class TestPreflightFailsBeforeHeavyAssembly:
    def test_occupiedPortRaisesWithPortAndOwner(self):
        from neurova.core.port_guard import PortUnavailableError, preflightPortAvailable

        sock = _listeningSocket()
        port = sock.getsockname()[1]
        try:
            with pytest.raises(PortUnavailableError) as excinfo:
                preflightPortAvailable("127.0.0.1", port)
            message = str(excinfo.value)
            assert str(port) in message, "失败信息里没有端口号"
            assert "占用" in message, "失败信息没有点明端口被占用"
        finally:
            sock.close()

    def test_freePortPassesPreflight(self):
        from neurova.core.port_guard import preflightPortAvailable

        sock = _listeningSocket()
        port = sock.getsockname()[1]
        sock.close()
        preflightPortAvailable("127.0.0.1", port)


class TestStartServerPreflightOrder:
    """结构判据：预检调用必须出现在 `create_app()` 之前（AST 行号）。"""

    @staticmethod
    def _callLines(function_name: str) -> list[int]:
        tree = ast.parse(START_SERVER.read_text(encoding="utf-8"))
        lines: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == function_name:
                lines.append(node.lineno)
            elif isinstance(func, ast.Attribute) and func.attr == function_name:
                lines.append(node.lineno)
        return lines

    def test_preflightPrecedesAppCreation(self):
        preflight = self._callLines("preflightPortAvailable")
        assert preflight, (
            "start_server.py 没有任何端口预检调用——uvicorn 会在 lifespan 装配完成"
            "之后才 bind，失败信息只能埋在 1253 行日志的尾部（Issue #189 主诉）。"
        )
        created = self._callLines("create_app")
        assert created, "找不到 create_app 调用，判据前提失效"
        assert min(preflight) < min(created), (
            f"端口预检在第 {min(preflight)} 行，create_app 在第 {min(created)} 行——"
            "预检必须在前，否则重型装配照跑不误。"
        )


class TestEveryLauncherSharesTheSameJudgement:
    """放大视角（教义第 5 条）：同一契约的全部消费方一并修。

    全仓除 `start_server.py` 外还有两条"先造 app、再 `uvicorn.run`"的入口，
    同一个根因（重型装配跑在前面，端口失败落在最后一行）：
    - `neurova/api/app.py:run_server`（同后端的进程内入口，被 `__main__` 使用）；
    - `neurova/guest_agent/server.py:main`（来宾守护进程）。

    判据与主入口一致：预检调用出现在应用创建/服务运行之前。
    """

    @staticmethod
    def _firstCallLine(src: str, names: tuple[str, ...]) -> int | None:
        tree = ast.parse(src)
        lines: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            target = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if target in names:
                lines.append(node.lineno)
        return min(lines) if lines else None

    @pytest.mark.parametrize(
        "rel,app_call",
        [
            ("neurova/api/app.py", "create_app"),
            ("neurova/guest_agent/server.py", "create_app"),
        ],
    )
    def test_preflightPrecedesAppCreation(self, rel, app_call):
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        preflight = self._firstCallLine(src, ("preflightPortAvailable",))
        assert preflight is not None, (
            f"{rel} 未接端口预检——同一契约的消费方漏了一处（教义第 5 条）"
        )
        app_line = self._firstCallLine(src, (app_call,))
        assert app_line is not None, f"{rel} 找不到 {app_call}，判据前提失效"
        assert preflight < app_line, (
            f"{rel}: 预检在第 {preflight} 行，{app_call} 在第 {app_line} 行——预检必须在前"
        )
