# -*- coding: utf-8 -*-
"""静态门禁「未定义名称」这一格的常驻判据。

要防的形态（都在本仓真栽过，且整条 CI 就红在这一格）：

1. **注解用的名字没进命名空间**——`from __future__ import annotations` 让注解不求值，
   于是 `-> McpCaller` / `: ChannelMessage` 这类漏 import 在运行时彻底隐形，
   只有 pyflakes 看得见。它不是"风格问题"：任何 `typing.get_type_hints()`
   或函数内的类型分支一碰就 NameError。
2. **真打到运行时的未定义名**——`logger.warning(..., file_path)` 里的局部变量根本不存在，
   命中这条分支就是 NameError，日志与「已阻止」的结果一起丢掉。

判据不用"跑一遍 CI 看绿不绿"来证明：直接以本仓为准跑 pyflakes 取 `undefined name` 读数，
按**文件级**断言为零。这样任何文件重新长出未定义名都会指名道姓地红。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 门禁看的目录，与 scripts/ci_static_gate.py 的 CHECK_DIRS 同源取值
CHECK_DIRS = ("neurova", "scripts")


#: 端到端钉住子进程的写侧码页（§6-64）：只钉父端 `encoding` 是"半修"——子端仍按
#: `locale.getpreferredencoding()` 写字节，父端按 UTF-8 解，读数就会被静默改写。
#: 由 tests/unit/ci/test_subprocessTextEncodingRatchet.py 的半修计数常驻核对。
def _utf8ChildEnv() -> dict:
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def undefinedNameReadings() -> list[str]:
    """跑一遍 pyflakes，逐行交回 `undefined name` 读数。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *CHECK_DIRS],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8ChildEnv(),
    )
    return [line for line in (proc.stdout or "").splitlines() if "undefined name" in line]


class TestStaticGateUndefinedNamesIsClean:
    def test_noUndefinedNameAnywhere(self):
        """整个门禁面零未定义名——这条就是 CI static-gate 那一格的本地镜像。"""
        try:
            import pyflakes  # noqa: F401
        except ImportError:  # pragma: no cover - 精简环境缺工具时明确跳过，不伪装成绿
            pytest.skip("未安装 pyflakes，无法取数（CI 的 static-gate 腿会自己装）")
        readings = undefinedNameReadings()
        assert readings == [], "存在未定义名称：\n" + "\n".join(readings)


class TestAnnotationNamesAreImported:
    """把"注解名字漏 import"单独钉住——它是被 `from __future__ import annotations` 藏起来的那一类。"""

    def test_mcpCallerAnnotationIsResolvable(self):
        from neurova.api.endpoints import mcp_server_api

        # 注解在模块命名空间里真的取得到（过去这里只有函数内惰性 import）
        assert mcp_server_api.McpCaller.__name__ == "McpCaller"

    def test_channelMessageAnnotationIsResolvable(self):
        from neurova.api.endpoints import channels

        assert channels.ChannelMessage.__name__ == "ChannelMessage"

    def test_knowledgeFactsTupleAnnotationIsResolvable(self):
        from neurova.knowledge.foundation import knowledge_facts

        assert knowledge_facts.Tuple is not None

    def test_providerCompatAnyAnnotationIsResolvable(self):
        from neurova.llm import provider_compat

        assert provider_compat.Any is not None


class TestFileOperationDenialNamesEveryPathValue:
    """无文件沙箱后端时那条"降级为阻止"的日志：过去引用未定义的 `file_path`，一进必 NameError。

    判据走**真链路**：让治理策略给出 SANDBOX + 无命令 + 有路径值，经
    `ToolExecutor._governance_precheck` 打到返回，断言日志把每条路径值都点出来。
    """

    def test_logNamesAllPathValues(self, monkeypatch, caplog):
        import asyncio
        import logging

        import neurova.security.governance as governance_module
        from neurova.tool_executor import ToolExecutor

        class _AlwaysAvailableBackend:
            @staticmethod
            def available():
                return True

        monkeypatch.setitem(
            governance_module._ENFORCED_SANDBOX_BACKENDS, "probe", _AlwaysAvailableBackend
        )

        policy = governance_module.GovernancePolicy()
        policy.ask_on_high = False  # HIGH → SANDBOX 而不是 ASK
        monkeypatch.setattr(
            governance_module, "get_governance", lambda: policy, raising=True
        )

        executor = ToolExecutor.__new__(ToolExecutor)  # 只跑这一段，不装配 agent
        executor._builtin_dispatch = {}
        executor._audit_governance = lambda *a, **k: None
        executor._agent = None
        # 身份取数走生产装配点（`_agent_identity` 从 agent.config 读），这里给同一形状的空身份
        executor._agent_identity = lambda: (None, "default")

        params = {"file_path": "/etc/passwd", "path": "/root/.ssh/id_rsa"}
        with caplog.at_level(logging.WARNING, logger="neurova.tool_executor"):
            verdict = asyncio.run(executor._governance_precheck("file_write", params))

        assert verdict is not None, "SANDBOX + 文件类必须降级为阻止，不能放行"
        assert verdict["success"] is False
        messages = " ".join(r.getMessage() for r in caplog.records)
        # 两条路径值都在日志里——过去连日志本身都会 NameError 掉
        assert "/etc/passwd" in messages
        assert "/root/.ssh/id_rsa" in messages
        assert "file_write" in messages


class TestGateScriptReadsTheSameDirs:
    """门禁脚本的目录清单与本判据同源——改一处而不改另一处就会漏掉半边。"""

    def test_checkDirsMatch(self):
        source = (REPO_ROOT / "scripts" / "ci_static_gate.py").read_text(encoding="utf-8")
        match = re.search(r"^CHECK_DIRS = \[(.*?)\]", source, re.M | re.S)
        assert match, "ci_static_gate.py 里找不到 CHECK_DIRS"
        declared = tuple(re.findall(r'"([^"]+)"', match.group(1)))
        assert declared == CHECK_DIRS
