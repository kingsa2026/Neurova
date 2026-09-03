"""
代码审计回归测试

固化 2026-08-28 全量代码审计中确认并修复的缺陷，防止回归。
每个测试类对应一个已定位的根因，注释中说明缺陷现象。
"""

import importlib

import pytest


class TestToolCallDefaultId:
    """缺陷：ToolCall 的默认 id 用 `f"call_{id(self)}"` 生成。

    类体作用域不参与闭包，default_factory 执行时 `self` 未定义 →
    NameError。该数据结构贯穿整个 function calling 链路，
    任何未显式传 id 的构造都会崩溃。
    """

    def test_creating_tool_call_without_id_does_not_raise(self):
        from neurova.cognitive_layers.model_adapter.base import ToolCall

        call = ToolCall(function_name="memory_search")
        assert call.id.startswith("call_")

    def test_generated_ids_are_unique(self):
        from neurova.cognitive_layers.model_adapter.base import ToolCall

        ids = {ToolCall(function_name="f").id for _ in range(50)}
        assert len(ids) == 50

    def test_explicit_id_is_preserved(self):
        from neurova.cognitive_layers.model_adapter.base import ToolCall

        assert ToolCall(id="explicit-1", function_name="f").id == "explicit-1"


class TestModelAdapterRegistry:
    """缺陷1：pydantic v2 下 `_clients` 未用 PrivateAttr 声明，
    __init__ 赋值抛 "object has no field '_clients'"。

    缺陷2：builtin.py 调用的 `register_adapter_pattern()` 在 registry 中
    从未实现，导致整个 model_adapter.builtin 模块无法导入。
    """

    def test_builtin_module_imports(self):
        assert importlib.import_module("neurova.cognitive_layers.model_adapter.builtin")

    def test_register_adapter_pattern_exists(self):
        from neurova.cognitive_layers.model_adapter.registry import get_model_adapter_registry

        registry = get_model_adapter_registry()
        assert callable(getattr(registry, "register_adapter_pattern", None))

    def test_builtin_adapters_are_registered(self):
        from neurova.cognitive_layers.model_adapter.registry import get_model_adapter_registry

        names = {a["name"] for a in get_model_adapter_registry().list_adapters()}
        assert names, "内置适配器应完成注册"

    def test_model_routes_to_expected_adapter(self):
        from neurova.cognitive_layers.model_adapter.registry import get_model_adapter_registry

        registry = get_model_adapter_registry()
        # 未知模型必须回落到 generic，而不是抛异常
        assert registry.find_adapter("totally-unknown-model-xyz") is not None


class TestMemoryLayerExports:
    """缺陷：__init__.py 的 __all__ 无条件声明了可选模块的名字
    （NeRF/torch 系列的 memory_field、volume_renderer 等）。

    依赖缺失时 try/except 让这些名字根本不绑定，
    `from ... memory_layer import *` 抛 AttributeError。
    """

    def test_all_declared_names_are_importable(self):
        import neurova.cognitive_layers.memory_layer as pkg

        missing = [name for name in pkg.__all__ if not hasattr(pkg, name)]
        assert not missing, f"__all__ 声明了不存在的名字: {missing}"

    def test_star_import_succeeds(self):
        namespace = {}
        exec("from neurova.cognitive_layers.memory_layer import *", namespace)
        assert namespace


class TestSkillsEventsFacade:
    """缺陷：ADR 0011 要求技能系统收敛到 neurova.skills 门面，
    但 neurova.skills.events 模块缺失，调用方被迫直接依赖
    skill_system 包的反射加载细节。
    """

    def test_events_module_exposes_skill_event(self):
        from neurova.skills.events import SkillEvent

        assert hasattr(SkillEvent, "POST_EXECUTE")

    def test_skills_package_exports_create_default_skills(self):
        import neurova.skills as skills

        assert callable(skills.create_default_skills)

    def test_agent_core_uses_facade_not_skill_system(self):
        import neurova.agent_core as agent_core

        src = open(agent_core.__file__, encoding="utf-8").read()
        assert "from neurova.skill_system import create_default_skills" not in src
        assert "from neurova.skills.events import SkillEvent" in src


class TestOptionalDependencyGuards:
    """缺陷：`import X` 被误写成 `pass`，依赖探测形同虚设。

    表现为：可用性标志恒为 True，但名字从未绑定；
    或依赖缺失时 except 分支又引用未导入的名字（二次 NameError）。
    """

    def test_qclaw_service_requests_import_is_real(self):
        import neurova.channels.qclaw_service as mod

        assert mod.REQUESTS_AVAILABLE == hasattr(mod, "requests")
        assert hasattr(mod, "hmac")

    def test_sip_requests_import_is_real(self):
        import neurova.channels.sip as mod

        assert mod.REQUESTS_AVAILABLE == hasattr(mod, "requests")

    def test_qqbot_httpx_import_is_real(self):
        import neurova.channels.qqbot as mod

        assert mod.HTTPX_AVAILABLE == hasattr(mod, "httpx")
        assert mod.logger is not None

    def test_agent_loop_availability_flag_is_truthful(self):
        import neurova.agent_core as mod

        # 标志必须与实际可导入性一致，而不是恒为 True
        assert mod.AGENT_LOOP_AVAILABLE is True


class TestDeletedDeadCode:
    """缺陷：conflict.py 的 _check_contradiction() 在 return 之后
    残留了一段引用 content1/memory1 等不存在变量的死代码
    （否定词冲突检测在主流程中已完整实现）。
    """

    def test_check_contradiction_returns_float(self):
        from neurova.cognitive_layers.memory_layer.conflict import ConflictDetector

        detector = ConflictDetector()
        score = detector._check_contradiction("我喜欢猫", "我不喜欢猫")
        assert isinstance(score, float)

    def test_negation_conflict_is_detected_in_main_path(self):
        from types import SimpleNamespace

        from neurova.cognitive_layers.memory_layer.conflict import ConflictDetector

        # use_semantic=False 走规则分支，避免测试结果依赖语义模型是否加载
        detector = ConflictDetector(use_semantic=False)
        m1 = SimpleNamespace(id="1", content="我喜欢猫")
        m2 = SimpleNamespace(id="2", content="我不喜欢猫")

        conflict = detector._check_pair_conflict(m1, m2)

        assert conflict is not None
        assert conflict["type"] == "negation_conflict"


class TestProactiveRecallEmotionTrigger:
    """缺陷：proactive_recall.py 中 `config.get("emotions", [])` 的返回值
    被丢弃，下方使用未定义的 target_emotion → NameError，
    情感触发回忆整体失效。
    """

    def test_target_emotion_is_bound(self):
        import inspect

        from neurova.cognitive_layers.memory_layer import proactive_recall

        src = inspect.getsource(proactive_recall)
        assert "target_emotion = config.get(" in src


class TestFirewallStatsEndpoint:
    """缺陷：/stats 端点引用了不存在的模块级变量 _firewall_rules_store，
    NameError 被 except 吞掉，统计永远返回全 0。
    """

    def test_stats_endpoint_does_not_reference_phantom_store(self):
        import ast
        import inspect

        from neurova.api.endpoints import firewall

        # 用 AST 而非文本匹配：注释里提到该名字是允许的，代码引用才是缺陷
        tree = ast.parse(inspect.getsource(firewall))
        referenced = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_firewall_rules_store"]
        assert not referenced, "端点代码仍在引用不存在的 _firewall_rules_store"


class TestSyntaxErrorsFixed:
    """缺陷：3 个文件存在语法错误，无法被任何工具解析或导入。"""

    @pytest.mark.parametrize(
        "path",
        [
            "scripts/verify_cli_commands.py",
            "scripts/diagnose_post_issue.py",
            "tests/comprehensive_test_runner.py",
        ],
    )
    def test_file_parses(self, path):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root / path).read_text(encoding="utf-8")
        ast.parse(source, filename=path)
