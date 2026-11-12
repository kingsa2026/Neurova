"""工具大输出 OutputRef 装配接线判据（候选 C4，2026-11-05 对比报告）

断点：`agent/tool_output_ref.py` 机制完备（咽喉 maybe_output_ref 已接线、
失败不折叠、诚实降级），装配器 `ensure_output_ref_installed_from_env` 也已实现，
但 **全仓零调用方**——其 docstring 自称「应用启动时（app.py lifespan）调用」，
实际 app.py 没有这一行：本仓自己的文档-代码断层（与 KWeaver 对比 §6.2 清单
同形态）。同时 install 与 env-installer 两处 docstring 对默认口径互相矛盾
（「默认不安装」vs「默认开启」）——本次一并钉死口径：库级默认不自动安装；
应用 lifespan 按 W1-4 装配默认开启，env NEUROVA_TOOL_OUTPUT_REF=0 逃生。

判据：
- AST 接线守卫：app.py 的 lifespan 路径内必须存在装配调用（沿
  test_agentCreateDoesNotLogAtError 的 AST 形态判先例）；
- 行为面：env 缺省 → 装配就位（大输出折叠为引用）；env=0 → 卸载（透传）；
  失败结果任何形态都不折叠（诊断正文保住）。
"""

import ast
import pathlib
from unittest import mock

import pytest
from tests.ast_scan import parseSource

APP_PY = pathlib.Path(__file__).resolve().parents[3] / "neurova" / "api" / "app.py"


def test_app_lifespan_calls_output_ref_installer():
    """AST 接线守卫：app.py 必须调用 ensure_output_ref_installed_from_env。"""
    tree = parseSource(APP_PY.read_text(encoding="utf-8"), str(APP_PY))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "ensure_output_ref_installed_from_env")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "ensure_output_ref_installed_from_env")
        )
    ]
    assert calls, "app.py 未调用 ensure_output_ref_installed_from_env——装配缺位（C4 断点未闭环）"


@pytest.fixture(autouse=True)
def _reset_handle(monkeypatch):
    import neurova.agent.tool_output_ref as ref

    monkeypatch.setattr(ref, "_global_handle", None)
    yield
    ref._global_handle = None


def test_env_default_installs():
    import neurova.agent.tool_output_ref as ref

    with mock.patch.dict("os.environ", {}, clear=False):
        ref.ensure_output_ref_installed_from_env()
    assert ref.get_installed_output_ref() is not None, "env 缺省必须装配（W1-4 默认开启）"


def test_env_zero_uninstalls():
    import neurova.agent.tool_output_ref as ref

    ref.install_tool_output_ref()
    with mock.patch.dict("os.environ", {"NEUROVA_TOOL_OUTPUT_REF": "0"}):
        ref.ensure_output_ref_installed_from_env()
    assert ref.get_installed_output_ref() is None, "env=0 必须卸载（恢复透传语义）"


def test_uninstalled_passthrough():
    import neurova.agent.tool_output_ref as ref

    ref._global_handle = None
    big = {"success": True, "output": "x" * 20000}
    out = ref.maybe_output_ref("exec_command", big, "/tmp", success=True)
    assert out is big, "未装配时必须恒透传（零行为变化）"


def test_installed_folds_large_success_result(tmp_path):
    import neurova.agent.tool_output_ref as ref

    ref.install_tool_output_ref(max_chars=1000)
    big = {"success": True, "output": "y" * 5000}
    out = ref.maybe_output_ref("exec_command", big, tmp_path, success=True)
    assert "output_ref" in out and out["output_ref"]["size_bytes"] > 1000
    assert out["output_ref"]["preview"]


def test_failure_result_never_folded(tmp_path):
    """失败正文即诊断本体——任何形态都不折叠（咽喉纪律，防诊断蒸发）。"""
    import neurova.agent.tool_output_ref as ref

    ref.install_tool_output_ref(max_chars=100)
    failed = {"success": False, "error": "e" * 5000, "stderr": "s" * 5000}
    out = ref.maybe_output_ref("exec_command", failed, tmp_path, success=False)
    assert out is failed, "失败结果不得折叠"
