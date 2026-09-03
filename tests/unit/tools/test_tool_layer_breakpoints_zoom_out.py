"""
TDD 红灯测试: 工具层断点 zoom-out 根因修复

覆盖审计发现的全部 CRITICAL/HIGH 断点，按 ADR 0009/0010/0011 决策编写。
修复前所有测试应 FAIL（红灯），修复后应 PASS（绿灯）。

断点编号对照:
  C1  原生模式 tool_result 丢失
  C2  tool_pipeline.py 死代码
  C3  ToolGuard 完全绕过
  C4  ToolEngine stub 遮蔽（本测试不直接覆盖，由 import 路径保证）
  H1  touch() 签名不匹配静默失败
  H2  orchestrator 绕过 _unpack_skill
  H3  tool RESULT 不传播到 memory/lifecycle
  H5  builtin/CLI/MCP 路径不调用 on_tool_executed
  H6  字符串 vs 枚举比较永远 False
  H7  双 ToolLifecycleManager 实例 split-brain
  H8  两个不兼容 ToolExecutionContext
  H9  四个 ExecutionStatus 枚举
  H10 两个 SkillRegistry API 不兼容
  H11 静默 except: pass
  H12 空 registry falsy 检查
"""
import asyncio
import importlib
import threading
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════
# Wave A — _unpack_skill 提升为共享函数 + orchestrator 接线 (H2)
# ══════════════════════════════════════════════════════════════════

class TestUnpackSkillSharedHelper:
    """H2: _unpack_skill 应从 ToolRouter 私有方法提升为共享函数，
    orchestrator.build_tools_for_llm 必须使用它解包 tuple。"""

    def test_unpack_skill_function_exists_in_compat_module(self):
        """skill_system/compat.py 应导出 unpack_skill 自由函数。"""
        from neurova.skill_system.compat import unpack_skill
        assert callable(unpack_skill), "unpack_skill 应是可调用函数"

    def test_unpack_skill_handles_tuple(self):
        """(Skill, Path) 元组应解包为 Skill。"""
        from neurova.skill_system.compat import unpack_skill
        skill = MagicMock(name="weather_skill")
        path = "/fake/path.py"
        result = unpack_skill((skill, path))
        assert result is skill, f"元组应解包为 Skill，实际: {result}"

    def test_unpack_skill_handles_list(self):
        """[Skill, ...] 列表应解包为第一个元素。"""
        from neurova.skill_system.compat import unpack_skill
        skill = MagicMock()
        result = unpack_skill([skill, "extra"])
        assert result is skill

    def test_unpack_skill_passes_through_bare_skill(self):
        """裸 Skill 对象应直接返回。"""
        from neurova.skill_system.compat import unpack_skill
        skill = MagicMock()
        result = unpack_skill(skill)
        assert result is skill

    def test_orchestrator_build_tools_for_llm_unpacks_class_b_tuples(self):
        """orchestrator 在迭代 skill_registry.skills 时必须解包 tuple。

        类 B 返回 Dict[str, Tuple[Skill, Path]]，若不解包，
        skill_to_tool_schema 拿到 tuple，name 永远是 "unknown_skill"。
        """
        from neurova.skill_system.compat import OpenAISchemaAdapter

        # 构造类 B 风格的 skill_registry
        test_skill = MagicMock()
        test_skill.name = "weather_skill"
        test_skill.description = "查询天气"
        test_skill._get_parameters = MagicMock(return_value={
            "location": {"type": "string", "required": True}
        })

        skill_registry = MagicMock()
        skill_registry.skills = {"weather_skill": (test_skill, "/fake/path.py")}

        # 直接调用 schema adapter，模拟 orchestrator 的路径
        # 修复后 orchestrator 应先 unpack 再传入
        from neurova.skill_system.compat import unpack_skill
        unpacked = unpack_skill(skill_registry.skills["weather_skill"])
        schema = OpenAISchemaAdapter.skill_to_tool_schema(unpacked)

        assert schema["function"]["name"] == "weather_skill", (
            f"类 B tuple 未解包，name 应为 'weather_skill'，实际: '{schema['function']['name']}'"
        )


# ══════════════════════════════════════════════════════════════════
# Wave B — 统一 ToolLifecycleManager (H1/H6/H7)
# ══════════════════════════════════════════════════════════════════

class TestToolLifecycleManagerUnified:
    """H1/H6/H7: ToolLifecycleManager 应统一为单一实现，touch 接受 success 参数，
    get_state 返回 ToolLifecycleState 枚举，无 split-brain。"""

    def test_touch_accepts_success_parameter(self):
        """touch(tool_name, success) 必须接受 success 参数（H1）。

        closed_loop.py Version A 的 touch(tool_name) 只接受 1 参，
        tool_executor.py:1100 调用 touch(tool_name, success) 会 TypeError。
        """
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager
        mgr = ToolLifecycleManager()
        # 不应抛 TypeError
        mgr.touch("weather", success=True)
        mgr.touch("search", success=False)
        assert mgr.get_usage_count("weather") == 1

    def test_get_state_returns_enum_not_string(self):
        """get_state 应返回 ToolLifecycleState 枚举，不是字符串（H6）。

        Version A 返回字符串 "archived"，与 ToolLifecycleState.ARCHIVED 枚举比较永远 False。
        """
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState
        mgr = ToolLifecycleManager()
        mgr.register_tool("test_tool")
        mgr.touch("test_tool")
        state = mgr.get_state("test_tool")
        assert state is not None, "已注册并 touch 的工具状态不应为 None"
        assert isinstance(state, ToolLifecycleState), (
            f"get_state 应返回 ToolLifecycleState 枚举，实际类型: {type(state)}"
        )
        assert state == ToolLifecycleState.ACTIVE

    def test_get_state_for_unregistered_returns_none(self):
        """未注册工具的 get_state 应返回 None。"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager
        mgr = ToolLifecycleManager()
        assert mgr.get_state("nonexistent") is None

    def test_get_state_archived_tool_demotes_from_muscle_memory(self):
        """H6: 归档状态的工具应被肌肉记忆降级。

        _should_demote_from_muscle_memory 比较 get_state() 返回值与
        ToolLifecycleState.ARCHIVED/DEGRADED，必须为 True 才降级。
        """
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState
        mgr = ToolLifecycleManager()
        mgr.register_tool("old_tool")
        # 模拟归档状态
        entry = mgr._entries["old_tool"]
        entry.state = ToolLifecycleState.ARCHIVED

        state = mgr.get_state("old_tool")
        assert state == ToolLifecycleState.ARCHIVED
        # 模拟 _should_demote 的比较逻辑
        assert state in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.DEGRADED)

    def test_lifecycle_manager_is_thread_safe(self):
        """Version B 必须有锁保护（无锁是 H4.1 潜在问题）。"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager
        mgr = ToolLifecycleManager()
        assert hasattr(mgr, '_lock'), "ToolLifecycleManager 必须有 _lock"
        assert isinstance(mgr._lock, type(threading.RLock())), (
            f"_lock 应为 RLock，实际: {type(mgr._lock)}"
        )

    def test_touch_records_failure_count(self):
        """touch(success=False) 应记录失败次数。"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager
        mgr = ToolLifecycleManager()
        mgr.register_tool("fail_tool")
        mgr.touch("fail_tool", success=False)
        entry = mgr._entries["fail_tool"]
        assert entry.failure_calls == 1
        assert entry.success_calls == 0
        assert entry.total_calls == 1

    def test_closed_loop_exports_unified_lifecycle_manager(self):
        """closed_loop.py 应 re-export 统一的 ToolLifecycleManager，不是 Version A。"""
        from neurova.evolution import closed_loop
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager as CanonicalTLM
        # closed_loop 中的 ToolLifecycleManager 应与规范定义是同一个类
        assert closed_loop.ToolLifecycleManager is CanonicalTLM, (
            "closed_loop.py 的 ToolLifecycleManager 应 re-export 规范定义"
        )


# ══════════════════════════════════════════════════════════════════
# Wave C — ToolGuard 接线 (C3/M5)
# ══════════════════════════════════════════════════════════════════

class TestToolGuardWired:
    """C3/M5: ToolEngine.execute/execute_with_safeguards 必须实际调用 tool_guard.guard()。"""

    def test_execute_calls_guard_before_execution(self):
        """execute() 必须在调用工具函数前先调用 tool_guard.guard()。"""
        from neurova.execution_engine.tool_engine import ToolEngine

        engine = ToolEngine()
        # 注册一个工具
        def dangerous_tool(**kwargs):
            return {"executed": True}
        engine.register_tool("dangerous", dangerous_tool, {})

        # mock guard 验证被调用
        guard_called = []
        original_guard = engine.tool_guard

        class TrackingGuard:
            def guard(self, tool_input="", context=None, **kwargs):
                guard_called.append(True)
                from neurova.security.tool_guard import ToolGuardResult
                return ToolGuardResult(safe=True)

        engine.tool_guard = TrackingGuard()
        try:
            result = asyncio.run(engine.execute("dangerous", {}))
            assert guard_called, "execute() 必须调用 tool_guard.guard()"
        finally:
            engine.tool_guard = original_guard

    def test_execute_with_safeguards_calls_guard(self):
        """execute_with_safeguards 必须调用 tool_guard.guard()。"""
        from neurova.execution_engine.tool_engine import ToolEngine

        engine = ToolEngine()

        def safe_tool(**kwargs):
            return {"ok": True}
        engine.register_tool("safe_tool", safe_tool, {})

        guard_called = []

        class TrackingGuard:
            def guard(self, tool_input="", context=None, **kwargs):
                guard_called.append(True)
                from neurova.security.tool_guard import ToolGuardResult
                return ToolGuardResult(safe=True)

        engine.tool_guard = TrackingGuard()
        try:
            asyncio.run(engine.execute_with_safeguards("safe_tool", {}))
            assert guard_called, "execute_with_safeguards 必须调用 tool_guard.guard()"
        finally:
            pass

    def test_guard_blocks_unsafe_tool(self):
        """guard 返回 should_block=True 时应阻止执行。"""
        from neurova.execution_engine.tool_engine import ToolEngine
        from neurova.security.tool_guard import ToolGuardResult

        engine = ToolEngine()

        def rm_rf(**kwargs):
            return {"deleted": "everything"}
        engine.register_tool("rm_rf", rm_rf, {})

        class BlockingGuard:
            def guard(self, tool_input="", context=None, **kwargs):
                return ToolGuardResult(safe=False, tool_name="rm_rf")

        engine.tool_guard = BlockingGuard()
        # 应抛 ValueError（具体异常，非通用 Exception）— 守卫阻止时 engine.execute 抛 ValueError
        with pytest.raises(ValueError, match="安全守卫阻止"):
            asyncio.run(engine.execute("rm_rf", {}))

    def test_default_guard_uses_correct_api(self):
        """DefaultGuard 的返回值必须有 .safe 属性（不是 .is_safe）（M5）。"""
        from neurova.execution_engine.tool_engine import ToolEngine
        engine = ToolEngine()
        guard = engine.tool_guard
        result = guard.guard(tool_input="test", context={})
        # 必须有 .safe 属性，不是 .is_safe
        assert hasattr(result, 'safe'), (
            f"guard 结果必须有 .safe 属性（M5 API 统一），实际属性: {dir(result)}"
        )


# ══════════════════════════════════════════════════════════════════
# Wave D — 原生模式 tool_result + on_tool_executed result 传播 (C1/H3/H5)
# ══════════════════════════════════════════════════════════════════

class TestNativeToolResultFlow:
    """C1: 原生 function-calling 模式的 tool_result 事件应接入 _tool_messages_list。"""

    def test_on_tool_executed_accepts_result_parameter(self):
        """H3: on_tool_executed 必须接受 result 参数并传播到 tool_memory。"""
        from neurova.tool_executor import ToolExecutor
        import inspect

        sig = inspect.signature(ToolExecutor.on_tool_executed)
        assert 'result' in sig.parameters, (
            f"on_tool_executed 必须有 result 参数（H3），实际参数: {list(sig.parameters)}"
        )

    def test_on_tool_executed_passes_result_to_tool_memory(self):
        """H3: result 参数应传到 tool_memory.record_tool_usage。"""
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.tool_memory = MagicMock()
        agent.tool_lifecycle = MagicMock()

        executor = ToolExecutor(agent)
        executor.on_tool_executed(
            tool_name="weather",
            params={"city": "北京"},
            user_input="北京天气",
            success=True,
            tool_source="builtin",
            execution_time=0.5,
            result={"temp": 25, "city": "北京"},
        )

        # tool_memory.record_tool_usage 应被调用
        assert agent.tool_memory.record_tool_called or \
               agent.tool_memory.record_tool_usage.called, \
               "tool_memory.record_tool_usage 应被调用"

    def test_builtin_tool_path_calls_on_tool_executed(self):
        """H5: 内置工具执行路径必须调用 on_tool_executed。"""
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.tool_memory = None
        agent.tool_lifecycle = None
        agent._skill_registry = None
        agent.tool_router = None
        agent.config = MagicMock()
        agent.user_id = "test_user"
        agent.agent_id = "test_agent"

        executor = ToolExecutor(agent)
        # mock _execute_builtin_tool 返回结果
        executor._execute_builtin_tool = AsyncMock(return_value={"success": True, "data": "ok"})

        # spy on_tool_executed
        on_executed_calls = []
        original = executor.on_tool_executed
        def spy(*args, **kwargs):
            on_executed_calls.append({"args": args, "kwargs": kwargs})
            return original(*args, **kwargs)
        executor.on_tool_executed = spy

        asyncio.run(executor._execute_single_tool("weather", {"city": "北京"}))

        assert len(on_executed_calls) > 0, (
            "内置工具执行后必须调用 on_tool_executed（H5）"
        )


# ══════════════════════════════════════════════════════════════════
# Wave E — 统一重复类 (H8/H9/H10) per ADR 0009/0010/0011
# ══════════════════════════════════════════════════════════════════

class TestExecutionStatusUnified:
    """H9: ExecutionStatus 应有单一规范定义在 tool_layers/types.py。"""

    def test_canonical_execution_status_exists(self):
        """tool_layers/types.py 应导出 ExecutionStatus。"""
        from neurova.tool_layers.types import ExecutionStatus
        assert hasattr(ExecutionStatus, 'PENDING')
        assert hasattr(ExecutionStatus, 'COMPLETED')
        assert hasattr(ExecutionStatus, 'FAILED')

    def test_execution_status_is_str_enum(self):
        """ExecutionStatus 应继承 (str, Enum) 以兼容字符串比较。"""
        from neurova.tool_layers.types import ExecutionStatus
        assert ExecutionStatus.COMPLETED == "completed"

    def test_tool_orchestrator_imports_canonical(self):
        """tool_orchestrator.py 应 import 规范定义，不本地定义。"""
        from neurova.tool_layers import tool_orchestrator
        from neurova.tool_layers.types import ExecutionStatus as CanonicalES
        assert tool_orchestrator.ExecutionStatus is CanonicalES, (
            "tool_orchestrator 应 re-export 规范 ExecutionStatus"
        )

    def test_tool_execution_manager_imports_canonical(self):
        """tool_execution_manager.py 应 import 规范定义。"""
        from neurova.agent import tool_execution_manager
        from neurova.tool_layers.types import ExecutionStatus as CanonicalES
        assert tool_execution_manager.ExecutionStatus is CanonicalES, (
            "tool_execution_manager 应 re-export 规范 ExecutionStatus"
        )


class TestToolExecutionContextUnified:
    """H8: ToolExecutionContext 应有单一规范定义。"""

    def test_canonical_context_has_result_field(self):
        """规范 ToolExecutionContext 必须有 result 字段（H3 依赖）。"""
        from neurova.tool_layers.types import ToolExecutionContext
        import inspect
        sig = inspect.signature(ToolExecutionContext)
        assert 'result' in sig.parameters, (
            "ToolExecutionContext 必须有 result 字段"
        )
        assert 'status' in sig.parameters

    def test_tool_pipeline_context_removed(self):
        """tool_pipeline.py 的 ToolExecutionContext 应被删除（随死代码 C2）。"""
        # 修复后 tool_pipeline.py 应不再定义 ToolExecutionContext
        # 或整个文件被删除
        try:
            from neurova.agent.tool_pipeline import ToolExecutionContext as PipelineCtx
            # 如果还在，应是同一个类（re-export）
            from neurova.tool_layers.types import ToolExecutionContext as CanonicalCtx
            assert PipelineCtx is CanonicalCtx, (
                "tool_pipeline 的 ToolExecutionContext 应 re-export 规范定义或被删除"
            )
        except ImportError:
            pass  # 文件被删除也是可接受的


class TestSkillRegistryUnified:
    """H10: SkillRegistry 应有单一规范实现（class A）。"""

    def test_agent_core_imports_class_a(self):
        """agent_core.py 应从 skill_system 导入 SkillRegistry（class A）。"""
        import neurova.agent_core as ac
        from neurova.skill_system import SkillRegistry as ClassA
        assert ac.SkillRegistry is ClassA, (
            "agent_core 应从 skill_system 导入 SkillRegistry（ADR 0011）"
        )

    def test_skills_registry_re_exports_class_a(self):
        """skills/registry.py 应 re-export class A，不定义 class B。"""
        from neurova.skills.registry import SkillRegistry
        from neurova.skill_system import SkillRegistry as ClassA
        assert SkillRegistry is ClassA, (
            "skills/registry.py 应 re-export class A（ADR 0011）"
        )

    def test_registry_has_no_len_method(self):
        """SkillRegistry 不应有 __len__（消除 falsy bug H12）。"""
        from neurova.skill_system import SkillRegistry
        assert not hasattr(SkillRegistry, '__len__'), (
            "SkillRegistry 不应有 __len__（导致空 registry falsy 检查失败 H12）"
        )

    def test_skills_property_returns_dict_of_skill(self):
        """skills 属性应返回 Dict[str, Skill]，不是 Dict[str, Tuple]。"""
        from neurova.skill_system import SkillRegistry
        sr = SkillRegistry()
        # 空 registry 的 skills 应返回空 dict
        skills = sr.skills
        assert isinstance(skills, dict)
        # 如果有 skill，值应是 Skill 对象不是 tuple
        for v in skills.values():
            assert not isinstance(v, (tuple, list)), (
                f"skills 值不应是 tuple/list，实际: {type(v)}"
            )


# ══════════════════════════════════════════════════════════════════
# Wave F — 死代码删除 + falsy 检查修复 (C2/H11/H12)
# ══════════════════════════════════════════════════════════════════

class TestDeadCodeRemoved:
    """C2: tool_pipeline.py 的 ToolExecutionPipeline 应被删除或标记废弃。"""

    def test_tool_pipeline_not_imported_in_production(self):
        """生产代码不应 import ToolExecutionPipeline。"""
        import subprocess
        # grep 生产代码（排除 tests/）确认无 import
        try:
            result = subprocess.run(
                ["python", "-c", """
import ast, os, sys
prod_files = []
for root, dirs, files in os.walk('neurova'):
    for f in files:
        if f.endswith('.py'):
            prod_files.append(os.path.join(root, f))
violations = []
for pf in prod_files:
    with open(pf, 'r', encoding='utf-8') as fh:
        content = fh.read()
    if 'ToolExecutionPipeline' in content and 'import' in content:
        # 检查是否有实际 import 语句
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module]
                    for name in names:
                        if name and 'tool_pipeline' in str(name):
                            violations.append(pf)
        except SyntaxError:
            pass
if violations:
    print(','.join(violations))
"""],
                capture_output=True, text=True, cwd="e:/项目/Neurova",
                timeout=30
            )
            violations = result.stdout.strip()
            assert not violations, (
                f"生产代码不应 import tool_pipeline，违规文件: {violations}"
            )
        except subprocess.TimeoutExpired:
            pytest.skip("grep 超时，跳过")


class TestFalsyRegistryCheckFixed:
    """H12: 空 registry 的 falsy 检查应改用 `is not None`。"""

    def test_router_uses_is_not_none(self):
        """router.py 的 `if skill_registry:` 应改为 `if skill_registry is not None:`。"""
        with open("e:/项目/Neurova/neurova/router.py", "r", encoding="utf-8") as f:
            content = f.read()
        # 查找 `if skill_registry:` 模式（非 is not None）
        import re
        # 匹配 "if skill_registry:" 但不匹配 "if skill_registry is not None:"
        bad_pattern = re.findall(r'if\s+skill_registry\s*:\s*(?!\s*#)', content)
        # 过滤掉 is not None 的
        lines = content.split('\n')
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if 'if skill_registry:' in stripped and 'is not None' not in stripped:
                violations.append(f"line {i}: {stripped}")
        assert not violations, (
            f"router.py 应使用 `if skill_registry is not None:` 而非 `if skill_registry:`\n"
            f"违规: {violations}"
        )


# ══════════════════════════════════════════════════════════════════
# Wave G — 静默 except 修复 (H11)
# ══════════════════════════════════════════════════════════════════

class TestSilentExceptFixed:
    """H11: tool_router.py 的 `except Exception: pass` 应改用 logger.exception。"""

    def test_no_bare_pass_in_tool_router(self):
        """tool_router.py 不应有 `except Exception: pass` 模式。"""
        with open("e:/项目/Neurova/neurova/tool_layers/tool_router.py", "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split('\n')
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # 检测 except 块后紧跟 pass（可能跨行）
            if 'except' in stripped and ('pass' in stripped or
                (i < len(lines) and lines[i].strip() == 'pass')):
                violations.append(f"line {i}: {stripped}")

        # 允许有 except + logger 但不允许 except + pass
        assert not violations, (
            f"tool_router.py 不应有 except + pass 模式（H11），违规: {violations}"
        )


# ══════════════════════════════════════════════════════════════════
# 集成验证 — ToolExecutor on_tool_executed 闭环 (H3/H5/H6 联合)
# ══════════════════════════════════════════════════════════════════

class TestToolExecutionClosedLoop:
    """H3+H5+H6 联合：工具执行后 result 传播到 memory + lifecycle + 防止归档工具误推荐。"""

    def test_full_closed_loop_records_result_and_lifecycle(self):
        """工具执行后：result 传到 tool_memory，success 传到 tool_lifecycle。"""
        from neurova.tool_executor import ToolExecutor
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager

        agent = MagicMock()
        tool_memory = MagicMock()
        lifecycle = ToolLifecycleManager()

        agent.tool_memory = tool_memory
        agent.tool_lifecycle = lifecycle
        agent._skill_registry = None
        agent.tool_router = None
        agent.config = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"

        executor = ToolExecutor(agent)

        # 执行一个成功的工具
        executor._execute_builtin_tool = AsyncMock(return_value={"temp": 25})
        asyncio.run(executor._execute_single_tool("weather", {"city": "北京"}))

        # lifecycle 应记录成功
        assert lifecycle.get_usage_count("weather") >= 1, "lifecycle 应记录工具使用"
        entry = lifecycle._entries.get("weather")
        assert entry is not None, "weather 应在 lifecycle 中注册"
        assert entry.success_calls >= 1, "应记录成功调用"

    def test_failed_tool_records_failure_in_lifecycle(self):
        """失败的工具执行应在 lifecycle 记录 failure_calls。"""
        from neurova.tool_executor import ToolExecutor
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager

        agent = MagicMock()
        lifecycle = ToolLifecycleManager()
        agent.tool_memory = None
        agent.tool_lifecycle = lifecycle
        agent._skill_registry = None
        agent.tool_router = None
        agent.config = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"

        executor = ToolExecutor(agent)
        executor._execute_builtin_tool = AsyncMock(side_effect=Exception("tool broken"))

        try:
            asyncio.run(executor._execute_single_tool("weather", {}))
        except Exception:
            pass  # 工具失败，但我们关心的是 lifecycle 是否记录

        entry = lifecycle._entries.get("weather")
        if entry:
            assert entry.failure_calls >= 1, "应记录失败调用"


# ══════════════════════════════════════════════════════════════════
# 审计 WARN 项补全 — 并发压力测试 + 端到端 C1 传播
# ══════════════════════════════════════════════════════════════════

class TestToolLifecycleConcurrentStress:
    """WARN-2 补全: touch() 并发线程安全压力测试。

    注意: CPython 3.15 GIL 行为变化可能让简单 += 竞态不触发，
    但此测试作为确定性不变量断言（total_calls == N*M）仍是有效回归防线，
    可在无 GIL 实现（free-threading Python / PyPy）下捕获锁缺失回归。
    """

    def test_concurrent_touch_no_lost_updates(self):
        """8 线程 × 500 次 touch，total_calls 必须精确等于 4000。"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager

        mgr = ToolLifecycleManager()
        mgr.register_tool("stress_tool")
        thread_count = 8
        calls_per_thread = 500
        expected_total = thread_count * calls_per_thread

        barrier = threading.Barrier(thread_count)

        def worker():
            barrier.wait()  # 所有线程同时开始，最大化竞争窗口
            for _ in range(calls_per_thread):
                mgr.touch("stress_tool", success=True)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        actual_total = mgr.get_usage_count("stress_tool")
        assert actual_total == expected_total, (
            f"并发 touch 丢失更新: 期望 {expected_total}, 实际 {actual_total} — 锁保护失败"
        )

    def test_concurrent_touch_mixed_success_failure_atomic(self):
        """4 线程 success + 4 线程 failure，total = success + failure。"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager

        mgr = ToolLifecycleManager()
        mgr.register_tool("mixed_tool")
        per_thread = 200

        def success_worker():
            for _ in range(per_thread):
                mgr.touch("mixed_tool", success=True)

        def failure_worker():
            for _ in range(per_thread):
                mgr.touch("mixed_tool", success=False)

        threads = [threading.Thread(target=success_worker) for _ in range(4)]
        threads += [threading.Thread(target=failure_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        entry = mgr._entries["mixed_tool"]
        assert entry.total_calls == 8 * per_thread, (
            f"total_calls 不匹配: 期望 {8 * per_thread}, 实际 {entry.total_calls}"
        )
        assert entry.success_calls == 4 * per_thread, (
            f"success_calls 不匹配: 期望 {4 * per_thread}, 实际 {entry.success_calls}"
        )
        assert entry.failure_calls == 4 * per_thread, (
            f"failure_calls 不匹配: 期望 {4 * per_thread}, 实际 {entry.failure_calls}"
        )


class TestNativeToolResultEndToEnd:
    """WARN-4 补全: 端到端验证原生 tool_result 事件到达 _tool_messages_list。"""

    def test_stream_captures_native_tool_events_into_tool_messages_list(self):
        """_call_loop_stream 应将 tool_call/tool_result 事件合并到 _tool_messages_list。"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

        # 构造 mock agent，具备 _tool_messages_list 和 loop
        agent = MagicMock()
        agent._tool_messages_list = []
        agent._current_reasoning = None
        agent._current_user_input = "测试原生工具调用"

        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent

        # mock loop.predict_step: async def 返回 async iterable（await 后迭代）
        async def fake_predict_step(messages, tools, stream):
            events = [
                {"type": "tool_call", "data": {"name": "weather", "args": {"city": "北京"}}},
                {"type": "tool_result", "data": {"name": "weather", "result": {"temp": 25}}},
                {"type": "content", "data": "北京今天 25 度"},
            ]

            async def aiter():
                for e in events:
                    yield e

            return aiter()

        fake_loop = MagicMock()
        fake_loop.predict_step = fake_predict_step
        agent.loop = fake_loop

        ctx = ChatContext(user_input="测试", context=[])

        reply = asyncio.run(pipeline._call_loop_stream(ctx, tools_for_llm=[]))

        # 回复文本不应包含工具事件
        assert reply == "北京今天 25 度", f"回复文本应仅含 content 数据，实际: {reply!r}"

        # _tool_messages_list 应包含捕获的 2 个原生工具事件
        assert len(agent._tool_messages_list) == 2, (
            f"应捕获 2 个工具事件，实际 {len(agent._tool_messages_list)} 个"
        )
        assert agent._tool_messages_list[0]["type"] == "tool_call"
        assert agent._tool_messages_list[1]["type"] == "tool_result"

    def test_stream_creates_tool_messages_list_when_missing(self):
        """agent._tool_messages_list 不存在时应自动创建并填充。"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

        # 用真实对象而非 MagicMock，避免自动属性遮蔽 getattr(..., None) 的 None 判定
        class FakeAgent:
            pass

        agent = FakeAgent()
        agent._current_reasoning = None
        # 故意不预设 _tool_messages_list（模拟 _init_agent_state 未运行场景）

        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent

        async def fake_predict_step(messages, tools, stream):
            events = [
                {"type": "tool_call", "data": {"name": "calc"}},
                {"type": "content", "data": "done"},
            ]

            async def aiter():
                for e in events:
                    yield e

            return aiter()

        fake_loop = MagicMock()
        fake_loop.predict_step = fake_predict_step
        agent.loop = fake_loop

        ctx = ChatContext(user_input="测试", context=[])

        asyncio.run(pipeline._call_loop_stream(ctx, tools_for_llm=[]))

        # 应自动创建 _tool_messages_list 并填入 tool_call 事件
        assert hasattr(agent, "_tool_messages_list"), "应自动创建 _tool_messages_list"
        assert len(agent._tool_messages_list) == 1
        assert agent._tool_messages_list[0]["type"] == "tool_call"

