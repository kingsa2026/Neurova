"""
内置工具层扩充 — 常规 Agent 工具（TDD）

背景：对比主流 agent harness 的常规工具基座后，发现本系统内置工具偏科
（重桌面/浏览器/语音/多智能体，缺通用文件检索与网络抓取能力）：

  新增工具          对标
  ────────────────────────────────────────────────
  file_list        Claude Code Glob / OpenHands glob（文件枚举）
  file_search      Claude Code Grep / OpenHands search（内容搜索）
  web_fetch        Claude Code WebFetch（网页正文抓取）
  run_code         DeepSeek harness code_interpreter
                   （执行体早已存在，但缺 schema → LLM 永远看不到）
  calculator       Hermes function calling 标配（LLM 算术不可靠）
  get_datetime     时间戳/时区换算（system prompt 只注入当前时间）

根因修复（schema ↔ 执行体漂移）：
  历史漂移实证：
    - asr_transcribe / tts_synthesize 有 schema 但 _execute_builtin_tool
      无分派分支 → LLM 调用必然返回"未知内置工具"；
    - run_code / execute_code 有执行体但无 schema → LLM 永远看不到。
  根因：schema 字典（builtin_tools.py）与 if/elif 分派链（tool_executor.py）
  是两条平行结构，没有任何机械关联，靠人肉同步必然漂移。
  修复：_execute_builtin_tool 改为类级分派表（工具名 → 方法名，调用时
  getattr 解析），并以不变量测试保证 _BUILTIN_SCHEMAS ⊆ 分派表。
"""

import base64
import math
import os

import pytest
from unittest.mock import AsyncMock, Mock, patch


def _make_executor():
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.memory_manager = Mock()
    agent.memory_manager._emotion_analyzer = Mock()
    # 默认语音管理器未启用；需要的用例自行替换为 Mock
    agent.asr_manager = None
    agent.tts_manager = None

    return ToolExecutor(agent)


def _urlopen_returning(body_bytes):
    """构造模拟 urllib.request.urlopen 返回值的 context manager"""
    resp = Mock()
    resp.read = Mock(return_value=body_bytes)

    cm = Mock()
    cm.__enter__ = Mock(return_value=resp)
    cm.__exit__ = Mock(return_value=False)
    return cm


# ═══════════════════════════════════════════════════════════════
# 1. Schema 注册（LLM 可见性）
# ═══════════════════════════════════════════════════════════════

# 工具名 → 必填参数
NEW_TOOLS = {
    "file_list": ["pattern"],
    "file_search": ["pattern", "path"],
    "web_fetch": ["url"],
    "run_code": ["code"],
    "calculator": ["expression"],
    "get_datetime": [],
}


class TestSchemaRegistration:
    @pytest.mark.parametrize("tool_name", sorted(NEW_TOOLS))
    def test_schema_registered_with_valid_shape(self, tool_name):
        """每个新工具必须在 _BUILTIN_SCHEMAS 注册且为合法 JSON Schema"""
        from neurova.builtin_tools import get_builtin_tool_params

        schema = get_builtin_tool_params(tool_name)
        assert schema is not None, f"{tool_name} 未注册 schema — LLM 永远看不到该工具"
        assert schema.get("description"), f"{tool_name} 缺少 description（LLM 靠它决定是否调用）"
        params = schema["parameters"]
        assert params["type"] == "object"
        assert isinstance(params.get("properties"), dict)
        assert set(params.get("required", [])) == set(NEW_TOOLS[tool_name])

    def test_registry_and_openai_format_visibility(self):
        """注册表自动装载后，新工具必须出现在 OpenAI function calling 工具列表里"""
        from neurova.builtin_tools import BuiltinToolRegistry

        registry = BuiltinToolRegistry()
        openai_tools = registry.get_openai_tools()
        names = {t["function"]["name"] for t in openai_tools}
        missing = set(NEW_TOOLS) - names
        assert not missing, f"工具列表缺少: {missing}"


# ═══════════════════════════════════════════════════════════════
# 2. 不变量：schema ↔ 分派表一致性（漂移的根因修复）
# ═══════════════════════════════════════════════════════════════


class TestSchemaDispatchConsistency:
    def test_every_schema_has_dispatch(self):
        """_BUILTIN_SCHEMAS 中每个工具必须在分派表中有执行体。

        违反此不变量 = 重现 asr_transcribe/tts_synthesize 的历史 bug：
        LLM 看得见工具、调用却返回"未知内置工具"。
        """
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.tool_executor import ToolExecutor

        dispatch = ToolExecutor._builtin_dispatch
        missing = sorted(set(_BUILTIN_SCHEMAS) - set(dispatch))
        assert not missing, f"这些工具有 schema 但无执行体，调用必失败: {missing}"

    def test_dispatch_targets_are_real_methods(self):
        """分派表值必须是 ToolExecutor 上真实存在的 async 方法名"""
        from neurova.tool_executor import ToolExecutor

        for tool_name, method_name in ToolExecutor._builtin_dispatch.items():
            method = getattr(ToolExecutor, method_name, None)
            assert method is not None, f"{tool_name} → {method_name} 方法不存在"
            assert callable(method)

    @pytest.mark.parametrize("tool_name", ["asr_transcribe", "tts_synthesize", "run_code"])
    def test_historically_drifted_tools_dispatchable(self, tool_name):
        """历史漂移过的三个工具必须可分派"""
        from neurova.tool_executor import ToolExecutor

        assert tool_name in ToolExecutor._builtin_dispatch


class TestDispatchBehavior:
    @pytest.mark.asyncio
    async def test_unknown_tool_error_semantics_unchanged(self):
        """未知工具的错误语义必须与原 if/elif 实现完全一致（tool_router 依赖）"""
        result = await _make_executor()._execute_builtin_tool("no_such_tool_xyz", {})
        assert result == {"error": "未知内置工具: no_such_tool_xyz"}

    @pytest.mark.asyncio
    async def test_execute_code_alias_still_works(self):
        """execute_code 是 run_code 的历史别名，重构后必须保留"""
        exe = _make_executor()
        with patch.object(
            exe, "_execute_run_code", new_callable=AsyncMock, return_value={"success": True}
        ) as mocked:
            await exe._execute_builtin_tool("execute_code", {"code": "print(1)"})
        mocked.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_alias_still_works(self):
        """search 是 web_search 的历史别名，重构后必须保留"""
        exe = _make_executor()
        with patch.object(
            exe, "_execute_web_search", new_callable=AsyncMock, return_value={"results": "r"}
        ) as mocked:
            await exe._execute_builtin_tool("search", {"query": "x"})
        mocked.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_resolves_at_call_time(self):
        """分派必须在调用时解析方法（getattr），保证单测可 patch 单个执行体"""
        exe = _make_executor()
        with patch.object(
            exe, "_execute_file_read", new_callable=AsyncMock, return_value={"content": "patched"}
        ):
            result = await exe._execute_builtin_tool("file_read", {"file_path": "x"})
        assert result == {"content": "patched"}


# ═══════════════════════════════════════════════════════════════
# 3. file_list — 文件枚举（对标 Glob）
# ═══════════════════════════════════════════════════════════════


class TestFileListTool:
    @pytest.fixture
    def tree(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("hello\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("y = 2\n", encoding="utf-8")
        return tmp_path

    @pytest.mark.asyncio
    async def test_glob_recursive_by_default(self, tree):
        result = await _make_executor()._execute_file_list({"pattern": "*.py", "path": str(tree)})
        assert "error" not in result
        files = result["files"]
        assert any(f.endswith("a.py") for f in files)
        assert any(f.endswith("c.py") for f in files), "默认应递归子目录"
        assert not any(f.endswith("b.txt") for f in files)
        assert result["count"] == len(files)

    @pytest.mark.asyncio
    async def test_non_recursive(self, tree):
        result = await _make_executor()._execute_file_list(
            {"pattern": "*.py", "path": str(tree), "recursive": False}
        )
        files = result["files"]
        assert any(f.endswith("a.py") for f in files)
        assert not any("sub" in f for f in files), "recursive=False 不应进入子目录"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, tree):
        result = await _make_executor()._execute_file_list({"pattern": "*.rs", "path": str(tree)})
        assert "error" not in result
        assert result["files"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_missing_pattern_error(self):
        result = await _make_executor()._execute_file_list({"path": "."})
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 4. file_search — 内容搜索（对标 Grep）
# ═══════════════════════════════════════════════════════════════


class TestFileSearchTool:
    @pytest.fixture
    def tree(self, tmp_path):
        (tmp_path / "main.py").write_text(
            "import os\n\ndef find_neurova():\n    return 'neurova'\n", encoding="utf-8"
        )
        (tmp_path / "notes.txt").write_text("nothing here\nneurova rocks\n", encoding="utf-8")
        noise = tmp_path / "node_modules"
        noise.mkdir()
        (noise / "junk.js").write_text("neurova\n", encoding="utf-8")
        return tmp_path

    @pytest.mark.asyncio
    async def test_search_directory(self, tree):
        result = await _make_executor()._execute_file_search(
            {"pattern": "neurova", "path": str(tree)}
        )
        assert "error" not in result
        matches = result["matches"]
        files = {m["file"] for m in matches}
        assert any("main.py" in f for f in files)
        assert any("notes.txt" in f for f in files)
        assert all("node_modules" not in m["file"] for m in matches), "应跳过 node_modules 等噪音目录"

    @pytest.mark.asyncio
    async def test_match_has_line_number_and_text(self, tree):
        result = await _make_executor()._execute_file_search(
            {"pattern": "neurova", "path": str(tree / "notes.txt")}
        )
        assert result["count"] == 1
        m = result["matches"][0]
        assert m["line"] == 2
        assert "neurova" in m["text"]

    @pytest.mark.asyncio
    async def test_regex_support(self, tree):
        result = await _make_executor()._execute_file_search(
            {"pattern": r"def \w+\(", "path": str(tree)}
        )
        assert any("main.py" in m["file"] for m in result["matches"])

    @pytest.mark.asyncio
    async def test_invalid_regex_falls_back_to_literal(self, tree):
        """非法正则应降级为字面量匹配，而不是报错"""
        result = await _make_executor()._execute_file_search(
            {"pattern": "a(b", "path": str(tree)}
        )
        assert "error" not in result
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_include_filter(self, tree):
        result = await _make_executor()._execute_file_search(
            {"pattern": "neurova", "path": str(tree), "include": "*.py"}
        )
        files = {m["file"] for m in result["matches"]}
        assert files, "include=*.py 应仍匹配到 main.py"
        assert all(f.endswith(".py") for f in files)

    @pytest.mark.asyncio
    async def test_max_results_cap(self, tree):
        result = await _make_executor()._execute_file_search(
            {"pattern": "neurova", "path": str(tree), "max_results": 1}
        )
        assert len(result["matches"]) == 1
        assert result.get("truncated") is True

    @pytest.mark.asyncio
    async def test_missing_params(self):
        exe = _make_executor()
        assert "error" in await exe._execute_file_search({"path": "."})
        assert "error" in await exe._execute_file_search({"pattern": "x"})

    @pytest.mark.asyncio
    async def test_nonexistent_path_error(self):
        result = await _make_executor()._execute_file_search(
            {"pattern": "x", "path": "no/such/path/anywhere"}
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 5. web_fetch — 网页抓取（对标 WebFetch）
# ═══════════════════════════════════════════════════════════════


class TestWebFetchTool:
    @pytest.mark.asyncio
    async def test_fetch_strips_html_to_text(self):
        html = (
            "<html><head><script>var x=1;</script><style>.a{}</style></head>"
            "<body><h1>Neurova</h1><p>Agent framework.</p></body></html>"
        )
        with patch(
            "urllib.request.urlopen", return_value=_urlopen_returning(html.encode("utf-8"))
        ):
            result = await _make_executor()._execute_web_fetch({"url": "https://example.com"})
        assert "error" not in result
        content = result["content"]
        assert "Neurova" in content and "Agent framework." in content
        assert "<" not in content, "正文应为纯文本"
        assert "var x" not in content, "script 必须剥离"
        assert ".a{}" not in content, "style 必须剥离"

    @pytest.mark.asyncio
    async def test_max_chars_truncation(self):
        body = "A" * 50000
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(body.encode())):
            result = await _make_executor()._execute_web_fetch(
                {"url": "https://example.com", "max_chars": 1000}
            )
        assert len(result["content"]) <= 1000
        assert result.get("truncated") is True

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self):
        """file:// 等非 http(s) 协议必须拒绝（防本地文件读取/SSRF 扩大面）"""
        with patch("urllib.request.urlopen") as mocked:
            result = await _make_executor()._execute_web_fetch({"url": "file:///C:/secret.txt"})
        mocked.assert_not_called()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_url_error(self):
        result = await _make_executor()._execute_web_fetch({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_dict(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = await _make_executor()._execute_web_fetch({"url": "https://down.example.com"})
        assert "error" in result
        assert result.get("url") == "https://down.example.com"


# ═══════════════════════════════════════════════════════════════
# 6. calculator — 安全数学计算（AST 白名单，禁止 eval）
# ═══════════════════════════════════════════════════════════════


class TestCalculatorTool:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("1 + 2 * 3", 7),
            ("(1 + 2) * 3", 9),
            ("2 ** 10", 1024),
            ("10 / 4", 2.5),
            ("10 // 4", 2),
            ("10 % 3", 1),
            ("-5 + 3", -2),
            ("sqrt(16)", 4.0),
            ("abs(-8)", 8),
            ("max(1, 5, 3)", 5),
            ("min(1, 5, 3)", 1),
            ("round(3.14159, 2)", 3.14),
        ],
    )
    async def test_eval(self, expr, expected):
        result = await _make_executor()._execute_calculator({"expression": expr})
        assert "error" not in result, result
        assert result["result"] == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_constants(self):
        result = await _make_executor()._execute_calculator({"expression": "pi"})
        assert "error" not in result
        assert result["result"] == pytest.approx(math.pi)

    @pytest.mark.asyncio
    async def test_division_by_zero_is_error(self):
        result = await _make_executor()._execute_calculator({"expression": "1 / 0"})
        assert "error" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "evil",
        [
            "__import__('os').system('echo hacked')",
            "().__class__.__bases__",
            "open('x.txt')",
            "eval('1+1')",
            "[x for x in (1,)]",
        ],
    )
    async def test_malicious_input_rejected(self, evil):
        """属性访问/导入/未白名单函数/推导式一律拒绝，绝不执行"""
        result = await _make_executor()._execute_calculator({"expression": evil})
        assert "error" in result, f"恶意表达式必须被拒绝: {evil}"

    @pytest.mark.asyncio
    async def test_huge_exponent_guarded(self):
        """超大指数会撑爆内存，必须拦截"""
        result = await _make_executor()._execute_calculator({"expression": "9 ** 999999999"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_expression_error(self):
        result = await _make_executor()._execute_calculator({})
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 7. get_datetime — 日期时间 / 时区 / 时间戳换算
# ═══════════════════════════════════════════════════════════════


class TestGetDatetimeTool:
    @pytest.mark.asyncio
    async def test_now_default(self):
        result = await _make_executor()._execute_get_datetime({})
        assert "error" not in result
        assert result["datetime"]
        assert result["iso"]
        assert result["weekday"]
        assert isinstance(result["timestamp"], int)

    @pytest.mark.asyncio
    async def test_named_timezone(self):
        result = await _make_executor()._execute_get_datetime({"timezone": "Asia/Shanghai"})
        assert "error" not in result
        assert "+08:00" in result["iso"]

    @pytest.mark.asyncio
    async def test_offset_timezone(self):
        result = await _make_executor()._execute_get_datetime(
            {"timezone": "+08:00", "timestamp": 0}
        )
        assert "error" not in result
        assert result["datetime"].startswith("1970-01-01 08:")

    @pytest.mark.asyncio
    async def test_timestamp_conversion_utc(self):
        result = await _make_executor()._execute_get_datetime({"timestamp": 0, "timezone": "UTC"})
        assert "error" not in result
        assert result["datetime"].startswith("1970-01-01 00:00:00")

    @pytest.mark.asyncio
    async def test_invalid_timezone_error(self):
        result = await _make_executor()._execute_get_datetime({"timezone": "Not/AZone"})
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 8. run_code 可见性修复（执行体早已存在，缺 schema）
# ═══════════════════════════════════════════════════════════════


class TestRunCodeVisibility:
    def test_run_code_schema_registered(self):
        from neurova.builtin_tools import get_builtin_tool_params

        schema = get_builtin_tool_params("run_code")
        assert schema is not None, "run_code 执行体早已存在，缺 schema 导致 LLM 永远看不到"
        props = schema["parameters"]["properties"]
        assert "code" in props
        assert "language" in props

    @pytest.mark.asyncio
    async def test_dispatch_reaches_run_code_executor(self):
        exe = _make_executor()
        with patch.object(
            exe,
            "_execute_run_code",
            new_callable=AsyncMock,
            return_value={"success": True, "stdout": "ok"},
        ) as mocked:
            result = await exe._execute_builtin_tool("run_code", {"code": "print(1)"})
        mocked.assert_awaited_once()
        assert result["success"] is True


# ═══════════════════════════════════════════════════════════════
# 9. asr_transcribe / tts_synthesize 分派修复
# ═══════════════════════════════════════════════════════════════


class TestAsrDispatchFix:
    @pytest.mark.asyncio
    async def test_dispatch_to_manager_with_decoded_bytes(self):
        exe = _make_executor()
        manager = Mock()
        manager.is_initialized = True
        manager.transcribe = AsyncMock(
            return_value={"text": "你好", "language": "zh", "duration_sec": 1.2}
        )
        exe._agent.asr_manager = manager

        audio_b64 = base64.b64encode(b"fake-audio-bytes").decode()
        result = await exe._execute_builtin_tool("asr_transcribe", {"audio_data": audio_b64})

        assert "error" not in result, result
        assert result.get("text") == "你好"
        manager.transcribe.assert_awaited_once()
        args, _kwargs = manager.transcribe.call_args
        assert args[0] == b"fake-audio-bytes", "audio_data 必须 base64 解码为 bytes 再送入引擎"

    @pytest.mark.asyncio
    async def test_auto_initialize_when_needed(self):
        exe = _make_executor()
        manager = Mock()
        manager.is_initialized = False
        manager.initialize = AsyncMock(return_value=True)
        manager.transcribe = AsyncMock(return_value={"text": "ok"})
        exe._agent.asr_manager = manager

        result = await exe._execute_builtin_tool(
            "asr_transcribe", {"audio_data": base64.b64encode(b"x").decode()}
        )
        manager.initialize.assert_awaited_once()
        assert result.get("text") == "ok"

    @pytest.mark.asyncio
    async def test_no_manager_clear_error(self):
        """修复前返回'未知内置工具'；修复后应给出明确的未启用提示"""
        result = await _make_executor()._execute_builtin_tool(
            "asr_transcribe", {"audio_data": "aGk="}
        )
        assert "error" in result
        assert "未知内置工具" not in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_base64_error(self):
        exe = _make_executor()
        manager = Mock()
        manager.is_initialized = True
        manager.transcribe = AsyncMock()
        exe._agent.asr_manager = manager

        result = await exe._execute_builtin_tool("asr_transcribe", {"audio_data": "!!not-b64!!"})
        assert "error" in result
        manager.transcribe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_audio_data_error(self):
        result = await _make_executor()._execute_builtin_tool("asr_transcribe", {})
        assert "error" in result


class TestTtsDispatchFix:
    @pytest.mark.asyncio
    async def test_dispatch_writes_audio_file_returns_meta(self):
        """合成结果写临时文件，只回传路径/元信息（base64 会撑爆 LLM 上下文）"""
        exe = _make_executor()
        manager = Mock()
        manager.is_initialized = True
        wav_bytes = b"RIFF" + b"\x00" * 100
        manager.synthesize = AsyncMock(return_value=wav_bytes)
        exe._agent.tts_manager = manager

        try:
            result = await exe._execute_builtin_tool("tts_synthesize", {"text": "你好"})
            assert "error" not in result, result
            assert result.get("success") is True
            assert result.get("bytes") == len(wav_bytes)
            audio_path = result.get("audio_path")
            assert audio_path and os.path.exists(audio_path)
            assert audio_path.endswith(".wav"), "WAV 头应识别为 .wav"
            manager.synthesize.assert_awaited_once()
        finally:
            if result.get("audio_path") and os.path.exists(result["audio_path"]):
                os.remove(result["audio_path"])

    @pytest.mark.asyncio
    async def test_no_manager_clear_error(self):
        result = await _make_executor()._execute_builtin_tool("tts_synthesize", {"text": "hi"})
        assert "error" in result
        assert "未知内置工具" not in result["error"]

    @pytest.mark.asyncio
    async def test_empty_audio_is_error(self):
        exe = _make_executor()
        manager = Mock()
        manager.is_initialized = True
        manager.synthesize = AsyncMock(return_value=b"")
        exe._agent.tts_manager = manager

        result = await exe._execute_builtin_tool("tts_synthesize", {"text": "hi"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_text_error(self):
        result = await _make_executor()._execute_builtin_tool("tts_synthesize", {})
        assert "error" in result
