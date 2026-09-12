"""T1 Schema 契约护栏 — docs/Neurova_工具调用链升级计划_2026-09-13.md。

钉三件事（Needle 对比结论：schema 单源↔执行体一致性从隐性约定变机器契约）：
1. dispatch/schema 键对账（防"执行器能跑但模型看不见"/"模型能传但无人接"）；
2. 执行体 AST 读取参数 ⊆ schema 声明（防参数静默丢弃——ChannelIntegrationPage
   同族根因的横向防线）；
3. _BUILTIN_SCHEMAS 全部 parameters 为合法 JSON Schema（Draft 2020-12）。

AST 局限（登记在案）：仅识别字面量键的 params.get("x")/params["x"] 读取；
把 params 整体传给辅助函数的读取由 READ_EXEMPT 显式豁免（逐条带理由）。
"""
import ast
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neurova.builtin_tools import _BUILTIN_SCHEMAS
import neurova.tool_executor as _te

_SRC = Path(_te.__file__).read_text(encoding="utf-8")

# dispatch 表中不另立 schema 的既有别名（2026-09-13 AST 对账实据；两键均为
# 正规名方法的第二入口，参数面与目标一致，属有意兼容别名非漂移）
DISPATCH_ALIASES = {"execute_code": "run_code", "search": "web_search"}

# to_openai_format 统一注入的展示参数（builtin_tools.py _TASK_NAME_PARAM_DEFS），
# 执行层分发前剥离、不进 _execute_* 方法
_INJECTED_KEYS = {"taskNameActive", "taskNameComplete"}

# 红灯期逐条裁决后的豁免表：工具名 → 执行体合法读取但未进 schema 的键。
# 每条必须带行内理由；无登记的违规一律按 bug 修 schema 或修执行体。
READ_EXEMPT: dict[str, set] = {
    # get_datetime 兼容别名：执行体 `params.get("timezone") or params.get("tz")`，
    # tz 为历史会话/旧提示词的别名，schema 单一规范名只暴露 timezone，双名进
    # schema 反而诱导模型混用（2026-09-13 裁决）
    "get_datetime": {"tz"},
}


def _dispatch_map() -> dict:
    # dispatch 为带注解赋值 `_builtin_dispatch: Dict[str, str] = {`，注解体
    # 含 `:` 与逗号，正则必须越过注解取到字面量体
    m = re.search(r"_builtin_dispatch[^{]*\{(.*?)\n    \}", _SRC, re.S)
    assert m, "_builtin_dispatch 字面量结构变化，同步本测试解析器"
    return dict(re.findall(r'"([a-z_0-9.]+)":\s*"(_execute_\w+)"', m.group(1)))


def _method_ast(name: str):
    tree = ast.parse(_SRC)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ToolExecutor")
    # 内置执行体全部 async def → 必须同时匹配 FunctionDef/AsyncFunctionDef
    fn = next(
        (f for f in cls.body
         if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == name),
        None,
    )
    assert fn, f"ToolExecutor 缺失 {name}"
    return fn


def _params_read(fn) -> set:
    """AST 提取字面量读取：params.get("k"...) 与 params["k"]。"""
    keys = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def test_dispatch_schema_parity():
    extra = set(_dispatch_map()) - set(_BUILTIN_SCHEMAS) - set(DISPATCH_ALIASES)
    assert not extra, f"dispatch 存在未登记 schema 的工具: {sorted(extra)}"


def test_all_builtin_schemas_valid_json_schema():
    bad = []
    for name, entry in _BUILTIN_SCHEMAS.items():
        try:
            Draft202012Validator.check_schema(entry["parameters"])
        except Exception as exc:
            bad.append(f"{name}: {exc.message}")
    assert not bad, "非法 parameters schema:\n" + "\n".join(bad)


@pytest.mark.parametrize("tool", sorted(_BUILTIN_SCHEMAS))
def test_executor_reads_only_declared_params(tool):
    method = _dispatch_map().get(tool)
    if method is None:
        pytest.skip("非 builtin dispatch 工具")
    declared = set((_BUILTIN_SCHEMAS[tool]["parameters"] or {}).get("properties") or {})
    undeclared = (
        _params_read(_method_ast(method))
        - declared
        - _INJECTED_KEYS
        - READ_EXEMPT.get(tool, set())
    )
    assert not undeclared, f"{tool} 执行体读取未声明参数（模型无法供给）: {sorted(undeclared)}"
