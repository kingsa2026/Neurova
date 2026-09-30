# -*- coding: utf-8 -*-
"""代码执行沙箱后端：session 承载 + 语言分派 + 后端诚实自报。

## 为什么单独一层

`neurova/sandbox/exec_sandbox.py` 是**一次性命令**的隔离执行面（治理层用它跑
工具命令）。代码执行沙箱要的是**有状态的会话**：同一 session 里连跑多段代码、
镜像与超时归 session 持有、执行后要读回 exit_code / stdout / stderr / 耗时。

本模块是沙箱 session 的执行后端，判据只写一份：

- **后端选择**：`auto` = Docker 可用则容器（跨平台真隔离），否则平台后端并
  **自报 `enforced=False`**（不谎称隔离）；`docker` = 强制容器，不可用即报错，
  **不静默降级成裸跑**（教义第 1/2 条：降级必须显形）。
- **语言分派**：语言 → 解释器 argv，白名单外显式拒绝（不许当 python 跑）。
- **诚实自报**：每次执行都带 `backend` 与 `enforced`。

复用 `exec_sandbox` 的后端探测与进程树杀灭，不另造隔离体系（教义第 6 条）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.sandbox.exec_sandbox import (
    SandboxSeverity,
    docker_available,
    get_exec_sandbox,
    killProcessTree,
    spawnKwargsForKill,
)

logger = get_logger(__name__)


class SandboxLanguageError(ValueError):
    """语言不在支持集内。"""


class SandboxBackendUnavailable(RuntimeError):
    """请求的隔离后端不可用（显式拒绝，不静默降级）。"""


#: 语言 → (解释器可执行名, argv 前缀, 源码文件后缀)
#: 只认可解释器**显式**调用的四种语言；其余显式拒绝（诚实报错优于改语义）
LANGUAGES: Dict[str, Dict[str, Any]] = {
    "python": {
        "executable": sys.executable,
        "argv": [],
        "suffix": ".py",
        "imageFallback": "python",
    },
    "shell": {
        "executable": "sh",
        "argv": [],
        "suffix": ".sh",
        "imageFallback": "shell",
    },
    "bash": {
        "executable": "bash",
        "argv": [],
        "suffix": ".sh",
        "imageFallback": "shell",
    },
    "javascript": {
        "executable": "node",
        "argv": [],
        "suffix": ".js",
        "imageFallback": "node",
    },
    "node": {
        "executable": "node",
        "argv": [],
        "suffix": ".js",
        "imageFallback": "node",
    },
}

#: 语言别名收口（前端下拉值 → 规范名）
LANGUAGE_ALIASES = {"js": "javascript"}


def supportedLanguages() -> List[str]:
    """支持的语言（有限枚举，与前端下拉对齐）。"""
    return ["python", "shell", "javascript"]


def _canonicalLanguage(language: str) -> str:
    normalized = (language or "").strip().lower()
    normalized = LANGUAGE_ALIASES.get(normalized, normalized)
    if normalized == "bash":
        normalized = "shell"
    if normalized == "node":
        normalized = "javascript"
    if normalized not in supportedLanguages():
        raise SandboxLanguageError(
            f"语言 '{language}' 不支持；可选：{supportedLanguages()}"
        )
    return normalized


def _resolveExecutable(language: str) -> Optional[str]:
    spec = LANGUAGES[language]
    candidate = spec["executable"]
    if os.path.isabs(candidate) and Path(candidate).exists():
        return candidate
    found = shutil.which(candidate)
    if found is None:
        raise SandboxBackendUnavailable(
            f"语言 {language} 的解释器 '{candidate}' 不在本机——"
            "不静默换成别的解释器执行（Windows 请改用 python/javascript 语言）"
        )
    return found


class _Enforcer:
    """超时兜底：到点无条件杀进程树，不依赖被监控方配合。

    为什么 `communicate(timeout=...)` 不够：它只杀**直接子进程**。解释器被
    包装器（venv 启动器、`sh -c`）套一层时，信号到不了真正在跑的那个进程，
    调用方要等满 timeout 才回来 —— 实测 `python -c` 走 venv 包装时即如此，
    `timeout=2` 却跑了整段 `sleep 60`。这正是「声明了限制却没人执行」的形态。
    """

    def __init__(self, proc: subprocess.Popen, timeout: float):
        self._proc = proc
        self._timeout = timeout
        self._timer: Optional[threading.Timer] = None
        self._fired = threading.Event()

    def arm(self) -> None:
        self._timer = threading.Timer(self._timeout, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        self._fired.set()
        try:
            killProcessTree(self._proc)
        except Exception as exc:  # noqa: BLE001 - 兜底杀失败不阻断收尸路径
            logger.warning("沙箱超时兜底杀进程失败: %s", exc)

    def fired(self) -> bool:
        return self._fired.is_set()

    def disarm(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class CodeSandboxSession:
    """一个代码执行沙箱 session：持有镜像/后端选择与工作目录。

    线程安全由调用方（端点层）串行化到 `asyncio.to_thread`，本类自身无共享可变态。
    """

    def __init__(self, image: str = "python:3.11-slim", backend: str = "auto"):
        self.image = image
        self.backend = backend
        self._workspace: Optional[Path] = None
        self._closed = False

    # ── 后端选择（唯一判据）──────────────────────────

    def resolveBackend(self) -> Dict[str, Any]:
        """返回 `{backend, enforced, severity, reason}`。

        - `backend="docker"`：不可用 → 抛 `SandboxBackendUnavailable`（不降级）；
        - `backend="auto"`：Docker 可用 → 容器；否则平台后端，`enforced` 取后端自报。
        """
        if self.backend == "docker":
            if not docker_available():
                raise SandboxBackendUnavailable(
                    "Docker 后端不可用（docker info 探测失败），无法提供容器隔离"
                )
            return {"backend": "docker", "enforced": True, "severity": SandboxSeverity.FULL,
                    "reason": "请求 backend=docker"}

        if docker_available():
            return {"backend": "docker", "enforced": True, "severity": SandboxSeverity.FULL,
                    "reason": "Docker 可用，auto 优先容器（跨平台真隔离）"}

        severity = SandboxSeverity.NETWORK_OFF
        platform_backend = get_exec_sandbox(severity)
        enforced = platform_backend.enforced()
        return {
            "backend": platform_backend.backend_name(),
            "enforced": enforced,
            "severity": severity,
            # 文案必须跟着值走：原先硬写"自报 enforced=False"，而后端如实回 True 时
            # 这句话就成了替机器撒谎的第二个事实源（补齐 enforced() 的同一批里撞出来的）
            "reason": (
                "Docker 不可用，平台后端自报已落实该档隔离"
                if enforced
                else "Docker 不可用且平台后端无内核隔离 → 自报 enforced=False"
            ),
        }

    def workspace(self) -> Path:
        if self._workspace is None or not self._workspace.exists():
            self._workspace = Path(tempfile.mkdtemp(prefix="neurova_sbx_"))
        return self._workspace

    # ── 执行 ────────────────────────────────────────

    def execute(self, command: str, language: str, timeout: float) -> Dict[str, Any]:
        """真跑一段代码，返回统一形状的产物（含 backend / enforced / timed_out）。

        超时是**硬约束**：`communicate(timeout=...)` 之外的 `_Enforcer` 兜底定时器
        在到点时无条件杀树 —— 解释器自行吞掉 SIGTERM（如 venv 包装器）或阻塞在
        不可中断等待里时，不靠被监控方配合也能掐断。
        """
        if self._closed:
            raise SandboxBackendUnavailable("该沙箱 session 已关闭")
        canonical = _canonicalLanguage(language)

        resolved = self.resolveBackend()
        if resolved["backend"] == "docker":
            return self._executeInContainer(command, canonical, timeout, resolved)
        return self._executeOnPlatform(command, canonical, timeout, resolved)

    def _executeOnPlatform(self, command, language, timeout, resolved) -> Dict[str, Any]:
        executable = _resolveExecutable(language)
        if executable is None:
            raise SandboxBackendUnavailable(
                f"语言 {language} 的解释器不在本机（{LANGUAGES[language]['executable']}）——"
                "不静默换成别的解释器执行"
            )
        workspace = self.workspace()
        source = workspace / f"snippet_{uuid.uuid4().hex[:8]}{LANGUAGES[language]['suffix']}"
        source.write_text(command, encoding="utf-8")

        argv = [executable, *LANGUAGES[language]["argv"], str(source)]

        started = time.time()
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **_spawnKwargs(),
            )
        except OSError as exc:
            raise SandboxBackendUnavailable(f"解释器启动失败：{exc}") from exc

        enforcer = _Enforcer(proc, timeout)
        enforcer.arm()
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            killProcessTree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:  # noqa: BLE001 - 收尸失败不改变超时结果契约
                stdout, stderr = "", ""
            exit_code = -1
        finally:
            enforcer.disarm()

        if enforcer.fired():
            timed_out = True
            if exit_code == 0:
                exit_code = -1
            if "timed out" not in (stderr or ""):
                stderr = (stderr or "") + f"\n[sandbox] command timed out after {timeout}s"

        return {
            "stdout": stdout or "",
            "stderr": stderr or "",
            "exit_code": exit_code,
            "backend": resolved["backend"],
            "enforced": bool(resolved["enforced"]),
            "timed_out": timed_out,
            "duration_ms": round((time.time() - started) * 1000, 2),
        }

    def _executeInContainer(self, command, language, timeout, resolved) -> Dict[str, Any]:
        """容器执行：语言 → 容器内解释器 argv（镜像自带 python/node）。"""
        workspace = self.workspace()
        suffix = LANGUAGES[language]["suffix"]
        source = workspace / f"snippet_{uuid.uuid4().hex[:8]}{suffix}"
        source.write_text(command, encoding="utf-8")

        if language == "python":
            inner = ["python", f"/work/{source.name}"]
        elif language == "javascript":
            inner = ["node", f"/work/{source.name}"]
        else:
            inner = ["sh", f"/work/{source.name}"]

        argv = [
            "docker", "run", "--rm",
            "--network=none",
            "--read-only",
            "--memory=512m",
            "--pids-limit=128",
            "--user", "nobody",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", f"{workspace}:/work:ro",
            "-w", "/work",
            self.image,
            *inner,
        ]
        started = time.time()
        timed_out = False
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as exc:
            raise SandboxBackendUnavailable(f"Docker 启动失败：{exc}") from exc

        enforcer = _Enforcer(proc, timeout)
        enforcer.arm()
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            killProcessTree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:  # noqa: BLE001
                stdout, stderr = "", ""
            exit_code = -1
        finally:
            enforcer.disarm()

        if enforcer.fired():
            timed_out = True
            if exit_code == 0:
                exit_code = -1
            if "timed out" not in (stderr or ""):
                stderr = (stderr or "") + f"\n[sandbox] container timed out after {timeout}s"

        return {
            "stdout": stdout or "",
            "stderr": stderr or "",
            "exit_code": exit_code,
            "backend": "docker",
            "enforced": True,
            "timed_out": timed_out,
            "duration_ms": round((time.time() - started) * 1000, 2),
        }

    def close(self) -> None:
        self._closed = True
        if self._workspace and self._workspace.exists():
            shutil.rmtree(self._workspace, ignore_errors=True)
        self._workspace = None


def _spawnKwargs() -> Dict[str, Any]:
    """转发到 `exec_sandbox.spawnKwargsForKill`（单源；本处是历史函数名契约）。"""
    return spawnKwargsForKill()




__all__ = [
    "CodeSandboxSession",
    "SandboxLanguageError",
    "SandboxBackendUnavailable",
    "dockerAvailable",
    "supportedLanguages",
    "LANGUAGES",
]


def dockerAvailable() -> bool:
    """Docker 可用性（薄封装：判据单源在 `exec_sandbox.docker_available`）。"""
    return docker_available()
