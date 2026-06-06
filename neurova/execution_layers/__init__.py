"""
Execution Runtime + Transport Abstraction v1.0.0

运行时+传输层双抽象 — 隔离: 全局

架构:
  执行环境 (Runtime)          传输层 (Transport)
  - LocalExecutor          - HTTPTransport
  - DockerExecutor        - WebSocketTransport
  - CloudFunctionExecutor  - gRPCTransport
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import os
import subprocess
import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class RuntimeType(Enum):
    """运行时类型"""
    LOCAL = "local"
    DOCKER = "docker"
    CLOUD_FUNCTION = "cloud_function"
    REMOTE = "remote"


class TransportType(Enum):
    """传输类型"""
    HTTP = "http"
    WEBSOCKET = "websocket"
    GRPC = "grpc"
    STDIO = "stdio"


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
        pass

    @abstractmethod
    async def stop(self) -> bool:
        """停止运行时"""
        pass

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
        pass

    @abstractmethod
    def get_info(self) -> RuntimeInfo:
        """获取运行时信息"""
        pass


class ExecutionTransport(ABC):
    """执行传输抽象基类"""
    
    def __init__(self, transport_type: TransportType, config: Optional[Dict[str, Any]] = None):
        self._transport_type = transport_type
        self._config = config or {}
        self._connected = False
        logger.debug("Transport %s initialized", transport_type.value)

    @property
    def transport_type(self) -> TransportType:
        return self._transport_type

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """断开连接"""
        pass

    @abstractmethod
    async def send(self, data: Any) -> Any:
        """发送数据"""
        pass

    @abstractmethod
    async def receive(self) -> Any:
        """接收数据"""
        pass


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
        """执行本地命令"""
        start_time = time.time()
        
        try:
            cmd = [command] + (args or [])
            merged_env = {**os.environ, **(env or {})}
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
                cwd=cwd,
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


class HTTPTransport(ExecutionTransport):
    """HTTP 传输层"""
    
    def __init__(self, base_url: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(TransportType.HTTP, config)
        self._base_url = base_url.rstrip("/")

    async def connect(self) -> bool:
        """建立 HTTP 连接"""
        self._connected = True
        logger.info("HTTP transport connected to %s", self._base_url)
        return True

    async def disconnect(self) -> bool:
        """断开 HTTP 连接"""
        self._connected = False
        logger.info("HTTP transport disconnected")
        return True

    async def send(self, data: Any) -> Any:
        """发送 HTTP 请求"""
        if not self._connected:
            raise RuntimeError("Not connected")
        
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/execute",
                    json=data,
                    timeout=self._config.get("timeout", 30),
                )
                return response.json()
                
        except ImportError:
            logger.warning("httpx not available, using fallback")
            return {"error": "httpx not installed"}
        except Exception as e:
            logger.error("HTTP send failed: %s", str(e))
            return {"error": str(e)}

    async def receive(self) -> Any:
        """HTTP 无状态，返回 None"""
        return None


class WebSocketTransport(ExecutionTransport):
    """WebSocket 传输层"""
    
    def __init__(self, ws_url: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(TransportType.WEBSOCKET, config)
        self._ws_url = ws_url
        self._ws = None

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            import websockets
            self._ws = await websockets.connect(self._ws_url)
            self._connected = True
            logger.info("WebSocket transport connected to %s", self._ws_url)
            return True
        except ImportError:
            logger.warning("websockets not available")
            return False
        except Exception as e:
            logger.error("WebSocket connect failed: %s", str(e))
            return False

    async def disconnect(self) -> bool:
        """断开 WebSocket 连接"""
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._connected = False
        logger.info("WebSocket transport disconnected")
        return True

    async def send(self, data: Any) -> Any:
        """发送 WebSocket 消息"""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        import json
        await self._ws.send(json.dumps(data))
        
        # 等待响应
        response = await self._ws.recv()
        return json.loads(response)

    async def receive(self) -> Any:
        """接收 WebSocket 消息"""
        if not self._ws:
            raise RuntimeError("Not connected")
        
        import json
        message = await self._ws.recv()
        return json.loads(message)


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


class TransportFactory:
    """传输层工厂"""
    
    @staticmethod
    def create(transport_type: TransportType, endpoint: str, **kwargs) -> ExecutionTransport:
        """创建传输层实例"""
        if transport_type == TransportType.HTTP:
            return HTTPTransport(base_url=endpoint, **kwargs)
        elif transport_type == TransportType.WEBSOCKET:
            return WebSocketTransport(ws_url=endpoint, **kwargs)
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

    @staticmethod
    def list_supported_types() -> List[TransportType]:
        """列出支持的传输类型"""
        return [TransportType.HTTP, TransportType.WEBSOCKET]


async def execute_skill(
    skill_name: str,
    args: Dict[str, Any],
    runtime: Optional[ExecutionRuntime] = None,
    transport: Optional[ExecutionTransport] = None,
) -> ExecutionResult:
    """
    统一技能执行接口（运行时+传输层双抽象）
    
    Args:
        skill_name: 技能名称
        args: 技能参数
        runtime: 执行运行时（可选，默认本地）
        transport: 传输层（可选）
        
    Returns:
        ExecutionResult 执行结果
    """
    start_time = time.time()
    
    try:
        # 使用默认本地运行时
        if runtime is None:
            runtime = LocalExecutor()
            await runtime.start()
        
        # 构建执行命令
        command = "python"
        script_args = ["-m", f"neurova.skills.{skill_name}"]
        
        # 将参数转为环境变量
        import json
        env = {
            "NEUROVA_SKILL_NAME": skill_name,
            "NEUROVA_SKILL_ARGS": json.dumps(args),
        }
        
        # 执行
        result = await runtime.exec(
            command=command,
            args=script_args,
            env=env,
            timeout=args.get("timeout", 60),
        )
        
        duration_ms = (time.time() - start_time) * 1000
        result.duration_ms = duration_ms
        
        return result
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        return ExecutionResult(
            success=False,
            error=str(e),
            duration_ms=duration_ms,
        )


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
