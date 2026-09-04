"""工具参数守卫测试（OpenOcta 启发 P1-5：toolArgumentsGuard）

OpenOcta 把生产踩过的 LLM 坑做成中间件（tool_arguments_guard.go）：
- 参数别名重映射：path/file/filename/filepath/filePath → file_path
- 截断 JSON 检测：手写括号/引号配平计数，能修则修
- 失败返回带修复建议的错误文案回灌模型，而不是让工具报错消耗迭代次数

Neurova 落点：ToolExecutor._execute_single_tool 咽喉点（治理预检之前，
治理评估看到的是修正后的参数）。装配语义对齐 tool_circuit_breaker：
**默认不安装**（install_tool_param_guard 显式装配，幂等），未安装时
get_param_guard() 返回 None、行为与未接入完全等价。

别名分两档（防误伤）：
- 无歧义档（无需 schema）：filename/filepath/filePath/file_name/fileName
  → file_path —— 没有工具以它们为规范参数名
- schema 感知档：path/file/link/cmd —— 可能是某些工具的真实参数名，
  仅当工具 schema 声明了目标规范名（且别名不是 schema 参数）时才重映射
"""
from __future__ import annotations

import pytest


@pytest.fixture
def guard():
    from neurova.security.tool_param_guard import ParamGuard

    return ParamGuard()


class TestAliasRemap:
    """别名归一：LLM 手滑写错参数名不再白跑一轮。"""

    def test_unambiguous_alias_without_schema(self, guard):
        """无 schema 时无歧义别名直接归一（filename → file_path）。"""
        params, rejection = guard.guard("file_read", {"filename": "a.txt"})
        assert rejection is None
        assert params == {"file_path": "a.txt"}

    def test_schema_required_alias_needs_schema(self):
        """path/file 是歧义别名：无 schema 不动，有 schema 且声明了目标才归一。"""
        from neurova.security.tool_param_guard import ParamGuard

        g = ParamGuard()
        # 无 schema：path 不动（可能是真实参数名）
        params, _ = g.guard("some_tool", {"path": "x"})
        assert params == {"path": "x"}

        # schema 声明了 file_path → 归一
        g2 = ParamGuard(schema_provider=lambda name: {"file_path"})
        params, _ = g2.guard("some_tool", {"path": "x"})
        assert params == {"file_path": "x"}

        # schema 声明 path 本身是真实参数 → 不动
        g3 = ParamGuard(schema_provider=lambda name: {"path"})
        params, _ = g3.guard("some_tool", {"path": "x"})
        assert params == {"path": "x"}

    def test_no_remap_when_canonical_present(self, guard):
        """规范名已存在时不归一（两个值可能各有语义，不擅删）。"""
        params, rejection = guard.guard("file_read", {"file_path": "a.txt", "path": "b"})
        assert rejection is None
        assert params == {"file_path": "a.txt", "path": "b"}

    def test_remap_multiple_aliases(self, guard):
        """无歧义档可批量归一；歧义档（cmd）无 schema 不动。"""
        params, rejection = guard.guard("t", {"filename": "a", "filepath": "b", "cmd": "ls"})
        assert rejection is None
        assert params == {"file_path": "a", "filepath": "b", "cmd": "ls"}


class TestTruncatedJson:
    """截断 JSON：流被掐断时参数值是半截 JSON——能修则修，修不了拒绝执行。"""

    def test_repair_unbalanced_brackets(self, guard):
        params, rejection = guard.guard("t", {"content": '{"a": [1, 2'})
        assert rejection is None
        assert params["content"] == '{"a": [1, 2]}'

    def test_repair_unterminated_string(self, guard):
        params, rejection = guard.guard("t", {"content": '{"msg": "hello'})
        assert rejection is None
        assert params["content"] == '{"msg": "hello"}'

    def test_repair_trailing_comma(self, guard):
        params, rejection = guard.guard("t", {"content": '{"a": 1, "b": [1, 2,'})
        assert rejection is None
        import json

        assert json.loads(params["content"]) == {"a": 1, "b": [1, 2]}

    def test_valid_json_untouched(self, guard):
        params, rejection = guard.guard("t", {"content": '{"a": 1}'})
        assert rejection is None
        assert params["content"] == '{"a": 1}'

    def test_plain_text_untouched(self, guard):
        """非 JSON 形态的字符串（代码/正文）不碰。"""
        code = "def f():\n    return {1: 2"
        params, rejection = guard.guard("run_code", {"code": code})
        assert rejection is None
        assert params["code"] == code

    def test_unrepairable_truncation_rejects(self, guard):
        """修不了 → 拒绝执行并给出修复建议（不让破坏性工具拿半截参数跑）。"""
        bad = '{"a": [1, 2' + "x" * 5
        # 制造不可配平：引号内含未转义结构性字符并截断——直接用一个必然修不好的输入
        params, rejection = guard.guard("file_write", {"content": '{"path": "x"', "file_path": "f"})
        if rejection is None:
            params, rejection = guard.guard("file_write", {"content": '{"a": '})
        assert rejection is not None
        assert rejection["success"] is False
        assert "param_guard" in rejection
        assert rejection["param_guard"]["issues"]
        assert rejection["param_guard"]["suggestions"]


class TestInstallSemantics:
    """装配语义对齐熔断器：默认不装，显式 install（幂等），可逆。"""

    def test_default_not_installed(self):
        from neurova.security.tool_param_guard import get_param_guard

        assert get_param_guard() is None

    def test_install_uninstall_roundtrip(self):
        from neurova.security import tool_param_guard as mpg

        mpg.uninstall_tool_param_guard(force=True)
        handle = mpg.install_tool_param_guard()
        try:
            assert mpg.get_param_guard() is not None
            # 幂等
            again = mpg.install_tool_param_guard()
            assert again is handle
        finally:
            mpg.uninstall_tool_param_guard()
        assert mpg.get_param_guard() is None

    def test_policy_denial_recognition(self, guard):
        """param_guard 拒绝 = 决策不是后端故障——熔断器观察者不计数。"""
        from neurova.security.governance import is_policy_denial

        _, rejection = guard.guard("file_write", {"content": '{"a": '})
        assert is_policy_denial(rejection) is True
