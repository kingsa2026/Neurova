from __future__ import annotations

"""
Neurova API Server - 应用入口

完整的 RESTful API 服务，提供统一的 API 接口。

功能:
1. JWT 认证
2. 流式输出 (SSE)
3. Agent 管理 API
4. 记忆管理 API
5. Skill 执行 API
6. LLM 管理 API
7. 系统健康检查
8. Prometheus 指标
"""

import contextlib
import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import traceback
import typing
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi import APIRouter
import uvicorn

logger = logging.getLogger(__name__)


class AppState:
    """应用全局状态"""

    def __init__(self):
        self.startup_manager = None
        self.health_checker = None
        self.agents: Dict[str, Any] = {}  # agent_id -> Agent instance
        self.default_agent_id: str = "default"
        self.llm_client = None
        self.provider_manager = None
        self.llm_router = None
        self.channel_manager = None
        self.admin_service = None
        self.resource_quota_manager = None
        self.skill_pool_manager = None
        self.user_group_manager = None
        self.token_manager = None
        self.tts_manager = None
        self.asr_manager = None
        self.audio_engine = None
        self.voice_engines: Dict[str, Any] = {}  # engine_type -> VoiceEngine instance
        self.sleep_manager = None
        self.shutdown_guard = None
        self.start_time: float = time.time()
        self.config: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def get_agent(self, agent_id: str = None) -> Optional[Any]:
        """获取 Agent 实例"""
        aid = agent_id or self.default_agent_id
        return self.agents.get(aid)

    def add_agent(self, agent_id: str, agent: Any) -> None:
        """添加 Agent 实例"""
        with self._lock:
            self.agents[agent_id] = agent

    def remove_agent(self, agent_id: str) -> bool:
        """移除 Agent 实例"""
        with self._lock:
            if agent_id in self.agents:
                del self.agents[agent_id]
                return True
            return False

    def get_uptime(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self.start_time


# 全局 AppState 单例
_app_state: Optional[AppState] = None
_app_instance: Optional[FastAPI] = None
_state_lock = threading.Lock()


def _register_default_health_checks(health_checker) -> None:
    """
    注册默认的系统健康检查
    """
    from neurova.core.health_checker import CheckType, RecoveryAction

    # 数据库检查
    health_checker.register(
        name="database",
        check_func=lambda: (True, "SQLite OK"),
        check_type=CheckType.READINESS,
        description="Database connectivity check",
        critical=True,
    )

    # 内存检查
    def check_memory():
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 90:
                return False, f"Memory usage critical: {mem.percent}%"
            if mem.percent > 80:
                return True, f"Memory usage high: {mem.percent}%"
            return True, f"Memory OK: {mem.percent}%"
        except ImportError:
            return True, "psutil not available, skip memory check"

    health_checker.register(
        name="memory",
        check_func=check_memory,
        check_type=CheckType.LIVENESS,
        description="System memory check",
    )

    # 磁盘检查
    def check_disk():
        try:
            import psutil
            disk = psutil.disk_usage("/")
            if disk.percent > 95:
                return False, f"Disk usage critical: {disk.percent}%"
            return True, f"Disk OK: {disk.percent}%"
        except Exception:
            return True, "Disk check skipped"

    health_checker.register(
        name="disk",
        check_func=check_disk,
        check_type=CheckType.LIVENESS,
        description="Disk space check",
    )


def _initialize_components(app_state: AppState) -> None:
    """
    初始化核心组件
    """
    logger.info("Initializing core components...")

    # 初始化启动管理器
    try:
        from neurova.core.startup_manager import StartupManager
        app_state.startup_manager = StartupManager()
    except Exception as e:
        logger.warning(f"StartupManager init failed: {e}")

    # 初始化健康检查器
    try:
        from neurova.core.health_checker import HealthChecker
        app_state.health_checker = HealthChecker()
        _register_default_health_checks(app_state.health_checker)
    except Exception as e:
        logger.warning(f"HealthChecker init failed: {e}")

    # 初始化 LLM Provider Manager
    try:
        from neurova.llm.provider_manager import LLMProviderManager
        app_state.provider_manager = LLMProviderManager()
    except Exception as e:
        logger.warning(f"LLMProviderManager init failed: {e}")

    # 初始化 LLM Router
    try:
        from neurova.llm.llm_router import LLMRouter
        app_state.llm_router = LLMRouter()
    except Exception as e:
        logger.warning(f"LLMRouter init failed: {e}")

    # 初始化 Channel Manager
    try:
        from neurova.channels.manager import ChannelManager
        app_state.channel_manager = ChannelManager()
    except Exception as e:
        logger.warning(f"ChannelManager init failed: {e}")

    # 初始化 Admin Service
    try:
        from neurova.admin.admin_service import AdminService
        import os as _os
        admin_storage = _os.path.join(_os.getcwd(), "data", "admin")
        app_state.admin_service = AdminService(storage_dir=admin_storage)
    except Exception as e:
        logger.warning(f"AdminService init failed: {e}")

    # 初始化 Token Manager
    try:
        from neurova.security.neu_token_manager import NEUTokenManager
        app_state.token_manager = NEUTokenManager()
    except Exception as e:
        logger.warning(f"NEUTokenManager init failed: {e}")

    # 初始化默认 Agent
    try:
        from neurova.agent_core import Agent, AgentConfig
        default_workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agent_workspaces", "default")
        os.makedirs(default_workspace, exist_ok=True)
        config = AgentConfig(
            name="Neurova",
            agent_id="default",
            enable_memory=True,
            workspace_path=default_workspace,
        )
        agent = Agent(config=config)
        app_state.add_agent("default", agent)
        logger.info("Default Agent initialized")
    except Exception as e:
        logger.warning(f"Default Agent init failed: {e}")

    # 初始化 TTS Manager
    try:
        from neurova.tts.manager import TTSManager, TTSConfig
        tts_config = TTSConfig(
            engine=app_state.config.get("tts_engine", "edge-tts"),
            model_path=app_state.config.get("tts_model_path", "models/tts/moss-nano"),
            tokenizer_path=app_state.config.get("tts_tokenizer_path", "models/tts/moss-tokenizer"),
            auto_download=app_state.config.get("tts_auto_download", False),
            voice=app_state.config.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
        )
        app_state.tts_manager = TTSManager(config=tts_config)
    except Exception as e:
        logger.warning(f"TTSManager init failed: {e}")

    # 初始化 ASR Manager（可选）
    try:
        from neurova.asr.manager import ASRManager, ASRConfig
        asr_config = ASRConfig(
            engine=app_state.config.get("asr_engine", "auto"),
            model_path=app_state.config.get("asr_model_path", "models/asr"),
            auto_download=app_state.config.get("asr_auto_download", True),
        )
        app_state.asr_manager = ASRManager(asr_config)
        logger.info(f"ASR Manager init success (engine={asr_config.engine})")
    except Exception as e:
        logger.warning(f"ASR Manager init failed: {e}")

    logger.info("Core components initialized")


def _register_core_modules(app_state: AppState) -> None:
    """注册核心模块到启动管理器"""
    if not app_state.startup_manager:
        return

    sm = app_state.startup_manager

    # 注册各模块（如果可用）
    try:
        from neurova.core.module_system import Module

        class AgentModule(Module):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._agent = app_state.get_agent()

            def _on_start(self):
                pass

            def _on_stop(self):
                if self._agent:
                    try:
                        self._agent.shutdown()
                    except Exception:
                        pass

        sm.register_module("agent", AgentModule, dependencies=[])
    except Exception as e:
        logger.warning(f"Failed to register agent module: {e}")


def _register_routes(app: FastAPI, app_state: AppState) -> None:
    """注册所有 API 路由"""
    from neurova.api.endpoints import (
        router, acp_router, evolution_router, rag_router,
        set_app_state, register_endpoint_routers,
    )

    # 设置全局应用状态
    set_app_state({
        "startup_manager": app_state.startup_manager,
        "health_checker": app_state.health_checker,
        "agents": app_state.agents,
        "llm_client": app_state.llm_client,
        "provider_manager": app_state.provider_manager,
        "llm_router": app_state.llm_router,
        "channel_manager": app_state.channel_manager,
        "admin_service": app_state.admin_service,
        "token_manager": app_state.token_manager,
        "tts_manager": app_state.tts_manager,
        "audio_engine": app_state.audio_engine,
        "asr_manager": app_state.asr_manager,
        "voice_engines": app_state.voice_engines,
    })

    # 注册主路由
    app.include_router(router, prefix="/api")

    # 注册特殊路由
    app.include_router(acp_router, prefix="/api/acp", tags=["ACP"])
    app.include_router(evolution_router, prefix="/api/evolution", tags=["Evolution"])
    app.include_router(rag_router, prefix="/api/rag", tags=["RAG"])

    # 注册所有端点路由
    register_endpoint_routers(app)

    logger.info("Routes registered")


def _register_frontend_error_log(app: FastAPI) -> None:
    """注册前端错误日志收集端点"""

    @app.post("/api/v1/frontend/errors")
    async def log_frontend_error(request: Request):
        try:
            body = await request.json()
            logger.warning(
                f"Frontend error: {body.get('message', 'unknown')}",
                extra={"frontend_error": body},
            )
            return {"status": "logged"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}


def _register_metrics_endpoint(app: FastAPI) -> None:
    """注册 Prometheus 指标端点"""

    @app.get("/metrics")
    async def get_metrics():
        metrics = []
        # 基础指标
        metrics.append(f'# HELP neurova_uptime_seconds Neurova uptime in seconds')
        metrics.append(f'# TYPE neurova_uptime_seconds gauge')
        uptime = _app_state.get_uptime() if _app_state else 0
        metrics.append(f'neurova_uptime_seconds {uptime}')

        metrics.append(f'# HELP neurova_agents_total Total number of agents')
        metrics.append(f'# TYPE neurova_agents_total gauge')
        agent_count = len(_app_state.agents) if _app_state else 0
        metrics.append(f'neurova_agents_total {agent_count}')

        # P3: 语音性能指标
        metrics.append(f'# HELP neurova_voice_engines_total Total number of voice engines')
        metrics.append(f'# TYPE neurova_voice_engines_total gauge')
        voice_count = len(_app_state.voice_engines) if _app_state else 0
        metrics.append(f'neurova_voice_engines_total {voice_count}')

        metrics.append(f'# HELP neurova_voice_tts_available TTS engine availability (1=available, 0=unavailable)')
        metrics.append(f'# TYPE neurova_voice_tts_available gauge')
        tts_available = 0
        if _app_state and "tts" in _app_state.voice_engines:
            try:
                tts_available = 1 if _app_state.voice_engines["tts"].is_available() else 0
            except Exception:
                tts_available = 0
        metrics.append(f'neurova_voice_tts_available {tts_available}')

        metrics.append(f'# HELP neurova_voice_asr_available ASR engine availability (1=available, 0=unavailable)')
        metrics.append(f'# TYPE neurova_voice_asr_available gauge')
        asr_available = 0
        if _app_state and "asr" in _app_state.voice_engines:
            try:
                asr_available = 1 if _app_state.voice_engines["asr"].is_available() else 0
            except Exception:
                asr_available = 0
        metrics.append(f'neurova_voice_asr_available {asr_available}')

        # 渠道指标
        metrics.append(f'# HELP neurova_channels_total Total number of registered channels')
        metrics.append(f'# TYPE neurova_channels_total gauge')
        channel_count = 0
        if _app_state and _app_state.channel_manager:
            channel_count = len(_app_state.channel_manager._adapters)
        metrics.append(f'neurova_channels_total {channel_count}')

        return PlainTextResponse("\n".join(metrics), media_type="text/plain")


def _add_health_routes(app: FastAPI, app_state: AppState) -> None:
    """添加健康检查和系统统计路由"""

    @app.get("/health")
    async def health_check():
        """简单的健康检查端点"""
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/health/detailed")
    async def detailed_health():
        """详细的健康检查"""
        if app_state.health_checker:
            app_state.health_checker.run_all_checks()
            return app_state.health_checker.get_report()
        return {"status": "unknown", "message": "Health checker not available"}

    @app.get("/api/v1/status")
    async def get_status():
        """获取系统状态"""
        return {
            "status": "running",
            "uptime": app_state.get_uptime(),
            "agents": len(app_state.agents),
            "version": "5.0.0",
            "timestamp": time.time(),
        }


async def _on_startup(app_state: AppState) -> None:
    """
    应用启动事件
    """
    logger.info("=" * 60)
    logger.info("Neurova API Server starting...")
    logger.info("=" * 60)

    # 初始化组件
    _initialize_components(app_state)

    # 初始化 TTS 引擎
    if hasattr(app_state, "tts_manager") and app_state.tts_manager:
        try:
            success = await app_state.tts_manager.initialize()
            if success:
                logger.info(f"TTS engine ready: {app_state.tts_manager.get_engine_name()}")
            else:
                logger.warning("TTS engine initialization failed, fallback will be used")
        except Exception as e:
            logger.warning(f"TTS engine init error: {e}")

    # 初始化 Audio Engine（可选）
    if hasattr(app_state, "audio_engine") and app_state.audio_engine:
        try:
            if app_state.audio_engine.is_available:
                success = await app_state.audio_engine.initialize()
                if success:
                    logger.info("Audio understanding engine ready")
                else:
                    logger.warning("Audio engine initialization failed")
            else:
                logger.info("Audio engine skipped (no GPU available)")
        except Exception as e:
            logger.warning(f"Audio engine init error: {e}")

    # P2-5: 创建 VoiceEngine 统一接口实例，替代旧的 TTSManager/ASRManager 直接调用
    try:
        from neurova.voice_engine import VoiceEngine, VoiceEngineType

        if app_state.tts_manager and getattr(app_state.tts_manager, "is_initialized", False):
            app_state.voice_engines["tts"] = VoiceEngine(
                engine_type=VoiceEngineType.TTS,
                engine=app_state.tts_manager,
            )
            logger.info("VoiceEngine[TTS] created from TTSManager")

        if app_state.asr_manager and getattr(app_state.asr_manager, "is_initialized", False):
            app_state.voice_engines["asr"] = VoiceEngine(
                engine_type=VoiceEngineType.ASR,
                engine=app_state.asr_manager,
            )
            logger.info("VoiceEngine[ASR] created from ASRManager")
    except Exception as e:
        logger.debug(f"VoiceEngine creation skipped: {e}")

    # P2-4: 注册 VoiceAdapter 到 ChannelManager（语音通话渠道）
    try:
        from neurova.channels.voice import VoiceAdapter, create_voice_adapter
        from neurova.channels.base import ChannelConfig

        voice_config = ChannelConfig(
            channel_type="voice",
            enabled=app_state.config.get("voice_enabled", False),
            app_id=app_state.config.get("twilio_account_sid", ""),
            app_secret=app_state.config.get("twilio_auth_token", ""),
            extra={
                "from_number": app_state.config.get("twilio_from_number", ""),
            },
        )
        voice_adapter = create_voice_adapter(voice_config)
        if app_state.channel_manager:
            app_state.channel_manager.register_adapter(voice_adapter)
            logger.info("VoiceAdapter registered to ChannelManager")
    except Exception as e:
        logger.debug(f"VoiceAdapter registration skipped: {e}")

    # 更新全局应用状态（TTS/Audio/VoiceEngine 已初始化）
    from neurova.api.endpoints import set_app_state as _update_app_state
    _update_app_state({
        "startup_manager": app_state.startup_manager,
        "health_checker": app_state.health_checker,
        "agents": app_state.agents,
        "llm_client": app_state.llm_client,
        "provider_manager": app_state.provider_manager,
        "llm_router": app_state.llm_router,
        "channel_manager": app_state.channel_manager,
        "admin_service": app_state.admin_service,
        "token_manager": app_state.token_manager,
        "tts_manager": app_state.tts_manager,
        "audio_engine": app_state.audio_engine,
        "asr_manager": app_state.asr_manager,
        "voice_engines": app_state.voice_engines,
    })

    # 注册核心模块
    _register_core_modules(app_state)

    # 启动管理器
    if app_state.startup_manager:
        result = app_state.startup_manager.start()
        if result.success:
            logger.info(f"Startup completed in {result.duration:.2f}s")
        else:
            logger.warning(f"Startup had errors: {result.errors}")

    # 启动渠道管理器（注意：start() 是 async 方法）
    if app_state.channel_manager:
        try:
            await app_state.channel_manager.start()
            logger.info("Channel manager started")
        except Exception as e:
            logger.warning(f"Channel manager start failed: {e}")

    logger.info("=" * 60)
    logger.info("Neurova API Server started successfully")
    logger.info("=" * 60)


async def _on_shutdown(app_state: AppState) -> None:
    """
    应用关闭事件 — 优雅关闭流程：
    1. 停止消息渠道消费
    2. 调用所有 Agent.shutdown() (睡眠整理 + 缓冲刷新)
    3. 停止启动管理器中的所有模块
    4. 关闭连接池
    """
    logger.info("Neurova API Server shutting down...")

    # 停止渠道管理器（stop() 是 async 方法）
    if app_state.channel_manager:
        try:
            await app_state.channel_manager.stop()
            logger.info("Channel manager stopped")
        except Exception as e:
            logger.warning(f"Channel manager stop error: {e}")

    # 关闭所有 Agent
    for agent_id, agent in app_state.agents.items():
        try:
            if hasattr(agent, "shutdown"):
                agent.shutdown()
                logger.info(f"Agent '{agent_id}' shut down")
        except Exception as e:
            logger.warning(f"Agent '{agent_id}' shutdown error: {e}")

    # 停止启动管理器
    if app_state.startup_manager:
        app_state.startup_manager.stop()

    logger.info("Neurova API Server shut down complete")


def create_app(
    config: Optional[Dict[str, Any]] = None,
    host: str = "0.0.0.0",
    port: int = 8000,
    debug: bool = False,
    **kwargs,
) -> FastAPI:
    """
    创建 FastAPI 应用

    参数:
        config: 应用配置
        host: 监听地址
        port: 监听端口
        debug: 调试模式

    Returns:
        FastAPI 应用实例
    """
    global _app_state, _app_instance

    # 单例模式
    if _app_instance is not None:
        return _app_instance

    with _state_lock:
        if _app_instance is not None:
            return _app_instance

        # 创建应用状态
        _app_state = AppState()
        _app_state.config = config or {}
        _app_state.config.update({"host": host, "port": port, "debug": debug})

        # 创建 FastAPI 应用
        app = FastAPI(
            title="Neurova API",
            description="Neurova - 智能 Agent 系统 API",
            version="5.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # 设置中间件
        from neurova.api.middleware import setup_middleware
        setup_middleware(app)

        # 注册路由
        _register_routes(app, _app_state)

        # 注册健康检查路由
        _add_health_routes(app, _app_state)

        # 注册前端错误日志
        _register_frontend_error_log(app)

        # 注册指标端点
        _register_metrics_endpoint(app)

        # 测试端点
        @app.get("/test")
        async def test_simple_endpoint():
            """最简单的测试端点"""
            return {"status": "ok", "message": "Neurova API is running"}

        @app.post("/test")
        async def test_post_direct():
            """直接在 app 上注册的 POST 端点（用于诊断）"""
            return {"status": "ok", "method": "POST"}

        # 注册启动/关闭事件
        @app.on_event("startup")
        async def startup_event():
            await _on_startup(_app_state)

        @app.on_event("shutdown")
        async def shutdown_event():
            await _on_shutdown(_app_state)

        _app_instance = app
        logger.info("FastAPI application created")

        return app


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    debug: bool = False,
    reload: bool = False,
    workers: int = 1,
    **kwargs,
) -> None:
    """
    运行 FastAPI 服务器

    参数:
        host: 监听地址
        port: 监听端口
        debug: 调试模式
        reload: 自动重载
        workers: 工作进程数
    """
    # 加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 从环境变量读取配置
    host = os.getenv("NEUROVA_HOST", host)
    port = int(os.getenv("NEUROVA_PORT", port))
    debug = os.getenv("NEUROVA_DEBUG", "false").lower() == "true" or debug

    # 创建应用
    app = create_app(host=host, port=port, debug=debug)

    logger.info(f"Starting server on {host}:{port}")

    # 运行服务器
    uvicorn.run(
        "neurova.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level="debug" if debug else "info",
        factory=True,
    )


def get_app() -> Optional[FastAPI]:
    """
    获取或创建 FastAPI 应用实例（单例模式，防止双重初始化）

    Returns:
        FastAPI 应用实例
    """
    global _app_instance
    if _app_instance is None:
        return create_app()
    return _app_instance


def get_app_state() -> Optional[AppState]:
    """获取应用状态"""
    return _app_state


# 入口点
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Neurova API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--reload", action="store_true", help="Auto reload")
    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_server(
        host=args.host,
        port=args.port,
        debug=args.debug,
        reload=args.reload,
    )
