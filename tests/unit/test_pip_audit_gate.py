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

#: `python <gate> --help` 的预算唯一出处（此前无 `timeout=`＝无界等待）。取低于全局 30s 的
#: 20s：先到点的应当是子进程那条诚实的 TimeoutExpired，而不是 thread 法的全局墙——后者会把
#: 整场跑测连报告一起带走（§6-402 批 K 口径）。
PROBE_WALL_S = 20
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
            timeout=PROBE_WALL_S,
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
            # 构建 cnb-qr5-1k4bor0bt 的 dependency-audit 腿实测原文：pip-audit 的
            # `OsvService` 把 requests 的连接异常收成自家 `ConnectionError`，
            # 打给 `_cli` 后印成这两行（逐字取自本次 CI 日志）。
            "ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed\n"
            "ERROR:pip_audit._cli:Tip: your network may be blocking this service. "
            "Try another service with `-s SERVICE`",
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

    def test_connection_advice_does_not_outrank_a_real_verdict(self, gate):
        """反向控制：连接失败建议**不得**压过一条已成立的裁决。

        两形态混流是真实场景（重试会把上一轮输出累积进同一段文本）：
        `_cli` 的提示句与 `Found N` 裁决同时出现时，判据只认后者。
        """
        mixed = (
            "ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed\n"
            "ERROR:pip_audit._cli:Tip: your network may be blocking this service. "
            "Try another service with `-s SERVICE`\n"
            "Found 1 known vulnerability in 1 package"
        )
        assert not gate.isInfrastructureFailure(1, mixed), (
            "连接建议句压过了已成立的裁决——重试一条已成立的裁决是空转"
        )


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
                                          "--attempts", "2",
                                          "--verdict-channel", "live"])
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
                                          "--attempts", "3",
                                          "--verdict-channel", "live"])
        assert gate.main() == 1
        assert len(calls) == 1, (
            f"「找到漏洞」被重试了 {len(calls)} 次——重试一条已成立的裁决是空转"
        )

    def test_connection_failure_recovers_with_retry(self, gate, monkeypatch):
        """CI 实测形态走完整 `main()`：抖动一次 → 第二次拿到裁决 → 退出 0。

        这条钉的是**行为**而不只是分类函数：构建 `cnb-qr5-1k4bor0bt` 的红，
        成因就是第一次调用撞上 OSV 连接失败、被当成「裁决已成立」直接判红，
        于是第二次机会根本不存在。修后必须能救回这一轮。
        """
        sequence = [
            (1, "ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed\n"
                "ERROR:pip_audit._cli:Tip: your network may be blocking this service. "
                "Try another service with `-s SERVICE`"),
            (0, "No known vulnerabilities found"),
        ]

        def fakeRunOnce(*_a, **_k):
            return sequence.pop(0)

        monkeypatch.setattr(gate, "runOnce", fakeRunOnce)
        monkeypatch.setattr(gate, "RETRY_BACKOFF", 0.0)
        monkeypatch.setattr(sys, "argv", [str(GATE), "-r", "requirements-ci.lock",
                                          "--attempts", "3",
                                          "--verdict-channel", "live"])
        assert gate.main() == 0, (
            "OSV 连接失败没被判成基础设施错误——它直接退了 1（裁决已成立），"
            "于是这一次网络抖动就是阻塞红灯，而它与提交内容无关"
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
                                          "--attempts", "3",
                                          "--verdict-channel", "live"])
        assert gate.main() == 0


class TestVerdictChannelDoesNotDependOnLiveOsv:
    """裁决通路必须有离线分支（Issue #357）。

    ## 为什么要有这道守卫

    构建 `cnb-a99-1k4bpgeim` 的 dependency-audit 腿红在
    `audit full runtime locked set`（`requirements-full.lock`）：

        ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed
        [pip-audit] ⚠️ 第 1 次为基础设施错误（裁决未成立），5s 后重试（共 3 次）
        [pip-audit] ❌ requirements-full.lock: 3 次尝试均未取得裁决……
        Finished, code: 2

    上一条修复（`ae48d45b`）只把这条红的**定性**改诚实了：它不再冒充
    「裁决已成立」，而是响亮地说「本轮没查成」。但它**没有拆掉那条外部依赖**
    ——`api.osv.dev` 一旦在 runner 上被拦，门禁依旧阻塞合并，而它与提交内容
    一个字的关系都没有。同一构建里 `requirements-ci.lock`（85 包）过了、
    `requirements-full.lock`（169 包）没过，正是因为后者要发 169 次 POST，
    长链路上必然撞上一次抖动。

    ## 修法：把 Python 锁这一路也接上**离线裁决通路**

    同仓 `scripts/ci/osv_audit.py` 早在 2026-09-22 就用离线库消灭过同形形态
    （其顶栏「裁决不依赖远端可实时到达」一节），A/B 实测：把 `api.osv.dev`
    解析到必挂 IP + 清空缓存 → 线上口径 3/3 红、离线口径 3/3 全绿。
    Python 这一路当时漏在体系外，本单补齐：

    * 离线库落点与 OSV 那一路**同一份缓存**（`~/.cache/osv-scalibr/PyPI/all.zip`），
      CI 两侧已挂的卷直接复用，不新造第二套缓存口径（AGENTS.md 修复教义第 6 条）；
    * 裁决通路收口在一处：缓存齐 → 走离线库（不再依赖 `api.osv.dev`）；
      缓存不齐 → 回退直连并**点名缺哪一份**；
    * 放行标准不变：允许清单仍是 `scripts/ci/osv-allowlist.toml`，
      退出码语义仍是 0/1/2。

    本守卫钉四件事（缺一条即红）：

    1. 门禁脚本暴露 `resolveVerdictChannel()`，且它按**缓存是否齐备**给不同结论；
    2. 离线分支的命令**不含**任何指向 `api.osv.dev` 的实时查询；
    3. 两侧 CI 配置都声明了 PyPI 离线库的预取步骤；
    4. 缓存不齐时回退直连**并点名**（不许静默直连、也不许静默判红）。
    """

    def test_gate_exposes_a_verdict_channel_resolver(self, gate):
        assert hasattr(gate, "resolveVerdictChannel"), (
            "pip_audit_gate.py 没有裁决通路解析入口——Python 锁这一路仍只能直连 "
            "api.osv.dev，一次网络抖动就是阻塞红灯（本单要消灭的形态）"
        )

    def test_offline_channel_is_chosen_when_cache_is_present(self, gate, tmp_path, monkeypatch):
        """缓存齐 → 走离线；且离线命令不查远端。"""
        cache_root = tmp_path / "osv-scalibr"
        (cache_root / "PyPI").mkdir(parents=True)
        (cache_root / "PyPI" / "all.zip").write_bytes(b"stub")
        monkeypatch.setattr(gate, "OSV_DB_CACHE", cache_root)

        offline, problems = gate.resolveVerdictChannel()
        assert offline is True, (
            f"离线库在场却仍选了直连通路（问题清单：{problems}）——"
            "裁决又绑回 api.osv.dev 的实时可达性"
        )
        assert problems == []

        command = gate.buildOfflineCommand("requirements-ci.lock", binary="/tmp/osv-scanner")
        joined = " ".join(command)
        assert "api.osv.dev" not in joined, f"离线命令里仍有实时查询地址: {joined}"
        assert "--offline" in command and "--offline-vulnerabilities" in command, (
            f"离线命令缺成对的离线 flag（缺一即退 127，反而伪装成基础设施故障）: {joined}"
        )

    def test_live_fallback_names_what_is_missing(self, gate, tmp_path, monkeypatch):
        """缓存不齐 → 回退直连，**并点名缺哪一份**（不许静默回退）。"""
        cache_root = tmp_path / "osv-scalibr-empty"
        monkeypatch.setattr(gate, "OSV_DB_CACHE", cache_root)

        offline, problems = gate.resolveVerdictChannel()
        assert offline is False, "缓存缺失却仍判「可走离线」——离线命令会退 127"
        assert problems, "缓存缺失却没有任何问题清单——回退是静默的，读日志的人无从自查"
        assert any("PyPI" in item for item in problems), (
            f"问题清单没点名缺的是哪个生态的库: {problems}"
        )

    def test_cache_root_is_the_same_source_as_the_osv_gate(self, gate):
        """离线库落点必须与 `osv_audit.py` **同值**——不新造第二套缓存口径。

        两处各写一份 `~/.cache/osv-scalibr` 就是第二份定义（教义第 6 条）：
        预取落到 A 处、门禁读 B 处时，门禁会报「离线库缺失」，而库其实就在旁边。
        判据直接比对两个模块的常量，而不是在注释里声称一致。
        """
        osv = gate._scannerModule()
        assert Path(gate.OSV_DB_CACHE) == Path(osv.OSV_DB_CACHE), (
            f"缓存落点分叉：pip_audit_gate={gate.OSV_DB_CACHE} "
            f"osv_audit={osv.OSV_DB_CACHE}"
        )

    def test_pypi_is_declared_in_the_shared_offline_scope(self, gate):
        """PyPI 生态必须登记在 `osv_audit.py` 的 `OFFLINE_DB_SCOPE` 里。

        预取侧按这张表推「要下哪些生态的库」，门禁侧按 `OFFLINE_ECOSYSTEM` 读。
        两处各写一份就会「预取到 A、门禁读 B」。
        """
        osv = gate._scannerModule()
        scopes = set(osv.OFFLINE_DB_SCOPE.values())
        assert gate.OFFLINE_ECOSYSTEM in scopes, (
            f"离线库归属表里没有 {gate.OFFLINE_ECOSYSTEM}——预取不会为它落库，"
            f"而门禁却在等它（现存生态：{sorted(scopes)}）"
        )

    def test_both_sides_prefetch_the_pypi_offline_database(self):
        """两侧 CI 都必须声明 PyPI 离线库预取——否则离线通路永远空转。"""
        for path in (CNB, GHW):
            text = io.open(path, encoding="utf-8").read()
            assert "PyPI" in text, (
                f"{path.name} 未声明 PyPI 离线库——Python 锁这一路的离线通路永远空转，"
                "门禁照旧绑在 api.osv.dev 的实时可达性上"
            )
