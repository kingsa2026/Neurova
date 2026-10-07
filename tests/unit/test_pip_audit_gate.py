# -*- coding: utf-8 -*-
"""pip-audit 门禁包装的常驻判据（Issue #354）。

## 为什么要有这道守卫

`dependency-audit` 腿红在第二段（构建 `cnb-tec-1k4b4771b` 的 `stage-2`）：

    $ python -m pip_audit -r requirements-full.lock --progress-spinner off
    requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443):
        Read timed out. (read timeout=15)
    Finished, code: 1, duration: 46.6s

一次读超时 = 退出码 1 = 阻塞红灯，而那条红与提交内容一个字的关系都没有。
本仓在 `scripts/ci/osv_audit.py` 里早已消灭过同形形态（见其顶栏「裁决不依赖远端
可实时到达」），只是当时只收口了 OSV 那一路。故修法不是「重跑一次」，而是**把
pip-audit 这一路也收进口径**：`scripts/ci/pip_audit_gate.py`。

本守卫钉四件事（缺一条即红）：

1. **两侧都走包装脚本**：`.cnb.yml` 与 `.github/workflows/ci.yml` 里不得再有
   `python -m pip_audit` 直调——直调就是「一次读超时 = 红灯」的形态。反向锁：
   真的会认直调（否则上面这条恒真）。
2. **换 OSV 库 + 给足超时**：`--vulnerability-service osv` 与 `--timeout` 必须在
   拼命令的单一落点里；`--timeout` 不得退回 pip-audit 的 15s 内置默认。
3. **只对基础设施错误重试**：读超时重试、「找到漏洞」立即判红。判据取真函数
   `isInfrastructureFailure()` 的输入输出对照，不扫源码形态——**裁决已成立时
   即便输出里夹着 timeout 字样，也不得重试**（重试一条已成立的裁决，等于把判据
   交给重试次数）。
4. **退出码语义与 OSV 那一路同源**：0/1/2，且 2 是「本轮没查成」而非「通过」。

可证伪路径（逐条）：把任一侧改回直调 → 转红；把 `--vulnerability-service` 删掉 →
转红；把 `isInfrastructureFailure` 改成恒 True → 「有漏洞」那条转红。
"""

from __future__ import annotations

import io
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "ci" / "pip_audit_gate.py"
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

#: 直调 pip-audit 的形态（本守卫要拦的那一种）。`-m pip_audit` 是唯一入口写法，
#: 落到 `pip-audit` 可执行文件是另一种拼法，也一并拦。
_DIRECT_INVOCATION = re.compile(r"\bpython\s+-m\s+pip_audit\b")


def _loadGate():
    """按路径加载包装脚本（它不是包内模块，故不用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("pip_audit_gate_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    assert GATE.is_file(), f"门禁包装脚本缺失: {GATE}——dependency-audit 退回直调形态"
    return _loadGate()


class TestBothSidesGoThroughTheGate:
    """两侧都经包装脚本调用；**任何一处直调**即红。"""

    def test_cnb_calls_the_gate(self):
        text = io.open(CNB, encoding="utf-8").read()
        assert "scripts/ci/pip_audit_gate.py -r requirements-ci.lock" in text
        assert "scripts/ci/pip_audit_gate.py -r requirements-full.lock" in text

    def test_github_calls_the_gate(self):
        text = io.open(GHW, encoding="utf-8").read()
        assert "scripts/ci/pip_audit_gate.py -r requirements-ci.lock" in text
        assert "scripts/ci/pip_audit_gate.py -r requirements-full.lock" in text

    def test_no_side_invokes_pip_audit_directly(self):
        """反向锁：直调形态必须被拦——否则上面两条只是"碰巧没写直调"。"""
        offenders = []
        for path in (CNB, GHW):
            for number, line in enumerate(io.open(path, encoding="utf-8"), 1):
                if _DIRECT_INVOCATION.search(line.split("#", 1)[0]):
                    offenders.append(f"{path.name}:{number}")
        assert not offenders, (
            f"以下位置仍在直调 pip-audit: {offenders}\n"
            "直调时 pypi.org 的一次 15s 读超时就是阻塞红灯（实测构建 "
            "cnb-tec-1k4b4771b 的 stage-2），而那条红与提交内容无关。"
            "统一走 scripts/ci/pip_audit_gate.py。"
        )

    def test_detector_is_not_vacuous(self):
        """反向控制：检出器真的认得出直调形态。"""
        assert _DIRECT_INVOCATION.search("python -m pip_audit -r requirements-ci.lock")
        assert not _DIRECT_INVOCATION.search(
            "python scripts/ci/pip_audit_gate.py -r requirements-ci.lock"
        )


class TestCommandContract:
    """拼命令的单一落点必须换库、给足超时。"""

    def test_uses_the_osv_service(self, gate):
        cmd = gate.buildCommand("requirements-ci.lock", 60)
        assert "--vulnerability-service" in cmd, (
            "包装脚本未指定漏洞库服务——pip-audit 会退回 `pypi`（每包一次 "
            "pypi.org 往返），这正是读超时红的那条路"
        )
        assert cmd[cmd.index("--vulnerability-service") + 1] == "osv"

    def test_timeout_is_raised_above_the_builtin_default(self, gate):
        """pip-audit 内置默认 15s；包装脚本的默认必须显著高于它。

        判据取「大于内置默认」而不是某个具体秒数：具体秒数会随机器与负载漂移，
        而「不得等于那个把一次网络抖动变成红灯的值」是结构性的。
        """
        cmd = gate.buildCommand("requirements-full.lock", gate.DEFAULT_TIMEOUT)
        value = int(cmd[cmd.index("--timeout") + 1])
        assert value > 15, (
            f"--timeout 给的是 {value}s，未高于 pip-audit 的 15s 内置默认——"
            "一次批量查询的耗时本就长于它，等于把网络抖动编码成阻塞红灯"
        )

    def test_cli_default_is_not_the_builtin(self, gate):
        """CLI 声明的默认值也必须是「高于内置默认」，不能只改拼命令那一层。"""
        # 直接查 argparse 声明的默认值（避免与 main 的实现细节耦合）
        proc = subprocess.run(
            [sys.executable, str(GATE), "--help"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        assert proc.returncode == 0, proc.stderr
        match = re.search(r"--timeout[^\n]*默认 (\d+)", proc.stdout)
        assert match is not None, f"--help 里读不到 --timeout 的默认值:\n{proc.stdout}"
        assert int(match.group(1)) > 15, (
            f"CLI 的 --timeout 默认是 {match.group(1)}s——退回 pip-audit 的 15s 内置默认"
        )


class TestVerdictSemantics:
    """重试只对「没查成」；「查成了、有漏洞」立即判红。"""

    @pytest.mark.parametrize(
        "output",
        [
            "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', "
            "port=443): Read timed out. (read timeout=15)",
            "socket.gaierror: Temporary failure in name resolution",
            "ConnectionResetError: [Errno 104] Connection reset by peer",
            "HTTPError: 503 Service Unavailable",
        ],
    )
    def test_infrastructure_forms_are_retryable(self, gate, output):
        assert gate.isInfrastructureFailure(1, output), (
            f"这一形态是「没查成」（可重试），但检出器不认：{output[:60]}"
        )

    @pytest.mark.parametrize(
        "output",
        [
            "Found 1 known vulnerability in 1 package",
            "Found 2 known vulnerabilities in 1 package",
        ],
    )
    def test_vulnerability_forms_are_not_retryable(self, gate, output):
        assert not gate.isInfrastructureFailure(1, output), (
            f"这一形态是「裁决已成立」（不许重试），但检出器把它当抖动：{output}"
        )

    def test_verdict_wins_over_residual_timeout_noise(self, gate):
        """**本守卫的核心反向控制**：裁决与抖动同时出现时不重试。

        重试路径会把上一轮的输出累积/交错，形态是「先一句 timeout、后一句
        Found N」。按形态只认抖动就会把一条**已成立的裁决**重试三遍，
        最后照旧判红——只是慢了，而判据已经交给了重试次数。
        """
        mixed = "Read timed out\n... retry ...\nFound 1 known vulnerability in 1 package"
        assert not gate.isInfrastructureFailure(1, mixed), (
            "裁决已成立却仍被判为可重试——重试一条已成立的裁决，"
            "等于把判据交给重试次数"
        )

    def test_clean_exit_is_never_a_failure(self, gate):
        assert not gate.isInfrastructureFailure(0, "No known vulnerabilities found")


class TestExitCodeVocabularyMatchesTheOsvGate:
    """退出码语义与 `scripts/ci/osv_audit.py` 同源（不新造第二套词汇）。"""

    def test_gate_declares_the_shared_vocabulary(self, gate):
        doc = gate.__doc__ or ""
        for phrase in ("0 = 无未允许的漏洞", "1 = 有未允许的漏洞", "2 = 基础设施错误"):
            assert phrase in doc, f"包装脚本未声明与 OSV 门禁同源的退出码词汇: {phrase}"

    def test_retries_exhausted_yields_infrastructure_code(self, gate, monkeypatch):
        """重试耗尽 → 退出 2（不是 0、也不是 1）：「没查成」必须与两种裁决可分辨。"""
        monkeypatch.setattr(gate, "runOnce", lambda *_a, **_k: (
            1, "requests.exceptions.ReadTimeout: Read timed out"))
        monkeypatch.setattr(gate, "RETRY_BACKOFF", 0.0)
        monkeypatch.setattr(sys, "argv", [str(GATE), "-r", "requirements-ci.lock",
                                          "--attempts", "2"])
        assert gate.main() == 2, "重试耗尽应退 2（基础设施错误），不得退 0 或 1"

    def test_established_verdict_exits_one_without_retry(self, gate, monkeypatch):
        """裁决已成立 → 退出 1，且**只调用一次**（不重试）。"""
        calls = []

        def fakeRunOnce(*_a, **_k):
            calls.append(1)
            return 1, "Found 1 known vulnerability in 1 package"

        monkeypatch.setattr(gate, "runOnce", fakeRunOnce)
        monkeypatch.setattr(gate, "RETRY_BACKOFF", 0.0)
        monkeypatch.setattr(sys, "argv", [str(GATE), "-r", "requirements-ci.lock",
                                          "--attempts", "3"])
        assert gate.main() == 1
        assert len(calls) == 1, (
            f"「找到漏洞」被重试了 {len(calls)} 次——重试一条已成立的裁决是空转"
        )

    def test_transient_failure_recovers_with_retry(self, gate, monkeypatch):
        """抖动后恢复 → 退出 0（重试真的救回了这一轮）。"""
        sequence = [
            (1, "requests.exceptions.ReadTimeout: Read timed out"),
            (0, "No known vulnerabilities found"),
        ]

        def fakeRunOnce(*_a, **_k):
            return sequence.pop(0)

        monkeypatch.setattr(gate, "runOnce", fakeRunOnce)
        monkeypatch.setattr(gate, "RETRY_BACKOFF", 0.0)
        monkeypatch.setattr(sys, "argv", [str(GATE), "-r", "requirements-ci.lock",
                                          "--attempts", "3"])
        assert gate.main() == 0
