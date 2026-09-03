"""
天气 / 实时信息查询能力缺失 — TDD RED 测试

根因（三层断路）：
  W-1: builtin_tools._BUILTIN_SCHEMAS 缺 weather / web_search schema
       → LLM 看不到这两个工具，自然不会调用
  W-2: orchestrator.get_tools_description 写死"需要实时信息时回复无法获取"
       → 提示层直接禁止 agent 尝试
  W-3: neurova/skill_system/compat.py 缺失
       → orchestrator.build_tools_for_llm 抑 ImportError，fallback 到空参数 schema
  W-4: WebSearchSkill._search_web 是 `return []` stub
       → Skill 路径即使被调用也返回空

用户决策：
  - 修复路径：双路径并行（内置实现 + Skill 系统）
  - 提示词策略：改为正向引导（保留 memory_search 限制，去掉"回复无法获取"）
"""

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NEUROVA_DIR = ROOT / "neurova"


# ═══════════════════════════════════════════════════════════════
# W-1: _BUILTIN_SCHEMAS 缺 weather / web_search
# ═══════════════════════════════════════════════════════════════

class TestW1BuiltinSchemasMissingWeather:
    """W-1: 内置工具 schema 单一事实源缺失 weather / web_search"""

    def test_builtin_schemas_contains_weather(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "weather" in _BUILTIN_SCHEMAS, (
            "_BUILTIN_SCHEMAS 必须包含 weather 工具，否则 LLM 永远看不到天气能力"
        )

    def test_weather_schema_has_location_param(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        if "weather" not in _BUILTIN_SCHEMAS:
            pytest.skip("weather schema 尚未添加（W-1 RED）")
        schema = _BUILTIN_SCHEMAS["weather"]
        props = schema.get("parameters", {}).get("properties", {})
        # tool_executor._execute_weather 读取 location / city / query 任一
        assert "location" in props or "city" in props or "query" in props, (
            "weather schema 必须提供 location 类参数，与 _execute_weather 的参数读取对齐"
        )

    def test_builtin_schemas_contains_web_search(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "web_search" in _BUILTIN_SCHEMAS, (
            "_BUILTIN_SCHEMAS 必须包含 web_search 工具，否则 LLM 永远看不到网络搜索能力"
        )

    def test_web_search_schema_has_query_param(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        if "web_search" not in _BUILTIN_SCHEMAS:
            pytest.skip("web_search schema 尚未添加（W-1 RED）")
        schema = _BUILTIN_SCHEMAS["web_search"]
        props = schema.get("parameters", {}).get("properties", {})
        # tool_executor._execute_web_search 读取 query / q / keywords
        assert "query" in props or "q" in props or "keywords" in props, (
            "web_search schema 必须提供 query 类参数，与 _execute_web_search 的参数读取对齐"
        )


# ═══════════════════════════════════════════════════════════════
# W-2: orchestrator 提示词禁止查实时信息
# ═══════════════════════════════════════════════════════════════

class TestW2OrchestratorForbidsRealtime:
    """W-2: get_tools_description 硬编码"回复告知用户你无法获取"断路指令"""

    def test_no_forbid_realtime_phrase(self):
        from neurova.context.orchestrator import ContextOrchestrator

        src = inspect.getsource(ContextOrchestrator.get_tools_description)
        # 原文："需要实时信息（天气、新闻、股价等）时，请直接回复告知用户你无法获取"
        forbidden_markers = [
            "回复告知用户你无法获取",
            "请直接回复告知用户你无法获取",
            "不要尝试用记忆搜索工具",
        ]
        for marker in forbidden_markers:
            assert marker not in src, (
                f"get_tools_description 不应包含断路指令: {marker!r}"
            )

    def test_positive_guidance_for_realtime_tools(self):
        from neurova.context.orchestrator import ContextOrchestrator

        src = inspect.getsource(ContextOrchestrator.get_tools_description)
        # 应包含正向引导：使用 weather / web_search 工具
        assert "weather" in src or "web_search" in src, (
            "get_tools_description 应正向引导使用 weather / web_search 工具获取实时信息"
        )

    def test_keeps_memory_search_limit(self):
        """保留对 memory_search 的限制（用户决策：只去掉禁止查实时信息，保留 memory 限制）"""
        from neurova.context.orchestrator import ContextOrchestrator

        src = inspect.getsource(ContextOrchestrator.get_tools_description)
        assert "memory_search" in src, (
            "应保留对 memory_search 的说明（仅限内部记忆）"
        )


# ═══════════════════════════════════════════════════════════════
# W-3: skill_system/compat.py 缺失
# ═══════════════════════════════════════════════════════════════

class TestW3SkillSystemCompatMissing:
    """W-3: neurova/skill_system/compat.py 不存在，导致 build_tools_for_llm 抑 ImportError"""

    def test_compat_module_file_exists(self):
        compat_path = NEUROVA_DIR / "skill_system" / "compat.py"
        assert compat_path.exists(), (
            f"必须创建 {compat_path}，orchestrator.build_tools_for_llm line 625 依赖此模块"
        )

    def test_compat_module_importable(self):
        try:
            from neurova.skill_system.compat import OpenAISchemaAdapter  # noqa: F401
        except ImportError as e:
            pytest.fail(f"neurova.skill_system.compat.OpenAISchemaAdapter 必须可导入: {e}")

    def test_openai_schema_adapter_has_skill_to_tool_schema(self):
        try:
            from neurova.skill_system.compat import OpenAISchemaAdapter
        except ImportError:
            pytest.skip("compat.py 尚未创建（W-3 RED）")
        assert hasattr(OpenAISchemaAdapter, "skill_to_tool_schema"), (
            "OpenAISchemaAdapter 必须提供 skill_to_tool_schema 静态方法，"
            "orchestrator line 627 调用此方法生成带参数的 schema"
        )

    def test_skill_to_tool_schema_returns_valid_format(self):
        try:
            from neurova.skill_system.compat import OpenAISchemaAdapter
        except ImportError:
            pytest.skip("compat.py 尚未创建（W-3 RED）")

        class _FakeSkill:
            name = "fake_skill"
            description = "测试 skill"

            def _get_parameters(self):
                return {"q": {"type": "string", "required": True, "description": "查询词"}}

        schema = OpenAISchemaAdapter.skill_to_tool_schema(_FakeSkill())
        assert isinstance(schema, dict), "schema 必须是 dict"
        assert schema.get("type") == "function", "schema.type 必须是 'function'"
        fn = schema.get("function", {})
        assert fn.get("name") == "fake_skill", "function.name 必须来自 skill.name"
        assert "parameters" in fn, "必须含 parameters 字段"
        props = fn["parameters"].get("properties", {})
        assert "q" in props, "应从 _get_parameters 提取参数"


# ═══════════════════════════════════════════════════════════════
# W-4: WebSearchSkill._search_web 是 stub
# ═══════════════════════════════════════════════════════════════

def _load_standalone_skill_system():
    """绕过 neurova.skill_system 包名遮蔽，按文件加载 skill_system.py 单文件模块。

    镜像 skill_system/__init__.py:91-107 的加载策略。
    """
    cache_key = "neurova.skill_system_module_standalone_for_test"
    if cache_key in sys.modules:
        return sys.modules[cache_key]
    mod_path = NEUROVA_DIR / "skill_system.py"
    assert mod_path.exists(), f"skill_system.py 单文件模块必须存在: {mod_path}"
    spec = importlib.util.spec_from_file_location(cache_key, str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = mod
    spec.loader.exec_module(mod)
    return mod


class TestW4WebSearchSkillStub:
    """W-4: WebSearchSkill._search_web 直接 `return []`，是空实现"""

    def test_search_web_not_return_empty_list_stub(self):
        """方法体不应只是 `return []` 单语句（允许 guard 中的 return [] 与 docstring 提及）"""
        import ast

        mod = _load_standalone_skill_system()
        src = inspect.getsource(mod.WebSearchSkill._search_web)
        tree = ast.parse(src.lstrip())
        func = tree.body[0]
        assert isinstance(func, (ast.AsyncFunctionDef, ast.FunctionDef)), "应解析为函数定义"

        # 收集非 docstring 语句
        statements = []
        for stmt in func.body:
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue  # 跳过 docstring
            statements.append(stmt)

        # 判定是否为"仅 return []"的纯 stub
        is_only_return_empty = (
            len(statements) == 1
            and isinstance(statements[0], ast.Return)
            and isinstance(statements[0].value, ast.List)
            and len(statements[0].value.elts) == 0
        )
        assert not is_only_return_empty, (
            "WebSearchSkill._search_web 方法体不应只是 `return []` 单语句空实现"
        )

    def test_search_web_has_real_implementation(self):
        mod = _load_standalone_skill_system()
        src = inspect.getsource(mod.WebSearchSkill._search_web)
        # 真实实现应包含网络请求或委托调用标记
        implementation_markers = [
            "urllib",            # 直接 HTTP 请求
            "requests",          # requests 库
            "httpx",             # httpx 库
            "aiohttp",           # aiohttp
            "_execute_web_search",  # 委托给 ToolExecutor
            "tool_executor",     # 委托给 ToolExecutor
            "raise NotImplementedError",  # 至少显式声明未实现（优于静默 stub）
        ]
        assert any(m in src for m in implementation_markers), (
            "WebSearchSkill._search_web 必须有真实实现（HTTP 请求或委托），"
            f"未找到任何实现标记: {implementation_markers}"
        )
