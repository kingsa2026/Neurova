"""
A9-A10 测试：验证 skill_system 僵尸文件和死代码清理

TDD vertical slices:
1. test_skillSystemCarrierResolvesInsidePackage — A9.1: 规范实现载体在包内 core.py
2. test_skillResultExportedIsRuntimeContract — A9.2: 门面导出的 SkillResult 即运行时返回的那份
3. test_compat_module_exists — A9.3: skill_system.compat 子模块存在并导出 OpenAISchemaAdapter
4. test_pool_service_py_file_removed — A10.1: neurova/skills/pool_service.py 死代码被删除
"""

from pathlib import Path


def test_skillSystemCarrierResolvesInsidePackage():
    """A9.1（2026-10-07 搬家后改写）：ADR 0011 规范实现的载体在包内 `core.py`。

    原守卫锁"顶层 skill_system.py 必须存在并可被反射加载"——那是遮蔽 bug 的
    产物，不是架构决策。现按**导入解析结果**判：门面所发工厂必须来自包内模块，
    影子文件是否回流由 test_skillSymbolSingleCarrier 锁（两条守卫不重复取证）。
    """
    from neurova.skill_system import core, get_skill_registry

    assert callable(get_skill_registry), "get_skill_registry 装配链断裂"
    carrier = Path(core.__file__).resolve()
    assert (carrier.parent.name, carrier.name) == ("skill_system", "core.py"), (
        f"规范实现载体不在包内：{carrier}"
    )


def test_skillResultExportedIsRuntimeContract():
    """A9.2 改判：门面导出的 SkillResult 必须是注册表实际返回的那一份。

    原判把 `skills/executor.py:SkillResult`（output 形状）钉成规范，而注册表与
    agent 热路径（`agent/loops/base.py` 读 `.data`）返回的是运行时 data 形状——
    名实分叉期间，端点降级分支 `getattr(result, "output")` 恒为 None。
    """
    from neurova.skill_system import SkillResult
    from neurova.skill_system.core import SkillResult as RuntimeSkillResult

    assert SkillResult is RuntimeSkillResult, (
        "门面名 SkillResult 与运行时返回的类不同一——同一符号又分叉出两条契约"
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
