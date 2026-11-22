# -*- coding: utf-8 -*-
"""沙箱第二档：Docker 容器档（强隔离执行后端）。

## 定位

`exec_sandbox` 的平台档（bwrap/Seatbelt/AppContainer/ProcessSandbox）与
`code_sandbox` 的 auto 档之上，本模块提供**显式请求强隔离**时的一次性容器
执行面：把一段代码放进 `--network none --read-only --cap-drop ALL` 的容器里跑，
宿主文件系统只经挂载白名单（/work 只读）进入容器，超时到点停容器。

## 与既有实现的关系（教义第 6 条：不新造平行体系）

- Docker 可用性判定**单源**复用 `exec_sandbox.docker_available()`（含全局
  缓存），本模块不建第二份 `docker info` 探测；
- 进程树杀灭与成团参数复用 `exec_sandbox.killProcessTree` /
  `spawnKwargsForKill`，收尸窗口复用 `KILL_GRACE_S`；
- 容器 argv 与 `code_sandbox` 的容器路径同族（--network none / --read-only /
  --cap-drop ALL / tmpfs /tmp / 挂载 /work），差异仅本档规格要求的资源上限
  （--cpus、--pids-limit 64、tmpfs 16m）与镜像档位（python:3.12-slim）。

## 诚实自报

- docker 不可用：`availability()`=False；`run_code` 返回 `enforced=False` 的
  不可用结果（不谎称隔离，也不静默降级成裸跑）；
- 语言：本期仅 python；js/ts 需 node 镜像，显式 `SandboxLanguageUnsupported`
  点名原因，其余语言同样显式 unsupported，不悄悄改语义；
- 镜像：本地已有则用；缺失则 pull 一次并记日志；拉取失败显式报错，不静默换镜像。

可选依赖 fail-soft：docker CLI 是外部可执行文件，探测/执行全部经 subprocess
按需调用；CLI 缺失、守护进程未启动、调用超时一律归入"不可用/失败"路径，
不在模块顶层做任何会拖垮 import 的动作。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set

from neurova.core.logger import get_logger
from neurova.sandbox.exec_sandbox import (
    KILL_GRACE_S,
    docker_available,
    killProcessTree,
    spawnKwargsForKill,
)

logger = get_logger(__name__)

__all__ = [
    "DEFAULT_PYTHON_IMAGE",
    "ContainerSandbox",
    "SandboxImageUnavailable",
    "SandboxLanguageUnsupported",
    "SandboxResult",
]

#: 容器档默认镜像：python 优先（本地已有则用，无则 pull 一次并记录）
DEFAULT_PYTHON_IMAGE = "python:3.12-slim"

#: 资源上限（本档规格）：断网 + 只读根文件系统 + 受限内存/CPU/进程数
_TMPFS_SPEC = "/tmp:rw,noexec,nosuid,size=16m"
_MEMORY_LIMIT = "512m"
_CPU_LIMIT = "1"
_PIDS_LIMIT = "64"

#: 超时后给 `docker stop` 与 CLI 退出的宽裕量（秒）：
#: 定时器在 timeout_s 到点停容器，communicate 以 timeout_s + 该宽裕量兜底等待
_STOP_GRACE_S = 10.0
#: 镜像存在性探测（docker image inspect）超时
_IMAGE_PROBE_TIMEOUT_S = 15.0
#: 一次性 pull 的上界（大镜像冷拉也应在分钟级内完成）
_PULL_TIMEOUT_S = 600.0

#: js/ts 需 node 镜像——本期容器档仅 python，显式 unsupported（不悄悄换镜像）
_NODE_IMAGE_LANGUAGES = frozenset({"javascript", "js", "node", "typescript", "ts"})

#: 镜像 pull 的进程级互斥（DCL 外层）：并发首次执行只拉一次
_PULL_LOCK = threading.Lock()


class SandboxLanguageUnsupported(ValueError):
    """语言不受容器档支持（js/ts 需 node 镜像，本期仅 python；诚实 unsupported）。"""


class SandboxImageUnavailable(RuntimeError):
    """容器镜像本地缺失且拉取失败（显式报错，不静默换镜像）。"""


@dataclass(frozen=True)
class SandboxResult:
    """容器档执行产物（调用方契约字段一次定死）。

    - `enforced=True`：代码确实在强隔离容器里跑过；
    - `enforced=False`：docker 不可用等原因导致**没有执行**，`detail` 带诚实
      原因——调用方不得把它当作"已隔离的成功/失败执行"消费。
    """

    stdout: str
    stderr: str
    exit_code: int
    enforced: bool
    duration_ms: float
    backend: str = "docker"
    timed_out: bool = False
    detail: str = ""

    @property
    def duration(self) -> float:
        """秒级耗时（与 duration_ms 同源，方便按秒判读）。"""
        return self.duration_ms / 1000.0


def _requirePython(language: str) -> None:
    """语言先验：仅 python；js/ts 点名"需 node 镜像"，其余诚实 unsupported。"""
    normalized = (language or "").strip().lower()
    if normalized in _NODE_IMAGE_LANGUAGES:
        raise SandboxLanguageUnsupported(
            f"语言 '{language}' 需 node 镜像，容器档本期仅 python，暂不支持 js/ts"
        )
    if normalized != "python":
        raise SandboxLanguageUnsupported(
            f"语言 '{language}' 不受容器档支持：本期仅 python"
        )


class ContainerSandbox:
    """Docker 容器档：把一段代码放进一次性强隔离容器执行。

    用法（本卡只交付模块本身；`tool_executor` 的 isolation="strong" 分派
    接线是后续卡）::

        sandbox = ContainerSandbox()
        if sandbox.availability():
            result = sandbox.run_code("print(6*7)")
    """

    def __init__(self, image: str = DEFAULT_PYTHON_IMAGE):
        self.image = image
        self._availabilityCache: Optional[bool] = None
        self._pulledImages: Set[str] = set()

    # ── 可用性（判定单源 + 缓存）─────────────────────

    def availability(self) -> bool:
        """docker CLI 可用性：`shutil.which` 快路径 + `docker info` 轻量验证。

        判定单源：`docker info` 探测复用 `exec_sandbox.docker_available()`
        （其内部已带全局缓存）；本方法只补 which 快路径并缓存结论，
        不建第二份探测。
        """
        if self._availabilityCache is None:
            if shutil.which("docker") is None:
                self._availabilityCache = False
            else:
                self._availabilityCache = docker_available()
        return self._availabilityCache

    # ── 执行 ────────────────────────────────────────

    def run_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_s: float = 60.0,
        workdir_files: Optional[Dict[str, bytes]] = None,
    ) -> SandboxResult:
        """在一次性容器里执行一段 python 代码。

        - docker 不可用 → 返回 `enforced=False` 的不可用结果（不谎报、不裸跑）；
        - 工作文件写入临时目录，只读挂载到 /work；容器根文件系统只读、断网、
          受限内存/CPU/进程数；超时到点停容器；
        - `workdir_files`：相对路径 → 内容（bytes），随 /work 进入容器。
        """
        _requirePython(language)
        started = time.time()
        if not self.availability():
            reason = (
                "Docker 不可用（docker CLI 缺失或 docker info 探测失败），"
                "容器档无法提供隔离执行——不降级为裸跑"
            )
            logger.warning("容器档拒绝执行：%s", reason)
            return SandboxResult(
                stdout="",
                stderr=reason,
                exit_code=-1,
                enforced=False,
                duration_ms=0.0,
                backend="docker",
                timed_out=False,
                detail=reason,
            )

        workdir = Path(tempfile.mkdtemp(prefix="neurova_container_sbx_"))
        try:
            # POSIX 下 mkdtemp 默认 0700，容器内 --user nobody 无法穿越；
            # 放开目录与文件读权限，只读挂载的隔离语义不受影响。
            os.chmod(workdir, 0o755)
            for relPath, content in (workdir_files or {}).items():
                self._writeWorkdirFile(workdir, relPath, content)
            snippet = workdir / "__neurova_snippet__.py"
            snippet.write_text(code, encoding="utf-8")
            os.chmod(snippet, 0o644)

            self._ensureImagePulled(self.image)
            return self._runContainer(snippet, workdir, timeout_s, started)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _writeWorkdirFile(workdir: Path, relPath: str, content) -> None:
        """把一个工作文件写进挂载白名单（临时目录），拒绝路径越界。"""
        rel = Path(relPath)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"workdir_files 路径越界：{relPath!r}")
        target = workdir / rel
        if isinstance(content, str):
            content = content.encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        os.chmod(target, 0o644)

    def _ensureImagePulled(self, image: str) -> None:
        """本地已有则用；缺失则 pull 一次（DCL + 日志记录），失败显式报错。"""
        if self._imagePresent(image):
            return
        with _PULL_LOCK:
            if image in self._pulledImages or self._imagePresent(image):
                return
            logger.warning("容器档镜像 %s 本地缺失，执行一次性 docker pull", image)
            try:
                pull = subprocess.run(
                    ["docker", "pull", image],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_PULL_TIMEOUT_S,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SandboxImageUnavailable(
                    f"镜像 {image} 拉取失败：{exc}——不静默换成别的镜像执行"
                ) from exc
            if pull.returncode != 0:
                tail = (pull.stderr or pull.stdout or "").strip()[-300:]
                raise SandboxImageUnavailable(
                    f"镜像 {image} 拉取失败（{tail}）——不静默换成别的镜像执行"
                )
            self._pulledImages.add(image)
            logger.info("容器档镜像 %s 拉取完成", image)

    @staticmethod
    def _imagePresent(image: str) -> bool:
        try:
            probe = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                timeout=_IMAGE_PROBE_TIMEOUT_S,
            )
            return probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _runContainer(
        self, snippet: Path, workdir: Path, timeout_s: float, started: float
    ) -> SandboxResult:
        """起容器执行代码片段；超时到点停容器，资源与网络限制见模块常量。"""
        containerName = f"neurova-sbx-{uuid.uuid4().hex[:12]}"
        argv = [
            "docker", "run", "--rm",
            "--name", containerName,
            "--network", "none",
            "--read-only",
            "--tmpfs", _TMPFS_SPEC,
            "--memory", _MEMORY_LIMIT,
            "--cpus", _CPU_LIMIT,
            "--pids-limit", _PIDS_LIMIT,
            "--user", "nobody",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "-v", f"{workdir}:/work:ro",
            "-w", "/work",
            self.image,
            "python", f"/work/{snippet.name}",
        ]
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **spawnKwargsForKill(),
            )
        except OSError as exc:
            return SandboxResult(
                stdout="",
                stderr=f"Docker 启动失败：{exc}",
                exit_code=-1,
                enforced=False,
                duration_ms=self._elapsedMs(started),
                backend="docker",
                timed_out=False,
                detail=f"Docker 启动失败：{exc}",
            )

        timedOut = threading.Event()

        def stopContainerOnTimeout() -> None:
            """超时=容器 stop：CLI 被杀后容器不会自动退出，须显式停掉。"""
            timedOut.set()
            killProcessTree(proc)
            try:
                subprocess.run(
                    ["docker", "stop", "-t", "2", containerName],
                    capture_output=True,
                    timeout=15,
                )
            except Exception as exc:  # noqa: BLE001 - 兜底停容器失败不阻断收尸
                logger.warning("超时停容器失败（%s）：%s", containerName, exc)

        timer = threading.Timer(timeout_s, stopContainerOnTimeout)
        timer.daemon = True
        timer.start()
        stdout = stderr = ""
        exitCode: int = -1
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s + _STOP_GRACE_S)
            exitCode = proc.returncode if proc.returncode is not None else -1
        except subprocess.TimeoutExpired:
            stopContainerOnTimeout()
            try:
                stdout, stderr = proc.communicate(timeout=KILL_GRACE_S)
            except Exception:  # noqa: BLE001 - 收尸失败不改变超时结果契约
                stdout, stderr = "", ""
            exitCode = -1
        finally:
            timer.cancel()

        if timedOut.is_set():
            if exitCode == 0:
                exitCode = -1
            if "timed out" not in (stderr or ""):
                stderr = (stderr or "") + f"\n[sandbox] container timed out after {timeout_s}s"

        return SandboxResult(
            stdout=stdout or "",
            stderr=stderr or "",
            exit_code=int(exitCode),
            enforced=True,
            duration_ms=self._elapsedMs(started),
            backend="docker",
            timed_out=timedOut.is_set(),
            detail="",
        )

    @staticmethod
    def _elapsedMs(started: float) -> float:
        return round((time.time() - started) * 1000.0, 2)
