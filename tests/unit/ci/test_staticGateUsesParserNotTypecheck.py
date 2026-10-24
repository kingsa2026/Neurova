# -*- coding: utf-8 -*-
"""静态门禁的"未定义名称"判据不许把**注解专用**的名字当成缺陷。

为什么要有这一档：CI 的 static-gate 腿曾报出 6 处 F821，其中 5 处是**注解**里的名字——
实体在函数体内懒加载（`McpCaller` 就是：模块级导入会拉 `neurova.agent` 包 __init__ →
`tool_executor` 的循环，AGENTS.md §3），注解却是模块级解析的。把它们"修"成模块级导入
会把生产改坏，删注解则丢掉 pyflakes 能读的事实——两条都是把报错挪走（教义第 1、2 条）。

本档钉的是**判据的形状**，三层：

① 注解专用名不报（含 `from __future__ import annotations` 之后的形参注解）；
② 真·未定义名照旧报（拼错的、写错形参的、函数体里读一个本文件从未绑定的名字）；
③ 反向自证：把"文件里别处 import 过同名名字"当成豁免证的实现，会被本档当场咬到——
   豁免只对**注解位置**成立，函数体里读仍未绑定的名字不许借这条通道溜过去。
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts" / "ci_static_gate.py"

# 本档要起子进程（把探针交给真门禁判），判据成本也是回归面：墙钟宽到机器慢也不判死
# （同 `test_moduleTopLevelShadowing.py` 的口径）。`pytest-timeout` 走全局 30s，
# 这一档按子进程数 × 单次门禁成本留余量。
pytestmark = pytest.mark.timeout(120)


def _gateUndefined(source: str, tmp_path: pathlib.Path) -> list[str]:
    """把一段源码交给**真门禁**判，收回它点名的那几行（不另写一份判据）。"""
    target = tmp_path / "probe_pkg"
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text("", encoding="utf-8")
    (target / "probe.py").write_text(source, encoding="utf-8")

    code = (
        "import sys, json;"
        "sys.path.insert(0, %r);"
        "from scripts.ci_static_gate import undefinedNamesIn;"
        "print(json.dumps(undefinedNamesIn(%r)))"
        % (str(tmp_path), str(target / "probe.py"))
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )
    if done.returncode != 0:
        raise AssertionError("门禁调用失败：" + (done.stderr or done.stdout)[-400:])
    import json

    return json.loads(done.stdout)


class TestAnnotationOnlyNamesAreNotDefects:
    def testLazilyImportedBodyLocalNameUsedInAnnotationIsAccepted(self, tmp_path):
        """实体在函数体内导入、名字只出现在注解里 —— 这是循环导入的正解，不许报。"""
        source = (
            "from __future__ import annotations\n"
            "\n"
            "def callerPrincipal(current_user) -> McpCaller:\n"
            "    from neurova.tool_layers.mcp_server import McpCaller\n"
            "    return McpCaller(userId=str(current_user))\n"
        )
        assert _gateUndefined(source, tmp_path) == []

    def testAnnotationNameImportedOnlyInASiblingScopeIsAccepted(self, tmp_path):
        """名字在文件另一处绑过、只在本处注解里出现 —— 形参注解那一面与上一条同一判据。

        实体落点（函数体内导入）与时序（注解在 def 时求值）分属两问：本档钉的是判据只看
        「这个名字在文件里绑没绑过」，不看绑定在哪个作用域——名字绑过就不算"未定义"。
        """
        source = (
            "from __future__ import annotations\n"
            "\n"
            "def _caller() -> dict:\n"
            "    from neurova.tool_layers.mcp_server import McpCaller\n"
            "    return {}\n"
            "\n"
            "def callerPrincipal(current_user) -> McpCaller:\n"
            "    return McpCaller(userId=str(current_user))\n"
        )
        assert _gateUndefined(source, tmp_path) == []


class TestRealUndefinedNamesStillTrip:
    def testPhantomVariableInTheFunctionBodyIsReported(self, tmp_path):
        """函数体里读一个本文件从未绑定的名字 —— 这是真缺陷（NameError 隐患），必须报。"""
        source = (
            "import logging\n"
            "\n"
            "logger = logging.getLogger(__name__)\n"
            "\n"
            "def deny():\n"
            "    return {\"error\": \"blocked: \" + file_path}\n"
        )
        hits = _gateUndefined(source, tmp_path)
        assert any("file_path" in line for line in hits), hits

    def testMisspelledAnnotationIsReported(self, tmp_path):
        """注解里拼错的名字照旧红 —— 豁免的对象是"懒加载通道"，不是"注解位置一律免检"。"""
        source = (
            "from __future__ import annotations\n"
            "\n"
            "def handler(seed) -> ChannleMessage:\n"
            "    return seed\n"
        )
        hits = _gateUndefined(source, tmp_path)
        assert any("ChannleMessage" in line for line in hits), hits


class TestGateIsWiredToTheParser:
    def testGateExposesTheUndefinedNameJudge(self):
        """门禁必须把判据做成可调用的函数，而不是埋在 subprocess 输出里数行。

        这是本档能咬住实现的前提：判据不可调用，就只能靠"CI 跑一遍看红绿"，
        那时谁也不知道它判的是语义还是字符串。
        """
        from scripts.ci_static_gate import undefinedNamesIn  # noqa: F401

    def testGateStillReportsThroughTheCiEntrypoint(self, tmp_path):
        """门禁入口仍是那一条命令（不新增第二条判据通道）。"""
        text = GATE.read_text(encoding="utf-8")
        assert "def check_pyflakes" in text
        assert "undefinedNamesIn(" in text, "check_pyflakes 没有走被判据钉住的那个函数"
        assert ast.parse(text)  # 语法自检：别让本档在门禁坏掉时还绿着
