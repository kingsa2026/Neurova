"""
Execution Runtime Abstraction v1.0.0

运行时单抽象 — 隔离: 全局

架构:
  执行环境 (Runtime)
  - LocalExecutor
  - DockerExecutor
  - CloudFunctionExecutor

这里**没有传输层**：`TransportType`／`ExecutionTransport`／`HTTPTransport`／`WebSocketTransport`／
`TransportFactory` 连同模块级 `execute_skill()` 一并退役（票④包 4）——生产与测试两侧现读零消费者，
而那个 helper 的签名上挂着 `transport` 参数、函数体从头到尾没用它，属于"契约上承诺了一件不做的事"。
注意别被同名骗了：`execution_engine/mcp_manager.py` 里那个 `TransportType` 是它自己的一份枚举。
"""

from neurova.core.logger import get_logger
import asyncio
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# 本包对外的契约（§6-224）：这 8 个名字是包外真在经包路径取用的那一圈（沙箱、工具执行器、
# 技能系统与判据各取若干）。实现写在本文件里，没有这份声明就没人能说清"这层对外给什么"。
__all__ = [
    "DockerExecutor",
    "ExecutionResult",
    "LocalExecutor",
    "RuntimeFactory",
    "RuntimeManager",
    "RuntimeType",
    "get_runtime_manager",
    "reset_runtime_manager",
]


class RuntimeType(Enum):
    """运行时类型"""

    LOCAL = "local"
    DOCKER = "docker"
    CLOUD_FUNCTION = "cloud_function"
    REMOTE = "remote"




@dataclass
class RuntimeInfo:
    """运行时信息"""

    runtime_id: str
    runtime_type: RuntimeType
    name: str
    status: str = "stopped"
    host: Optional[str] = None
    port: Optional[int] = None
    pid: Optional[int] = None
    started_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def uptime_seconds(self) -> Optional[float]:
        if self.started_at and self.is_running:
            return time.time() - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_id": self.runtime_id,
            "runtime_type": self.runtime_type.value,
            "name": self.name,
            "status": self.status,
            "host": self.host,
            "port": self.port,
            "pid": self.pid,
            "started_at": self.started_at,
            "uptime_seconds": self.uptime_seconds,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:1000] if self.stdout else None,
            "stderr": self.stderr[:1000] if self.stderr else None,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


class ExecutionRuntime(ABC):
    """执行运行时抽象基类"""

    def __init__(self, runtime_id: str, config: Optional[Dict[str, Any]] = None):
        self._runtime_id = runtime_id
        self._config = config or {}
        self._started = False
        logger.debug("Runtime %s initialized", runtime_id)

    @property
    def runtime_id(self) -> str:
        return self._runtime_id

    @property
    def is_started(self) -> bool:
        return self._started

    @abstractmethod
    async def start(self) -> bool:
        """启动运行时"""

    @abstractmethod
    async def stop(self) -> bool:
        """停止运行时"""

    @abstractmethod
    async def exec(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ExecutionResult:
        """执行命令"""

    @abstractmethod
    def get_info(self) -> RuntimeInfo:
        """获取运行时信息"""




class LocalExecutor(ExecutionRuntime):
    """本地执行器"""

    def __init__(self, runtime_id: str = "local", config: Optional[Dict[str, Any]] = None):
        super().__init__(runtime_id, config)
        self._process: Optional[subprocess.Popen] = None

    async def start(self) -> bool:
        """启动本地运行时"""
        self._started = True
        logger.info("Local executor started")
        return True

    async def stop(self) -> bool:
        """停止本地运行时"""
        if self._process:
            self._process.terminate()
            self._process = None
        self._started = False
        logger.info("Local executor stopped")
        return True

    async def exec(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ExecutionResult:
        """执行本地命令。

        两处此前是**结构性**缺陷，都在这里根修：

        1. `communicate` 是阻塞调用，此前直接在 `async def` 里跑——整条事件循环
           被它占住（实测：0.6s 的命令期间，每 50ms 一跳的定时器在这段时间内
           一跳都没出）。下沉线程池后循环保持可用，工具面与心跳不再被单条命令拖住。
        2. `process.kill()` 只杀直接子进程，且外部（超时/用户取消）拿不到句柄。
           改走单源杀灭原语 + 进程自成团（否则按组杀灭会命中宿主进程组）。
        """
        start_time = time.time()

        try:
            # 局部导入：`exec_sandbox` 在自身函数内反向引用本模块（Docker 执行器），
            # 提到模块级会把这条懒加载环变成导入期环。
            from neurova.core.cancel_token import registerKillAction
            from neurova.sandbox.exec_sandbox import (
                KILL_GRACE_S,
                killProcessTree,
                spawnKwargsForKill,
            )

            cmd = [command] + (args or [])
            merged_env = {**os.environ, **(env or {})}

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
                cwd=cwd,
                **spawnKwargsForKill(),
            )
            # 句柄立刻交给取消令牌：用户停止 / 超时都能兑现为进程组杀灭。
            # 刻意**不**写 `self._process`：运行时实例经 RuntimeManager 复用，
            # 并发 exec 会互相覆盖该字段、并在 `finally` 里把对方的句柄抹掉
            # （它此前恒为 None，故这是一处新引入的竞态，不是既有缺陷）。
            registerKillAction(lambda: killProcessTree(process))

            # `communicate` 的第一个位置参是 `input` 而非 `timeout`，故经关键字传
            # （写成 `to_thread(process.communicate, timeout)` 会把秒数当 stdin 内容）。
            def _reap(grace: Optional[float]):
                return process.communicate(timeout=grace)

            try:
                stdout, stderr = await asyncio.to_thread(_reap, timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                killProcessTree(process)
                try:
                    stdout, stderr = await asyncio.to_thread(_reap, KILL_GRACE_S)
                except Exception:  # noqa: BLE001 - 收尸失败不改变超时契约
                    stdout, stderr = b"", b""
                exit_code = -1

            duration_ms = (time.time() - start_time) * 1000

            return ExecutionResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout.decode("utf-8", errors="replace") if stdout else None,
                stderr=stderr.decode("utf-8", errors="replace") if stderr else None,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    def get_info(self) -> RuntimeInfo:
        """获取本地运行时信息"""
        return RuntimeInfo(
            runtime_id=self._runtime_id,
            runtime_type=RuntimeType.LOCAL,
            name="Local Executor",
            status="running" if self._started else "stopped",
            pid=os.getpid() if self._started else None,
        )


class DockerExecutor(ExecutionRuntime):
    """Docker 执行器"""

    def __init__(
        self,
        runtime_id: str = "docker",
        image: str = "python:3.11-slim",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(runtime_id, config)
        self._image = image
        self._container_id: Optional[str] = None

    async def start(self) -> bool:
        """启动 Docker 容器"""
        try:
            # 检查 Docker 是否可用
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.error("Docker not available")
                return False

            self._started = True
            logger.info("Docker executor started with image: %s", self._image)
            return True

        except Exception as e:
            logger.error("Failed to start Docker executor: %s", str(e))
            return False

    async def stop(self) -> bool:
        """停止 Docker 容器"""
        if self._container_id:
            try:
                subprocess.run(
                    ["docker", "stop", self._container_id],
                    capture_output=True,
                    timeout=30,
                )
                self._container_id = None
            except Exception as e:
                logger.error("Failed to stop container: %s", str(e))

        self._started = False
        logger.info("Docker executor stopped")
        return True

    async def exec(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ExecutionResult:
        """在 Docker 容器中执行命令"""
        start_time = time.time()

        try:
            cmd = ["docker", "run", "--rm"]

            # BUG AUDIT C-11: 原先裸 `docker run --rm` 无任何隔离，却被
            # exec_sandbox 当"真隔离"后端使用。补齐最小安全隔离集：
            # 断网 + 只读根 fs + 资源上限 + 非特权用户 + 禁提权。
            cmd.extend(
                [
                    "--network=none",
                    "--read-only",
                    "--memory=512m",
                    "--pids-limit=128",
                    "--user",
                    "nobody",
                    "--security-opt=no-new-privileges",
                    "--cap-drop=ALL",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                ]
            )

            # 添加环境变量
            if env:
                for key, value in env.items():
                    cmd.extend(["-e", f"{key}={value}"])

            # 添加工作目录
            if cwd:
                cmd.extend(["-w", cwd])

            # 镜像和命令
            cmd.append(self._image)
            cmd.append(command)
            if args:
                cmd.extend(args)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout, stderr = process.communicate(timeout=timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                exit_code = -1

            duration_ms = (time.time() - start_time) * 1000

            return ExecutionResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout.decode("utf-8", errors="replace") if stdout else None,
                stderr=stderr.decode("utf-8", errors="replace") if stderr else None,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    def get_info(self) -> RuntimeInfo:
        """获取 Docker 运行时信息"""
        return RuntimeInfo(
            runtime_id=self._runtime_id,
            runtime_type=RuntimeType.DOCKER,
            name=f"Docker ({self._image})",
            status="running" if self._started else "stopped",
            metadata={"image": self._image, "container_id": self._container_id},
        )






class RuntimeFactory:
    """运行时工厂"""

    @staticmethod
    def create(runtime_type: RuntimeType, **kwargs) -> ExecutionRuntime:
        """创建运行时实例"""
        if runtime_type == RuntimeType.LOCAL:
            return LocalExecutor(**kwargs)
        elif runtime_type == RuntimeType.DOCKER:
            return DockerExecutor(**kwargs)
        else:
            raise ValueError(f"Unsupported runtime type: {runtime_type}")

    @staticmethod
    def list_supported_types() -> List[RuntimeType]:
        """列出支持的运行时类型"""
        return [RuntimeType.LOCAL, RuntimeType.DOCKER]






class RuntimeManager:
    """运行时管理器"""

    def __init__(self):
        self._runtimes: Dict[str, ExecutionRuntime] = {}
        self._lock = threading.RLock()
        logger.info("RuntimeManager initialized")

    async def start_runtime(self, runtime_type: RuntimeType, **kwargs) -> str:
        """启动运行时"""
        with self._lock:
            runtime_id = f"{runtime_type.value}_{int(time.time())}"
            runtime = RuntimeFactory.create(runtime_type, runtime_id=runtime_id, **kwargs)

            success = await runtime.start()
            if success:
                self._runtimes[runtime_id] = runtime
                logger.info("Runtime started: %s", runtime_id)
                return runtime_id
            else:
                raise RuntimeError(f"Failed to start runtime: {runtime_type.value}")

    async def stop_runtime(self, runtime_id: str) -> bool:
        """停止运行时"""
        with self._lock:
            runtime = self._runtimes.get(runtime_id)
            if not runtime:
                return False

            success = await runtime.stop()
            if success:
                del self._runtimes[runtime_id]
                logger.info("Runtime stopped: %s", runtime_id)

            return success

    def list_active(self) -> List[Dict[str, Any]]:
        """列出活跃的运行时"""
        with self._lock:
            return [r.get_info().to_dict() for r in self._runtimes.values()]

    def get_runtime(self, runtime_id: str) -> Optional[ExecutionRuntime]:
        """获取运行时实例"""
        with self._lock:
            return self._runtimes.get(runtime_id)


# 全局单例
_manager_instance: Optional[RuntimeManager] = None
_manager_lock = threading.Lock()


def get_runtime_manager() -> RuntimeManager:
    """获取全局 RuntimeManager 实例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = RuntimeManager()
    return _manager_instance


def reset_runtime_manager() -> None:
    """重置全局 RuntimeManager 实例（用于测试）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
