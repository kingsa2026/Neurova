
"""
Pytest 配置和共享 fixtures

提供测试中可复用的模拟对象和通用工具。
"""
import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def mock_logger():
    """模拟日志记录器"""
    class MockLogger:
        def __init__(self):
            self.info_messages = []
            self.error_messages = []
            self.debug_messages = []
            self.warning_messages = []

        def info(self, msg):
            self.info_messages.append(msg)

        def error(self, msg):
            self.error_messages.append(msg)

        def debug(self, msg):
            self.debug_messages.append(msg)

        def warning(self, msg):
            self.warning_messages.append(msg)

    return MockLogger()


@pytest.fixture
def mock_event_bus():
    """模拟事件总线"""
    class MockEventBus:
        def __init__(self):
            self.events = []
            self.subscribers = {}

        def subscribe(self, event_type, callback):
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(callback)

        def emit(self, event_type, data=None):
            self.events.append((event_type, data))
            if event_type in self.subscribers:
                for callback in self.subscribers[event_type]:
                    callback(data)

    return MockEventBus()


@pytest.fixture
def temp_config(tmp_path):
    """临时配置目录"""
    return tmp_path / "config"


@pytest.fixture
def temp_workspace(tmp_path):
    """临时 Agent 工作目录

    用于 AgentConfig(workspace_path=...) 和 Agent(workspace_path=...) 测试。
    agent_core.py:215-220 强制要求 workspace_path 非空, 否则抛 ValueError。
    依赖此 fixture 的测试: test_agent.py 等。
    """
    workspace = tmp_path / "agent_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def temp_db_path(tmp_path):
    """临时 SQLite DB 路径

    用于 Agent(db_path=...) 记忆模块测试。返回字符串形式路径。
    依赖此 fixture 的测试: test_agent.py 等。
    """
    db_dir = tmp_path / "memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "memory.db")


# ============================================================
# 语音引擎共享 fixtures
# ============================================================

@pytest.fixture
def mock_tts_manager():
    """模拟 TTSManager（向后兼容旧端点）"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.get_engine_name.return_value = "mock-tts"
    manager.stats = {"initialized": True, "engine": "mock-tts"}
    manager.synthesize = AsyncMock(return_value=b"mock audio bytes")
    manager.synthesize_stream = AsyncMock()
    manager.shutdown = AsyncMock()
    return manager


@pytest.fixture
def mock_asr_manager():
    """模拟 ASRManager（向后兼容旧端点）"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.get_engine_name.return_value = "mock-asr"
    manager.stats = {"initialized": True, "engine": "mock-asr"}
    manager.transcribe = AsyncMock(return_value={"text": "模拟识别结果", "language": "zh"})
    manager.understand = AsyncMock(return_value={"answer": "模拟理解结果"})
    manager.caption = AsyncMock(return_value={"caption": "模拟描述"})
    manager.shutdown = AsyncMock()
    return manager


@pytest.fixture
def mock_tts_voice_engine():
    """模拟 TTS VoiceEngine（新统一接口）"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.TTS
    engine.is_available.return_value = True
    engine.get_info.return_value = {
        "engine_type": "tts",
        "is_initialized": True,
        "engine_class": "MockTTS",
    }
    engine.process = AsyncMock(return_value=VoiceResult(
        audio_data=b"mock audio bytes",
        metadata={"operation": "synthesize", "engine": "mock-tts"},
    ))
    return engine


@pytest.fixture
def mock_asr_voice_engine():
    """模拟 ASR VoiceEngine（新统一接口）"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.ASR
    engine.is_available.return_value = True
    engine.get_info.return_value = {
        "engine_type": "asr",
        "is_initialized": True,
        "engine_class": "MockASR",
    }
    engine.process = AsyncMock(return_value=VoiceResult(
        text="识别结果",
        confidence=0.95,
        metadata={"operation": "transcribe", "engine": "mock-asr"},
    ))
    return engine


@pytest.fixture
def mock_failing_voice_engine():
    """模拟会失败的 VoiceEngine"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.TTS
    engine.is_available.return_value = True
    engine.process = AsyncMock(return_value=VoiceResult(error="引擎故障"))
    return engine


@pytest.fixture
def mock_agent():
    """模拟 Agent 实例（用于 pipeline/agent 相关测试）"""
    agent = MagicMock()
    agent._turn_count = 0
    agent._collect_tool_messages.return_value = []
    agent._save_to_session = MagicMock()
    agent.conversation_buffer = MagicMock()
    agent.memory_manager = MagicMock()
    agent.memory_manager.remember = AsyncMock()
    agent.memory_agent = MagicMock()
    agent.post_chat_pipeline = MagicMock()
    agent.post_chat_pipeline.execute = AsyncMock(return_value=None)
    return agent


# ============================================================
# AutoVoiceEngine 共享 fixtures
# ============================================================

@pytest.fixture
def available_engine():
    """可用的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.synthesize = AsyncMock(return_value=b"audio data")
    engine.transcribe = AsyncMock(return_value={"text": "识别结果"})
    return engine


@pytest.fixture
def failing_engine():
    """会失败的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.synthesize = AsyncMock(return_value=b"")
    engine.transcribe = AsyncMock(return_value={"text": "", "error": "引擎故障"})
    return engine


@pytest.fixture
def unavailable_engine():
    """不可用的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = False
    return engine


@pytest.fixture
def mock_auto_tts_engine(available_engine):
    """模拟自动 TTS 引擎（AutoVoiceEngine）"""
    from neurova.voice_engine import AutoVoiceEngine, VoiceEngineType
    return AutoVoiceEngine(
        engine_type=VoiceEngineType.TTS,
        engines=[available_engine],
    )


@pytest.fixture
def mock_auto_asr_engine(available_engine):
    """模拟自动 ASR 引擎（AutoVoiceEngine）"""
    from neurova.voice_engine import AutoVoiceEngine, VoiceEngineType
    return AutoVoiceEngine(
        engine_type=VoiceEngineType.ASR,
        engines=[available_engine],
    )



# ---------------------------------------------------------------------------
# 仓库文件防污染隔离
# ---------------------------------------------------------------------------
# 历史事故（2026-09，dee84dc）: settings API 的 CORS PUT 会写模块级常量
# _CORS_CONFIG_FILE（直指仓库 config/cors.json），测试期写入的
# evil.example.com 被误提交入库，随安装包分发后桌面端注册/登录全挂。
# 统一重定向：测试会话期间 CORS 配置只落临时目录，永不碰仓库真实文件。

@pytest.fixture(autouse=True)
def _isolate_cors_config_file(tmp_path, monkeypatch):
    """所有测试的 CORS 配置读写都指向临时目录。"""
    try:
        from neurova.api.endpoints import settings as _settings
    except Exception:  # pragma: no cover - settings 依赖缺失时跳过
        return
    monkeypatch.setattr(_settings, "_CORS_CONFIG_FILE", tmp_path / "cors.json")


# ---------------------------------------------------------------------------
# Token 用量历史库防污染隔离
# ---------------------------------------------------------------------------
# usage_history（神经va/core/usage_history.py）默认落 data/usage_history.db；
# multi_model_client 入账路径会写入它，测试期直接落盘会污染仓库 data/。
# 统一指向每测试临时目录（含单例重建），与 _isolate_cors_config_file 同模式。

@pytest.fixture(autouse=True)
def _isolate_usage_history(tmp_path, monkeypatch):
    """所有测试的 usage_history 落盘指向临时目录。"""
    monkeypatch.setenv("NEUROVA_USAGE_HISTORY_DB", str(tmp_path / "usage_history.db"))
    try:
        from neurova.core.usage_history import reset_usage_history
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_usage_history()


# ---------------------------------------------------------------------------
# 元认知台账防污染隔离
# ---------------------------------------------------------------------------
# MetaLedger（neurova/cognitive_layers/meta_cognition_layer/ledger.py）默认落
# data/metacognition.db；B/C 写穿透与 API 测试都会写它，测试期直接落盘会污染
# 仓库 data/。统一指向每测试临时目录（含单例重建），与 _isolate_usage_history 同模式。

@pytest.fixture(autouse=True)
def _isolate_governance_settings(tmp_path, monkeypatch):
    """所有测试的治理设置（governance_settings.json）指向临时目录。

    data/governance_settings.json 是运行时管理面（RSI 部署阶段/对话规则提取
    门控），读写真实文件会（a）污染仓库 data/（b）让测试读到彼此的开关值。
    与 _isolate_usage_history 同模式。
    """
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "governance_settings.json"))


@pytest.fixture(autouse=True)
def _isolate_meta_ledger(tmp_path, monkeypatch):
    """所有测试的元认知台账落盘指向临时目录。

    （合并残留：本文件内曾定义两次，后者静默遮蔽前者——2026-09-06 收敛为一份。）
    MetaLedger（neurova/cognitive_layers/meta_cognition_layer/ledger.py）默认落
    data/metacognition.db；B/C 写穿透与 API 测试都会写它，测试期直接落盘会污染
    仓库 data/。统一指向每测试临时目录（含单例重建），与 _isolate_usage_history 同模式。
    """
    monkeypatch.setenv("NEUROVA_META_LEDGER_DB", str(tmp_path / "metacognition.db"))
    try:
        from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_meta_ledger()


@pytest.fixture(autouse=True)
def _isolate_ekb(tmp_path, monkeypatch):
    """所有测试的经验知识库（EKB）落盘指向临时目录。

    根因（3920 条垃圾经验事故 2026-09-06）：管线级测试用 MagicMock
    evolution（hasattr 恒真）→ _step_record_experience 的 EKB 写入分支必执行，
    模块单例默认打生产库 data/experience_knowledge.db，测试对话
    （"Hello" ×1223 等）全部灌进真库。与 _isolate_meta_ledger 同模式：
    环境变量指向 tmp_path + 单例重建。
    """
    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "experience_knowledge.db"))
    try:
        from neurova.skills.experience_knowledge_base import (
            reset_experience_knowledge_base,
        )
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_experience_knowledge_base()
    yield
    reset_experience_knowledge_base()
