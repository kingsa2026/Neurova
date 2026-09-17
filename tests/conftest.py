
"""
Pytest 配置和共享 fixtures

提供测试中可复用的模拟对象和通用工具。
"""
import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(autouse=True)
def _isolate_session_manager_singletons():
    """跨套件全局状态隔离（残留处理 2026-09-13 大合批泄漏治理）。

    SessionManager 为类级单例 + 类级解析/sidecar 缓存（进程级共享）；
    前序测试把 _instance 指向已删除的 tmp 目录或留下缓存条目时，后续
    会话面测试会在"全量批跑"里看到与单跑不一致的计数/解析断言。
    每测试后重置单例并清类级缓存；get_session_repository 同步复位。"""
    yield
    try:
        from neurova.session_manager import SessionManager
    except Exception:
        return
    SessionManager._instance = None
    for attr in ("_summary_cache", "_feedback_cache", "_sidecar_cache"):
        cache = getattr(SessionManager, attr, None)
        if isinstance(cache, dict):
            cache.clear()
    try:
        from neurova import session_repository as _sr
    except Exception:
        _sr = None
    if _sr is not None and hasattr(_sr, "reset_session_repository"):
        try:
            _sr.reset_session_repository()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _isolate_skill_service_storage(tmp_path, monkeypatch):
    """Keep default skill-library writes out of user data during regressions."""
    import hashlib
    from neurova.skills.skill_service import SkillService
    original = SkillService.__init__

    def isolated(self, agent_id, skills_dir=None):
        directory = tmp_path / "agent-skills" / hashlib.sha256(str(agent_id).encode()).hexdigest()
        return original(self, agent_id, skills_dir if skills_dir is not None else str(directory))

    monkeypatch.setattr(SkillService, "__init__", isolated)


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
def _isolate_evolution_job_queue(tmp_path, monkeypatch):
    """所有测试的进化作业队列落盘指向临时目录（含单例重建）。

    EvolutionJobQueue（neurova/evolution/job_queue.py）默认落
    data/evolution/jobs.db；进化队列开关默认开（2026-09-15 SettingPage 收口）
    后，post_chat 每轮都会 enqueue/drain——不隔离即污染仓库 data/ 并让
    测试互相看到作业。
    """
    monkeypatch.setenv("NEUROVA_EVOLUTION_JOBS_DB", str(tmp_path / "evolution_jobs.db"))
    try:
        from neurova.evolution.job_queue import reset_evolution_job_queue

        reset_evolution_job_queue()
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        pass


@pytest.fixture(autouse=True)
def _disable_skill_semantic_in_tests(monkeypatch):
    """语义档测试全局关：召回热路径的懒解析永不加载 ONNX 模型/不触下载器。

    专属测试（wave E/F）用显式注入的 fake engine 绕过 env（SkillVectorCache
    对显式 engine 不吃开关，见 _get_engine 注释）；生产默认行为不受影响。
    """
    monkeypatch.setenv("NEUROVA_SKILL_SEMANTIC", "0")


@pytest.fixture(autouse=True)
def _isolate_turn_context():
    """每测试清回合上下文（Wave H 测试卫生）。

    生产安全前提：asyncio 每请求 task 的 context 拷贝隔离，
    set_turn_skill_view 等不跨请求泄漏；但 pytest 同线程直调 chat_pipeline
    全链测试会把 view/funnel 残留到后续测试（task_name_params 等被视图门
    误拒的批跑失败根因，2026-09-15）。
    """
    try:
        from neurova.core import turn_context

        turn_context.clear_turn_state()
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        pass
    yield
    try:
        from neurova.core import turn_context

        turn_context.clear_turn_state()
    except Exception:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _isolate_neurflow_storage(tmp_path, monkeypatch):
    """NeurflowStorage 默认路径隔离。

    NeurflowStorage(db_path="neurflow.db") 是 cwd 相对路径 → 测试从仓库根
    运行时读到开发者的真实 neurflow.db：其中"已发布"工作流经 workflow_as_tool
    （P1-3）注入 LLM 工具面，使所有经 _build_tools_for_llm 的测试随本机数据
    漂移（同 EKB 单例打真库事故根因）。默认构造重定向到每测试临时库；
    显式传 db_path 的专属测试不受影响。同时清 neurflow_api._get_storage 的
    函数属性缓存，防上一测试的临时库句柄泄漏到下一测试。
    """
    try:
        import neurova.collaboration.neurflow.storage as _nstor
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    real_cls = _nstor.NeurflowStorage
    tmp_db = str(tmp_path / "neurflow.db")

    class _IsolatedStorage(real_cls):
        def __init__(self, db_path: str = "neurflow.db"):
            super().__init__(tmp_db if db_path == "neurflow.db" else db_path)

    monkeypatch.setattr(_nstor, "NeurflowStorage", _IsolatedStorage)
    try:
        import neurova.api.endpoints.neurflow_api as _napi

        if hasattr(_napi._get_storage, "_instance"):
            del _napi._get_storage._instance
        # neurflow_api 模块顶层若已绑定旧类引用，一并替换
        monkeypatch.setattr(_napi, "NeurflowStorage", _IsolatedStorage, raising=False)
    except Exception:  # pragma: no cover
        pass


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


@pytest.fixture(autouse=True)
def _reset_memory_request_scope():
    """每个测试后归还未设置态：MemoryManager 的请求作用域是模块级 ContextVar。

    根因（2026-09-12 甄别）：set_request_scope 的"随请求上下文销毁"仅对
    异步任务成立——pytest 单线程同步执行下 ContextVar 值跨测试存活，
    任一测试 set_request_scope 后不归还，后续测试的记忆写入/读取全部落在
    被污染的作用域上（曾致 test_moe_router_reads_persist_db 顺序依赖失败：
    remember 写进 user_id='7' 的作用域，MoE 适配器按 n1/u1 过滤读空）。
    """
    yield
    try:
        from neurova.cognitive_layers.memory_layer.manager import (
            clear_memory_request_scope,
        )
    except Exception:  # pragma: cover - 模块未就绪时跳过
        return
    clear_memory_request_scope()
