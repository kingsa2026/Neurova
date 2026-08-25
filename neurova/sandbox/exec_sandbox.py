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
from enum import Enum
from typing import Any, Dict, Optional

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

    def wrap(self, command: str) -> str:
        """返回包装后的命令；子类重写以注入隔离前缀。"""
        return command

    def execute(
        self,
        command: str,
        timeout: float = 30.0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        wrapped = self.wrap(command)
        try:
            result = subprocess.run(
                wrapped,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout or "",
                "error": result.stderr or "",
                "return_code": result.returncode,
                "sandbox": self.backend_name(),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout} seconds",
                "return_code": -1,
                "sandbox": self.backend_name(),
            }
        except Exception as e:  # noqa: BLE001 - 沙箱执行需捕获一切异常以保证可用
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
                "sandbox": self.backend_name(),
            }


class ProcessSandbox(ExecSandbox):
    """默认沙箱：仅进程级执行（无内核隔离），用于降级/CI。"""


class BubblewrapSandbox(ExecSandbox):
    """Linux: 基于 bubblewrap 的文件系统/网络隔离。"""

    def available(self) -> bool:
        return sys.platform.startswith("linux") and shutil.which("bwrap") is not None

    def backend_name(self) -> str:
        return "bubblewrap"

    def wrap(self, command: str) -> str:
        base = "bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp"
        if self.severity in (SandboxSeverity.NETWORK_OFF, SandboxSeverity.FULL):
            base += " --unshare-net"
        return f'{base} -- sh -c "{_escape(command)}"'


class SeatbeltSandbox(ExecSandbox):
    """macOS: 基于 sandbox-exec 的 Seatbelt 配置。"""

    def available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("sandbox-exec") is not None

    def backend_name(self) -> str:
        return "seatbelt"

    def wrap(self, command: str) -> str:
        profile = (
            "(version 1)"
            "(deny default)"
            "(allow file-read*)"
            "(allow process-exec)"
            "(allow sysctl-read)"
        )
        if self.severity in (SandboxSeverity.NETWORK_OFF, SandboxSeverity.FULL):
            profile += "(deny network*)"
        return f"sandbox-exec -p '{profile}' sh -c \"{_escape(command)}\""


class AppContainerSandbox(ExecSandbox):
    """Windows: AppContainer 受限执行（暂降级为常规执行并标注）。"""

    def available(self) -> bool:
        return sys.platform == "win32"

    def backend_name(self) -> str:
        return "appcontainer"


def _escape(s: str) -> str:
    """转义双引号，避免注入沙箱命令。"""
    return s.replace('"', '\\"')


def _detect_backend(severity: SandboxSeverity) -> ExecSandbox:
    """按平台与可用工具选择最佳隔离后端；始终能降级到 ProcessSandbox。"""
    if severity == SandboxSeverity.NONE:
        return ProcessSandbox(severity)
    if platform.system() == "Linux" and BubblewrapSandbox().available():
        return BubblewrapSandbox(severity)
    if platform.system() == "Darwin" and SeatbeltSandbox().available():
        return SeatbeltSandbox(severity)
    if platform.system() == "Windows":
        return AppContainerSandbox(severity)
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
    """便捷入口：按 severity 选择沙箱并执行命令。"""
    return get_exec_sandbox(severity).execute(command, timeout=timeout, cwd=cwd, env=env)


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
]
