"""
内核级执行沙箱。

提供跨平台进程隔离能力：
- Linux: bubblewrap (bwrap) 文件系统/网络隔离
- macOS: Seatbelt (sandbox-exec)
- Windows: AppContainer（受限执行，降级为常规执行并标注）
- 通用降级: ProcessSandbox（无内核隔离，仅进程级）

所有后端对外暴露统一的 `execute()` 接口，返回调用方约定的字典形态。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.proc_text import decodeChild

logger = get_logger(__name__)


def killProcessTree(proc: subprocess.Popen) -> None:
    """按平台杀灭整棵进程树（**全仓唯一**的进程组杀灭实现）。

    - POSIX: 进程组 SIGKILL（调用方须以 `start_new_session=True` 起进程，
      否则 `getpgid` 返回的是宿主进程组，杀它会连带杀掉宿主自身）；
      进程已退出时 `getpgid` 抛 `ProcessLookupError`，退回直接 kill。
    - Windows: `taskkill /T /F`（`TerminateProcess` 只杀单个进程，
      `taskkill /T` 遍历子树）；taskkill 缺失/失败时退回 `proc.kill()`。

    公开成模块级函数，是因为它不再只服务沙箱内部：工具超时/用户取消路径也要
    经它收尸（`core/cancel_token.CancelToken.onCancel` 注册的就是本函数）。
    此前它是 `ExecSandbox` 的私有方法，沙箱外的调用方只能各自再写一份——
    第二份杀灭实现正是本函数要挡掉的形态。
    """
    if sys.platform == "win32":
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            try:
                subprocess.run(
                    [taskkill, "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
                return
            except Exception:  # noqa: BLE001 - taskkill 失败退回单杀
                pass
        proc.kill()
        return
    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def spawnKwargsForKill() -> Dict[str, Any]:
    """起进程时该带的 kwargs：让子进程自成一团，供后续整组杀灭。

    **这不是可选优化**：POSIX 下不带它，`os.getpgid(child)` 返回的是**宿主**进程组，
    按组杀灭会连带杀掉宿主自身（本仓实测：未成团时子进程 pgid == 本进程 pgid）。
    故"要杀进程树的调用方"与"起进程的调用方"必须共用这一处取值——
    各自手写 `{"start_new_session": True}` 就是给同一约束两份定义。

    Windows 无需成团（`taskkill /T` 按父子关系遍历），返回空 dict。
    """
    if sys.platform == "win32":
        return {}
    return {"start_new_session": True}


#: 进程杀灭后的**收尸窗口**（秒）。杀灭是异步生效的：`SIGKILL` 发出后进程
#: 还需要一点时间被回收，立刻读 `returncode` 会拿到 `None`（僵尸未收）。
#: 数值沿用既有沙箱路径的 `communicate(timeout=5)`——不新造第二个尺度。
KILL_GRACE_S = 5.0


class SandboxSeverity(str, Enum):
    """隔离强度等级"""

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
            proc = subprocess.Popen(
                argv,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                **self._spawn_kwargs(),
            )
        except Exception as e:  # noqa: BLE001 - 沙箱执行需捕获一切异常以保证可用
            return {
                **base,
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
            }
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return {
                **base,
                "success": proc.returncode == 0,
                "output": decodeChild(stdout),
                "error": decodeChild(stderr),
                "return_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            # C-22: 超时后必须杀整棵进程树（原 subprocess.run 只杀直接子进程，
            # sh/cmd 的孙进程残留继续占资源）
            self._kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:  # noqa: BLE001 - 收尸失败不改变超时结果契约
                stdout, stderr = "", ""
            return {
                **base,
                "success": False,
                "output": decodeChild(stdout),
                "error": f"Command timed out after {timeout} seconds",
                "return_code": -1,
            }
        except Exception as e:  # noqa: BLE001 - 沙箱执行需捕获一切异常以保证可用
            self._kill_process_tree(proc)
            return {
                **base,
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
            }

    def _spawn_kwargs(self) -> Dict[str, Any]:
        """C-22: POSIX 下让子进程成为新进程组首进程，供超时后整组杀灭（单源转发）。"""
        return spawnKwargsForKill()

    def _kill_process_tree(self, proc: subprocess.Popen) -> None:
        """实例方法形态：转调模块级单源 `killProcessTree`（薄转发，不含逻辑）。"""
        killProcessTree(proc)


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


def _detect_backend(severity: SandboxSeverity) -> ExecSandbox:
    """按平台与可用工具选择最佳隔离后端；始终能降级到 ProcessSandbox。"""
    if severity == SandboxSeverity.NONE:
        return ProcessSandbox(severity)
    if platform.system() == "Linux" and BubblewrapSandbox().available():
        return BubblewrapSandbox(severity)
    if platform.system() == "Darwin" and SeatbeltSandbox().available():
        return SeatbeltSandbox(severity)
    # 遗留③：AppContainer 真实现落地（Low integrity + 默认断网）——
    # Windows 优先 AppContainer，受限令牌（SAFER）兜底，裸 process 最后
    if platform.system() == "Windows":
        from neurova.sandbox.appcontainer import AppContainerSandbox

        ac = AppContainerSandbox(severity)
        if ac.available():
            return ac
        from neurova.sandbox.restricted_token import RestrictedTokenSandbox

        rt = RestrictedTokenSandbox(severity)
        if rt.available():
            return rt
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


# operation not permitted /
# permission denied / read-only file system / seccomp / sandbox / landlock /
# failed to write file，另补 Windows "access is denied"
_SANDBOX_DENIAL_KEYWORDS = (
    "operation not permitted",
    "permission denied",
    "access is denied",
    "read-only file system",
    "seccomp",
    "sandbox",
    "landlock",
    "failed to write file",
)
# shell 自身错误退出码：找不到命令/用法错等与沙箱无关
_SHELL_OWN_ERROR_CODES = frozenset({2, 126, 127})
_SIGSYS_EXIT_CODE = 128 + 31  # Linux seccomp SIGSYS 终止 → 128+31


def attribution_sandbox_denial(result: Any) -> Optional[Dict[str, Any]]:
    """归因一次沙箱内执行失败：是沙箱拦截还是命令本身错误。

    判据（保守启发式）：
    - returncode 缺失或 0 → 非失败，不归因
    - returncode == 159（128+SIGSYS）→ 直接判定（seccomp 杀进程，无需关键词）
    - returncode ∈ {2,126,127} → shell 自身错误，排除
    - stdout+stderr 命中沙箱关键词 → 归因命中
    - 其余 → 命令本身错误，不归因

    Returns:
        {"kind": "filesystem", "reason": <关键词>, "snippet": <输出末尾 512 字符>}
        或 None。
    """
    if not isinstance(result, dict):
        return None
    returncode = result.get("returncode")
    if not isinstance(returncode, int) or returncode == 0:
        return None
    combined = " ".join(
        str(result.get(k) or "") for k in ("stdout", "stderr")
    ).strip()
    snippet = combined[-512:]
    if returncode == _SIGSYS_EXIT_CODE:
        return {"kind": "filesystem", "reason": "sigsys", "snippet": snippet}
    if returncode in _SHELL_OWN_ERROR_CODES:
        return None
    low = combined.lower()
    for kw in _SANDBOX_DENIAL_KEYWORDS:
        if kw in low:
            return {"kind": "filesystem", "reason": kw, "snippet": snippet}
    return None


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
    "KILL_GRACE_S",
    "killProcessTree",
    "spawnKwargsForKill",
    "SandboxSeverity",
    "ExecSandbox",
    "ProcessSandbox",
    "BubblewrapSandbox",
    "SeatbeltSandbox",
    "get_exec_sandbox",
    "reset_exec_sandbox",
    "execute_in_sandbox",
    "execute_in_sandbox_async",
    "docker_available",
]
