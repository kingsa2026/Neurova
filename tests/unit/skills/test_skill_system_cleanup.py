"""
A9-A10 测试：验证 skill_system 僵尸文件和死代码清理

TDD vertical slices:
1. test_skill_system_py_file_removed — A9.1: neurova/skill_system.py 僵尸文件被删除
2. test_skill_result_exported_from_skill_system — A9.2: skill_system 导出 SkillResult
3. test_compat_module_exists — A9.3: skill_system.compat 子模块存在并导出 OpenAISchemaAdapter
4. test_pool_service_py_file_removed — A10.1: neurova/skills/pool_service.py 死代码被删除
"""

from pathlib import Path


def test_skill_system_py_standalone_loadable():
    """A9.1（2026-09-08 架构甄别后改写）：skill_system.py 是 ADR 0011 的
    规范实现载体（SkillRegistry/get_skill_registry/create_default_skills），
    由 skill_system/__init__ 经 spec_from_file_location 有意加载为
    neurova.skill_system_module_standalone——不再是"僵尸"，而是生产依赖
    （mcp_server_api/marketplace/skill/neurflow 四端点取 get_skill_registry）。
    守卫锁定：文件必须存在且经 standalone 缓存键可加载。"""
    skill_system_py = Path(__file__).parent.parent.parent.parent / "neurova" / "skill_system.py"
    assert skill_system_py.exists(), (
        f"standalone 载体 {skill_system_py} 不存在——get_skill_registry 加载链断裂"
    )
    from neurova.skill_system import get_skill_registry
    assert callable(get_skill_registry)


def test_skill_result_exported_from_skill_system():
    """A9.2: skill_system 应导出 SkillResult

    根因：github_push/skill.py:39 调用 `from neurova.skill_system import Skill, SkillResult`，
    但 SkillResult 不在 skill_system/__init__.py 的 __all__ 中，也不在 __getattr__ 代理分支中，
    导致运行时 AttributeError。
    """
    import sys
    for mod_name in list(sys.modules.keys()):
        if mod_name == "neurova.skill_system":
            del sys.modules[mod_name]

    from neurova.skill_system import SkillResult
    from neurova.skills.executor import SkillResult as RealSkillResult

    assert SkillResult is RealSkillResult, (
        "skill_system.SkillResult 应等于 neurova.skills.executor.SkillResult"
    )


def test_compat_module_exists():
    """A9.3: skill_system.compat 子模块应存在并导出 OpenAISchemaAdapter

    根因：agent/loops/base.py:237 和 context/orchestrator.py:591 调用
    `from neurova.skill_system.compat import OpenAISchemaAdapter`，
    但 neurova/skill_system/compat.py 子模块不存在，导致运行时 ModuleNotFoundError
    （虽有 try/except 降级，但降级路径生成的 schema 缺少参数信息，影响 LLM 工具调用质量）。
    """
    import sys
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("neurova.skill_system.compat"):
            del sys.modules[mod_name]

    from neurova.skill_system.compat import OpenAISchemaAdapter

    # 验证 OpenAISchemaAdapter 有 skill_to_tool_schema 方法
    assert hasattr(OpenAISchemaAdapter, "skill_to_tool_schema"), (
        "OpenAISchemaAdapter 应有 skill_to_tool_schema 静态方法/类方法"
    )


def test_compat_openai_schema_adapter_generates_valid_schema():
    """A9.3 补充：OpenAISchemaAdapter.skill_to_tool_schema 应返回有效的 OpenAI tool schema

    调用方（base.py:245, orchestrator.py:593）期望返回 dict 含 type/function/name/description/parameters。
    """
    import sys
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("neurova.skill_system.compat"):
            del sys.modules[mod_name]

    from neurova.skill_system.compat import OpenAISchemaAdapter
    from neurova.skills.models import Skill, SkillSource

    skill = Skill(
        id="test_skill",
        name="Test Skill",
        description="A test skill",
        source=SkillSource.BUILTIN,
    )

    schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)

    assert isinstance(schema, dict), f"schema 应为 dict，实际: {type(schema)}"
    assert schema["type"] == "function", f'schema["type"] 应为 "function"，实际: {schema.get("type")}'
    assert "function" in schema, "schema 应含 function 键"
    assert schema["function"]["name"] == "Test Skill"
    assert schema["function"]["description"] == "A test skill"
    assert "parameters" in schema["function"], "function 应含 parameters 键"


def test_pool_service_py_file_removed():
    """A10.1: neurova/skills/pool_service.py 死代码应被删除

    根因：pool_service.py（套3）零调用方，注释自称"已删除"但文件物理存在，
    造成维护陷阱。全项目 grep 确认无 `from neurova.skills.pool_service import` 语句。
    """
    pool_service_py = Path(__file__).parent.parent.parent.parent / "neurova" / "skills" / "pool_service.py"
    assert not pool_service_py.exists(), (
        f"死代码文件 {pool_service_py} 仍存在，应删除（零调用方）"
    )
