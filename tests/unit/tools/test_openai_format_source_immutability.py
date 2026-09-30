"""展示层转换不得回写事实源（`_BUILTIN_SCHEMAS`）。

起因不是形式问题：`to_openai_format()` 给每个内置工具注入 `taskNameActive` /
`taskNameComplete` 两个展示参数，注入用的是 `params.setdefault(...)`——它写的是
`_BUILTIN_SCHEMAS[name]["parameters"]` **那个对象本身**。于是任何一次序列化之后，
事实源里就多出了两个模型面参数，后续所有按 schema 参数面做判定的消费方
（权限归类、幻影旋钮守卫、参数白名单对账）读到的是脏值，且读数取决于
"在此之前有没有人调过序列化"——同一份声明在不同测试顺序下给出不同答案。

判据取两面：
1. 转换后事实源逐字不变（本文件的主张）；
2. 模型可见面照样带上注入参数（反向锁，防止"修"成把注入删掉）。
"""

import typing

from neurova.builtin_tools import BuiltinToolRegistry, _BUILTIN_SCHEMAS

# 出口注入的展示参数（单源见 builtin_tools._TASK_NAME_PARAM_DEFS）
DISPLAY_INJECTED = {"taskNameActive", "taskNameComplete"}


def _propertyNames() -> typing.Dict[str, typing.List[str]]:
    return {
        name: sorted((schema.get("parameters") or {}).get("properties", {}))
        for name, schema in _BUILTIN_SCHEMAS.items()
    }


def test_toOpenaiFormat_leavesTheSchemaSourceUntouched():
    before = _propertyNames()
    registry = BuiltinToolRegistry()
    for tool in registry._tools.values():
        tool.to_openai_format()
    assert _propertyNames() == before, (
        "序列化一次就把展示参数写进了事实源，参数面读数随调用顺序漂："
        + str({
            name: sorted(set(after) - set(before.get(name, [])))
            for name, after in _propertyNames().items()
            if set(after) - set(before.get(name, []))
        })
    )
    for name, props in _propertyNames().items():
        leaked = DISPLAY_INJECTED & set(props)
        assert not leaked, f"{name} 的事实源参数面带着出口注入的展示参数：{sorted(leaked)}"


def test_displayParamsStillReachTheModelFacingPayload():
    """反向锁：修的是"写回事实源"，不是注入本身——模型侧仍要看见这两个参数。"""
    registry = BuiltinToolRegistry()
    fmt = registry.get_tool("browser_click_ref").to_openai_format()
    props = fmt["function"]["parameters"]["properties"]
    assert DISPLAY_INJECTED <= set(props), sorted(props)
    assert "ref" in props, "注入不该挤掉业务参数"


def test_outgoingParametersObjectIsNotTheSourceObject():
    """下游还会就地消毒（`orchestrator._build_tools_for_llm` 给 parameters 补
    `type` / `properties`），所以出口必须交出一个**新对象**——否则消毒又会写回事实源。
    """
    registry = BuiltinToolRegistry()
    tool = registry.get_tool("browser_click_ref")
    fmt = tool.to_openai_format()
    assert fmt["function"]["parameters"] is not tool.parameters
    assert fmt["function"]["parameters"]["properties"] is not tool.parameters["properties"]
