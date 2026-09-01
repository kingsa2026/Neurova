"""
内核级执行沙箱 (对齐 QwenPaw Sandbox)。

提供跨平台进程隔离能力：
- Linux: bubblewrap (bwrap) 文件系统/网络隔离
- macOS: Seatbelt (sandbox-exec)
- Windows: AppContainer（受限执行，降级为常规执行并标注）
- 通用降级: ProcessSandbox（无内核隔离，仅进程级）

所有后端对外暴露统一的 `execute()` 接口，返回与 CLIToolExecutor 兼容的字典。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class SandboxSeverity(str, Enum):
    """隔离强度等级（与 QwenPaw Governance 对齐）"""

    NONE = "none"  # 不隔离（同进程）
    NETWORK_OFF = "network_off"  # 禁网络
    READ_ONLY = "read_only"  # 只读文件系统
    FULL = "full"  # 禁网络 + 只读 + 受限 fs


class ExecSandbox:
    """沙箱执行基类。"""

    def __init__(self, severity: SandboxSeverity = SandboxSeverity.NONE):
        self.severity = severity

    def available(self) -> bool:
        """当前平台是否支持该后端。"""
        return True

    def backend_name(self) -> str:
        return "process"

    def wrap_argv(self, command: str) -> List[str]:
        """返回执行用 argv 列表；子类重写以注入隔离前缀。

        默认 shell 语义（管道/重定向由 shell 处理）：POSIX 走 sh -c，
        Windows 走 cmd /c。argv 传递消除引号转义层（比 shell=True 更安全）。
        """
        if sys.platform == "win32":
            return ["cmd.exe", "/c", command]
        return ["sh", "-c", command]

    def enforced(self) -> bool:
        """该后端是否真实落实了声明的隔离（P1-7 诚实化：占位实现返回 False）。

        子类按平台能力重写；False 时调用方结果将携带 sandbox_enforced=False
        与 warning 自报，治理层据此升级裁决（拒绝优于静默放行）。
        """
        return False

    def _base_result(self) -> Dict[str, Any]:
        enforced = self.enforced()
        result: Dict[str, Any] = {
            "sandbox": self.backend_name(),
            # P1-7：隔离真实性自报——占位后端必须承认未隔离
            "sandbox_enforced": enforced,
            "isolated": enforced,
        }
        if self.severity != SandboxSeverity.NONE and not enforced:
            result["warning"] = (
                f"沙箱后端 {self.backend_name()} 未强制 severity="
                f"{self.severity.value}（无内核隔离），请求被降级执行"
            )
            logger.warning(
                "沙箱未强制: backend=%s severity=%s（配置了隔离但平台不支持）",
                self.backend_name(),
                self.severity.value,
            )
        return result

    def execute(
        self,
        command: str,
        timeout: float = 30.0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        argv = self.wrap_argv(command)
        base = self._base_result()
        try:
            result = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
            return {
                **base,
                "success": result.returncode == 0,
                "output": result.stdout or "",
                "error": result.stderr or "",
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                **base,
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout} seconds",
                "return_code": -1,
            }
        except Exception as e:  # noqa: BLE001 - 沙箱执行需捕获一切异常以保证可用
            return {
                **base,
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
            }


class ProcessSandbox(ExecSandbox):
    """默认沙箱：仅进程级执行（无内核隔离），用于降级/CI。"""


class BubblewrapSandbox(ExecSandbox):
    """Linux: 基于 bubblewrap 的文件系统/网络隔离。"""

    def available(self) -> bool:
        return sys.platform.startswith("linux") and shutil.which("bwrap") is not None

    def backend_name(self) -> str:
        return "bubblewrap"

    def enforced(self) -> bool:
        return True

    def wrap_argv(self, command: str) -> List[str]:
        # bwrap 注入隔离前缀；command 作为 sh -c 的单个 argv（无转义层）
        parts = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
        if self.severity in (SandboxSeverity.NETWORK_OFF, SandboxSeverity.FULL):
            parts.append("--unshare-net")
        parts.extend(["--", "sh", "-c", command])
        return parts


class SeatbeltSandbox(ExecSandbox):
    """macOS: 基于 sandbox-exec 的 Seatbelt 配置。"""

    def available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("sandbox-exec") is not None

    def backend_name(self) -> str:
        return "seatbelt"

    def enforced(self) -> bool:
        return True

    def wrap_argv(self, command: str) -> List[str]:
        profile = (
            "(version 1)"
            "(deny default)"
            "(allow file-read*)"
            "(allow process-exec)"
            "(allow sysctl-read)"
        )
        if self.severity in (SandboxSeverity.NETWORK_OFF, SandboxSeverity.FULL):
            profile += "(deny network*)"
        # profile / command 均作为单个 argv 传递
        return ["sandbox-exec", "-p", profile, "sh", "-c", command]


class AppContainerSandbox(ExecSandbox):
    """Windows: AppContainer 受限执行。

    P1-7 诚实化：真实现（COM 派生受限 token / packaged app 语义）尚未落地，
    available() 必须返回 False——原占位在 win32 返回 True 但执行走普通 shell，
    让治理层误以为隔离生效（安全谎言）。真实现推后。
    """

    def available(self) -> bool:
        return False

    def backend_name(self) -> str:
        return "appcontainer"


def _detect_backend(severity: SandboxSeverity) -> ExecSandbox:
    """按平台与可用工具选择最佳隔离后端；始终能降级到 ProcessSandbox。"""
    if severity == SandboxSeverity.NONE:
        return ProcessSandbox(severity)
    if platform.system() == "Linux" and BubblewrapSandbox().available():
        return BubblewrapSandbox(severity)
    if platform.system() == "Darwin" and SeatbeltSandbox().available():
        return SeatbeltSandbox(severity)
    # P1-7：AppContainer 未实现（available=False），Windows 诚实降级
    return ProcessSandbox(severity)


_EXEC_SANDBOX_CACHE: Dict[SandboxSeverity, ExecSandbox] = {}


def get_exec_sandbox(severity: SandboxSeverity = SandboxSeverity.NONE) -> ExecSandbox:
    """获取（带缓存的）隔离沙箱实例。"""
    if severity not in _EXEC_SANDBOX_CACHE:
        _EXEC_SANDBOX_CACHE[severity] = _detect_backend(severity)
    return _EXEC_SANDBOX_CACHE[severity]


def reset_exec_sandbox() -> None:
    """清空缓存（测试用）。"""
    _EXEC_SANDBOX_CACHE.clear()


def execute_in_sandbox(
    command: str,
    timeout: float = 30.0,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    severity: SandboxSeverity = SandboxSeverity.NONE,
) -> Dict[str, Any]:
    """便捷入口：按 severity 选择沙箱并执行命令（同步，平台后端）。"""
    return get_exec_sandbox(severity).execute(command, timeout=timeout, cwd=cwd, env=env)


def docker_available() -> bool:
    """探测 Docker 是否可用（结果缓存，避免反复探测 docker info）"""
    global _DOCKER_AVAILABLE_CACHE
    if _DOCKER_AVAILABLE_CACHE is not None:
        return _DOCKER_AVAILABLE_CACHE
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        _DOCKER_AVAILABLE_CACHE = probe.returncode == 0
    except Exception:  # noqa: BLE001 - docker 未安装/守护进程未启动
        _DOCKER_AVAILABLE_CACHE = False
    return _DOCKER_AVAILABLE_CACHE


_DOCKER_AVAILABLE_CACHE: Optional[bool] = None


async def execute_in_sandbox_async(
    command: str,
    timeout: float = 30.0,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    severity: SandboxSeverity = SandboxSeverity.NONE,
    backend: str = "auto",
) -> Dict[str, Any]:
    """异步便捷入口：治理 SANDBOX 判定的执行通道。

    backend 语义：
    - "docker"：强制容器执行（Docker 不可用时返回明确错误，不静默降级）
    - "auto"（默认）：需要隔离（severity != NONE）且 Docker 可用 → 容器执行
      （跨平台真隔离，补齐 Windows AppContainer 占位）；否则回退平台后端
    - 其他值：按平台后端执行（原 execute_in_sandbox 行为）
    """
    use_docker = backend == "docker" or (
        backend == "auto" and severity != SandboxSeverity.NONE and docker_available()
    )
    if not use_docker:
        result = execute_in_sandbox(command, timeout=timeout, cwd=cwd, env=env, severity=severity)
        # 统一返回形状：平台后端历史 key 为 return_code/output/error，规范为容器后端同形
        result.setdefault("returncode", result.get("return_code"))
        result["stdout"] = result.get("stdout", result.get("output", ""))
        result["stderr"] = result.get("stderr", result.get("error", ""))
        result["backend"] = get_exec_sandbox(severity).backend_name()
        return result

    if not docker_available():
        return {
            "success": False,
            "error": "Docker 后端不可用（docker info 探测失败），无法提供容器隔离",
            "backend": "docker",
        }

    from neurova.execution_layers import DockerExecutor

    executor = DockerExecutor(runtime_id=f"sandbox_{int(time.time())}")
    started = await executor.start()
    if not started:
        return {"success": False, "error": "Docker 容器启动失败", "backend": "docker"}
    try:
        exec_result = await executor.exec(
            "sh", args=["-c", command], env=env, cwd=cwd, timeout=timeout
        )
        return {
            "success": getattr(exec_result, "exit_code", 1) == 0,
            "returncode": getattr(exec_result, "exit_code", 1),
            "stdout": getattr(exec_result, "stdout", "") or "",
            "stderr": getattr(exec_result, "stderr", "") or "",
            "backend": "docker",
        }
    finally:
        await executor.stop()


__all__ = [
    "SandboxSeverity",
    "ExecSandbox",
    "ProcessSandbox",
    "BubblewrapSandbox",
    "SeatbeltSandbox",
    "AppContainerSandbox",
    "get_exec_sandbox",
    "reset_exec_sandbox",
    "execute_in_sandbox",
    "execute_in_sandbox_async",
    "docker_available",
]
