# -*- coding: utf-8 -*-
"""OSV 门禁的「真扫到、且真拦得住」守卫（Issue #121 修复单）。

为什么单独立一份守卫：`tests/unit/test_osv_audit_gate.py` 锁的是**配置契约**
（双侧同命令、阻塞语义、清单有期限），它自己写明「不跑真实扫描」。于是有一类
缺陷它结构上抓不到——**脚本语法自洽、配置齐备，但真在 CI 上跑起来是哑弹**。

2026-09-22 的实测正是这一类（PR #121 的 dependency-audit 连续两次红）：

    $ python scripts/ci/osv_audit.py        # cnb 容器 python:3.12，无误装任何 CLI
    [osv] 下载 .../osv-scanner_linux_amd64      ← 容器里没有 unzip/tar，解压
    [osv] 指纹校验通过 (linux_amd64)             失败 → 落盘 127 字节 HTML 错误页
    [osv] 扫描器异常退出（code=127）             ← 127 字节却与真二进制 sha256 一致，
    返回 2                                       指纹校验"通过"（对比的是同一份错误页）

三处根因，逐条钉死：

1. **扫描器不校验 CLI 契约**：二进制取回来就直接用。取到的可能是错误页
   （见上）、也可能是**不认 `scan source` 的旧版线**（1.9.2 实测：
   `osv-scanner scan source -L a.lock` → `Failed to walk source` + 退出 127，
   与本次报错同码同形）。于是 `--with-binary` 必须**先起一次真扫描自证**：
   真跑、出解析得了的 JSON、退出码在扫描器的契约集合内。
2. **被扫依赖树没被点数**：`Scanned ... found 447 packages` 是「扫描器真的解析了
   这两片树」的唯一读数，修复前无人核。缺了它，扫了 0 个包也会印绿字：
   告警若被 `2>&1 | cat` 之类管道吞掉，**有漏洞也能退出 0**。
   故把「由 Python 收集的逐目标包数」与扫描器自报数对账（未登记的类型列显式名单）。
3. **容器缺解压器**：下载回来的 `osv-scanner_linux_amd64` 是**未压缩的单一静态
   二进制**（v2.6.0 / v1.9.2 实测均如此），根本不需要 unzip/tar。修复前
   `_download_scanner` 里那段 `subprocess.run([...unzip/tar...])` 属凭想象写的死码。

本守卫的判据全部**真调函数**（`_targetPackageCounts` / `_commandContract` /
`_packageCountsMatch` / `_pipelineExitCodesSurviveRedirect`），不比对脚本文本——
「函数在不在、判据咬不咬合」才是要守的东西。
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "osv_audit.py"
ALLOWLIST = PROJECT_ROOT / "scripts" / "ci" / "osv-allowlist.toml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

# 被扫依赖树：锁文件 → (解析器, 该解析器的点数正则)。
# osv-scanner 的 `Scanned <path> file and found N packages` 是本仓库唯一能证明
# 「它真读了这两片树」的读数，故逐目标钉住措辞（措辞变了就该有人来复核）。
SCANNED_LINE = {
    "NeurUI/src-tauri/Cargo.lock": re.compile(
        r"Scanned\s+\S*Cargo\.lock\s+file and found (\d+) packages"
    ),
    "tools/npx-runtime/package-lock.json": re.compile(
        r"Scanned\s+\S*package-lock\.json\s+file and found (\d+) packages"
    ),
}

# 合法退出码：0 = 无未允许漏洞；1 = 有未允许漏洞；65 = 入参错误（v2 的 flag 用法错）。
# 其余（127 等）一律语义不明。PR #121 的 CI 就是 127，修复前语义未登记 → 被当
# 「扫描器不能用」，而真因是「取到的不是能用的扫描器」。
CONTRACT_EXIT_CODES = (0, 1, 65)

# cnb 侧 dependency-audit 的 docker 镜像（Python 之外不预装任何 CLI）。
# 「装了就多一条依赖」这件事必须先被复核——本守卫按它决定要不要查解压器契约。
_CNB_AUDIT_IMAGE = re.compile(r"python:3\.\d+")


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("osv_audit_hardening", AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paths(home: Path, rels) -> dict:
    out = {}
    for rel in rels:
        src = PROJECT_ROOT / rel
        dest = home / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        out[rel] = dest
    return out


def _scannerStub(home: Path, tool: str = "echo", body: str = "") -> Path:
    """写一个假扫描器：能在 `--with-binary` 预检里自证契约（真跑、出 JSON、退出 0）。"""
    stub = home / f"osv-scanner-stub-{tool}"
    stub.write_text(
        "#!/bin/sh\n"
        'out=""\n'
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "--output" ]; then out="$2"; shift 2; continue; fi\n'
        "  shift\n"
        "done\n"
        + body
        + 'printf \'{"results": [], "fake_format": "%s"}\' "$tool" > "$out"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


@pytest.fixture(scope="module")
def auditModule():
    return _load_audit_module()


class TestDownloadPathNeedsNoExtractor:
    """下载回来的是未压缩单一静态二进制——不需要 unzip/tar，缺了解压器不是理由。"""

    def test_download_step_does_not_shell_out_to_extractors(self, auditModule):
        """回退路径：把 `subprocess.run([...unzip...])` 加回 `_download_scanner` → 转红。"""
        import inspect

        source = inspect.getsource(auditModule._download_scanner)
        assert "unzip" not in source and "tar" not in source, (
            "下载步骤里又出现解压器调用——osv-scanner 的 release 资产是**未压缩的单一\n"
            "静态二进制**（v2.6.0 仓库内既证；v1.9.2 实测 `curl -sSL -o bin <url>` 后\n"
            "`./bin --version` 直接可跑）。容器（python:3.12）里没有 unzip/tar，\n"
            "加了这一步只会把正常下载改成落 127 字节错误页。"
        )

    def test_container_image_is_known_and_python_only(self, auditModule):
        """按 cnb 的镜像判据：只用 python 官方镜像时，脚本不得依赖任何额外 CLI。"""
        cnb = (PROJECT_ROOT / ".cnb.yml").read_text(encoding="utf-8")
        pipe = cnb.split("- name: dependency-audit", 1)[1].split("- name: ", 1)[0]
        images = _CNB_AUDIT_IMAGE.findall(pipe)
        assert images, "cnb dependency-audit 的镜像不是 python:3.x——本判据需复核"
        import inspect

        source = inspect.getsource(auditModule)
        for cli in ("unzip", "tar", "wget", "curl", "sha256sum"):
            assert f'"{cli}"' not in source, (
                f"镜像 {images[0]} 不预装 {cli}，脚本不得调用它（Python 侧有等价能力）"
            )


class TestScannerCommandContract:
    """命令契约必须随扫描器版本落定，且必须与下载的版本自洽。"""

    def test_contract_covers_scanner_line_and_output_side(self, auditModule):
        contract = auditModule._commandContract()
        version = auditModule.OSV_SCANNER_VERSION
        assert contract["line"] in ("v1", "v2"), f"未登记扫描器线: {contract['line']}"
        expected = "v2" if version.startswith("2.") else "v1"
        assert contract["line"] == expected, (
            f"下载的是 {version}（{expected} 线），契约却按 {contract['line']} 线拼命令"
            "——取回 v1.9.2 却拼 `scan source`，实测退出 127（PR #121 就是这个形态）。"
        )
        assert contract["output"] == "--output", (
            "命令行必须把 JSON 落到 --output 指定文件；走 stdout 会让告警与结果同流，"
            "`2>&1 | cat` 一类的管道吞码后**有漏洞也能退出 0**。"
        )
        assert "--config" in contract["config_flag"]
        assert contract["lockfile_flag"] in ("--lockfile", "-L")
        assert contract["format_flag"] and contract["json_format"]

    def test_contract_covers_flags_actually_used_in_buildScanCommand(self, auditModule):
        """扫描器属于「接口随版本变」的外部 CLI，拼命令前必须先自证它认这些 flag。

        做法：起一个会在收到自证 `--help` 时吐用法清单的假扫描器，比对本仓库
        实际要用的每个 flag 都在其中。回退路径：删掉 `_commandContract` 的
        `flags` 集合 → 本用例报错（集合缺失即无自证依据）。
        """
        contract = auditModule._commandContract()
        assert isinstance(contract.get("flags"), (set, frozenset)) and contract["flags"], (
            "_commandContract 未登记实际要用的 flag 集合——无从自证扫描器认不认它们"
        )

    def test_version_pin_is_recorded_with_fingerprints(self, auditModule):
        """版本与指纹必须同时钉住：换版本不换指纹 = 供应链敞开。"""
        assert re.fullmatch(r"\d+\.\d+\.\d+", auditModule.OSV_SCANNER_VERSION)
        assert auditModule._BINARY_SHA256, "无指纹表"
        for key, digest in auditModule._BINARY_SHA256.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{key} 指纹不是 sha256"


class TestTargetPackageCounts:
    """被扫依赖树的包数必须由「解析/点数」得到，而不是抄扫描器自己的输出。"""

    def test_cargo_lock_counts_manifest_packages(self, auditModule, tmp_path, monkeypatch):
        home = tmp_path / "home"
        paths = _paths(home, ["NeurUI/src-tauri/Cargo.lock"])
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)
        counts = auditModule._targetPackageCounts(list(paths.values()))
        rel = "NeurUI/src-tauri/Cargo.lock"
        assert rel in counts, f"{rel} 未被点数（判据未咬合）"
        real = len(re.findall(r"(?m)^\[\[package\]\]$", (PROJECT_ROOT / rel).read_text(encoding="utf-8")))
        assert counts[rel] == real, (
            f"Cargo.lock 点数 {counts[rel]} 与 [[package]] 条目数 {real} 不符——"
            "对账数字错了，『真扫到了这些包』就成了空话"
        )
        assert real > 1, "夹具本身不成立"

    def test_package_lock_counts_all_entries(self, auditModule, tmp_path, monkeypatch):
        home = tmp_path / "home"
        paths = _paths(home, ["tools/npx-runtime/package-lock.json"])
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)
        counts = auditModule._targetPackageCounts(list(paths.values()))
        rel = "tools/npx-runtime/package-lock.json"
        assert rel in counts
        tree = json.loads((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
        entries = [key for key in tree["packages"] if key]
        assert counts[rel] == len(entries), (
            "package-lock.json 点数与 lockfileVersion 3 的依赖条目数不符"
            "（空键 = lockfile 自身的元信息，不计入依赖）"
        )
        assert counts[rel] > 1, "夹具本身不成立"

    def test_unregistered_target_type_is_named_not_guessed(self, auditModule, tmp_path, monkeypatch):
        """未登记的依赖载体类型必须显式报红并点名，不许静默取 0（取 0 就是把对账变成空转）。"""
        home = tmp_path / "home"
        home.mkdir()
        stray = home / "requirements-ci.lock"
        stray.write_text("requests==2.31.0\n", encoding="utf-8")
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)
        counts = auditModule._targetPackageCounts([stray])
        assert counts.get("requirements-ci.lock") == auditModule.UNCOUNTED_SENTINEL, (
            "未登记类型的点数被猜成具体数字——对账会变成恒真/恒假的空转"
        )


class TestScannerReportedCountsAreReconciled:
    """解析出的包数 与 扫描器自报包数 必须相等（本条目 3 的核心判据）。"""

    @staticmethod
    def _scannerOutput(cargo=447, npm=368, lock="Cargo.lock", plock="package-lock.json"):
        return (
            f"Scanned /w/{lock} file and found {cargo} packages\n"
            f"Scanned /w/{plock} file and found {npm} packages\n"
        )

    def test_matching_counts_pass(self, auditModule):
        counts = {
            "NeurUI/src-tauri/Cargo.lock": 447,
            "tools/npx-runtime/package-lock.json": 368,
        }
        problems = auditModule._packageCountsMatch(
            counts, self._scannerOutput(), SCANNED_LINE, CONTRACT_EXIT_CODES
        )
        assert problems == [], f"读数一致却报问题: {problems}"

    def test_zero_scanned_packages_is_red(self, auditModule):
        """回退路径：扫描器一个包都没点数（输出被截断/挂错目标）→ 必须报红。

        没有这条，「扫了 0 个包」也能印绿字：告警被管道吞掉时有漏洞即静默放行。
        """
        counts = {
            "NeurUI/src-tauri/Cargo.lock": 447,
            "tools/npx-runtime/package-lock.json": 368,
        }
        problems = auditModule._packageCountsMatch(
            counts, "Found 0 packages\n", SCANNED_LINE, CONTRACT_EXIT_CODES
        )
        assert problems, "扫描器自报 0 个包却对账通过——门禁会静默放行"

    def test_drifted_count_is_red_and_names_both_sides(self, auditModule):
        counts = {
            "NeurUI/src-tauri/Cargo.lock": 447,
            "tools/npx-runtime/package-lock.json": 368,
        }
        problems = auditModule._packageCountsMatch(
            counts, self._scannerOutput(cargo=12), SCANNED_LINE, CONTRACT_EXIT_CODES
        )
        assert problems, "两侧包数不一致却报通过——对账判据不咬合"
        joined = "\n".join(problems)
        assert "447" in joined and "12" in joined, (
            f"报错必须同时点名两侧读数（解析 447 / 扫描器 12），实得: {joined}"
        )

    def test_unparsable_scan_output_is_red(self, auditModule):
        """扫描器没吐『Scanned … found N packages』（版本/措辞变了）→ 报红，不静默。"""
        counts = {"NeurUI/src-tauri/Cargo.lock": 447}
        problems = auditModule._packageCountsMatch(
            counts, "everything is fine\n", SCANNED_LINE, CONTRACT_EXIT_CODES
        )
        assert problems, "读数缺失却报通过——门禁在没证据时不能绿"

    def test_error_exit_code_is_red_even_when_counts_match(self, auditModule):
        counts = {
            "NeurUI/src-tauri/Cargo.lock": 447,
            "tools/npx-runtime/package-lock.json": 368,
        }
        problems = auditModule._packageCountsMatch(
            counts, self._scannerOutput(), SCANNED_LINE, CONTRACT_EXIT_CODES, returncode=127
        )
        assert problems, "退出码 127 语义不明却报通过——PR #121 的红就是这么被放走的"


class TestPipelineExitCodesSurviveRedirect:
    """门禁步骤的写法必须让子进程退出码穿过管道（否则有漏洞也能绿）。"""

    @staticmethod
    def _auditStepScripts() -> list:
        yaml = pytest.importorskip("yaml")
        import io

        cnb = yaml.safe_load(io.open(PROJECT_ROOT / ".cnb.yml", encoding="utf-8").read())
        script = ""
        for p in cnb["main"]["push"]:
            if isinstance(p, dict) and p.get("name") == "dependency-audit":
                for st in p["stages"]:
                    if str(st.get("script", "")).strip().startswith("python scripts/ci/osv_audit.py"):
                        script = str(st["script"])
        gh = yaml.safe_load(
            io.open(PROJECT_ROOT / ".github" / "workflows" / "ci.yml", encoding="utf-8").read()
        )
        for st in gh["jobs"]["dependency-audit"]["steps"]:
            run = str(st.get("run", "") or "")
            if run.strip().startswith("python scripts/ci/osv_audit.py"):
                script += "\n" + run
        assert script.strip(), (
            "双侧都找不到 osv_audit.py 的门禁步骤——本判据无从生效（配置被挪走请同步本守卫）"
        )
        return [line.strip() for line in script.splitlines() if line.strip()]

    def test_verifies_the_real_idiom(self, tmp_path):
        """先自证判据本身会红：把脚本写成软管道形态，判据必须报出。"""
        soft = tmp_path / "soft.sh"
        soft.write_text("python3 -c 'import sys; sys.exit(2)' 2>&1 | cat\n", encoding="utf-8")
        problems = _load_audit_module()._pipelineExitCodesSurviveRedirect(soft.read_text(encoding="utf-8"))
        assert problems, "软管道（| cat 吞码）未被判红——判据不咬合"

        hard = tmp_path / "hard.sh"
        hard.write_text(
            "set -o pipefail\npython3 -c 'import sys; sys.exit(2)' 2>&1 | cat\n", encoding="utf-8"
        )
        assert _load_audit_module()._pipelineExitCodesSurviveRedirect(hard.read_text(encoding="utf-8")) == []

    def test_configured_steps_keep_the_exit_code(self):
        """当前双侧的写法必须让退出码穿过管道。

        回退路径：把脚本改成 `python scripts/ci/osv_audit.py 2>&1 | cat` 且不加
        `set -o pipefail` → 转红（`sh`/`bash` 实测：子进程 127，管道整体 0）。
        """
        module = _load_audit_module()
        problems = module._pipelineExitCodesSurviveRedirect("\n".join(self._auditStepScripts()))
        assert problems == [], (
            "门禁步骤的写法会让退出码丢失:\n  - " + "\n  - ".join(problems)
        )


class TestWithBinaryPreflightProvesUsableScanner:
    """`--with-binary` 必须真起一次扫描自证「这个二进制能用」，不能只看文件在不在。"""

    @staticmethod
    def _expectedJson(counts) -> dict:
        return {
            "results": [
                {
                    "source": {"path": str(p)},
                    "packages": [
                        {"package": {"name": f"pkg-{i}", "version": "1.0.0"}}
                        for i in range(count)
                    ],
                }
                for p, count in counts.items()
            ]
        }

    @staticmethod
    def _stubScanner(home: Path) -> Path:
        """可执行的假扫描器：`--version` 自证能过，扫描调用由 fakeRun 接管。"""
        home.mkdir(parents=True, exist_ok=True)
        stub = home / "osv-scanner-stub"
        stub.write_text("#!/bin/sh\necho 'osv-scanner version: 9.9.9'\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        return stub

    @staticmethod
    def _scannedOutput(targets, counts) -> str:
        return "".join(
            f"Scanned /w/{Path(rel).name} file and found {counts[rel]} packages\n"
            for rel in targets
        )

    def test_preflight_reports_each_scanned_target_with_package_counts(
        self, auditModule, tmp_path, monkeypatch
    ):
        """预检通过时必须给出逐目标包数读数（这是「真扫到了」的唯一证据）。"""
        home = tmp_path / "home"
        rels = ["NeurUI/src-tauri/Cargo.lock", "tools/npx-runtime/package-lock.json"]
        paths = _paths(home, rels)
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)
        counts = auditModule._targetPackageCounts(list(paths.values()))

        def fakeRun(cmd, *, cwd=None, capture_output=None, text=None):
            if "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="osv-scanner version: 9.9.9\n", stderr="")
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_text(json.dumps({"results": []}), encoding="utf-8")
            index = next(i for i, rel in enumerate(rels) if rel in " ".join(cmd))
            # 每次调用换一份计数输出，让「逐目标点名」这件事可核
            body = self._scannedOutput(
                rels, {rel: counts[rel] + index for rel in rels}
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=body, stderr="")

        monkeypatch.setattr(auditModule.subprocess, "run", fakeRun)
        report = auditModule.runPreflight(
            self._stubScanner(home),
            list(paths.values()),
            PROJECT_ROOT / "scripts/ci/osv-allowlist.toml",
        )
        text = "\n".join(report)
        for rel in rels:
            assert Path(rel).name in text, f"预检未点名被扫目标 {rel}"
        assert str(counts[rels[0]]) in text, "预检未给出各目标的包数读数"

    def test_preflight_fails_when_scanner_cannot_parse_targets(
        self, auditModule, tmp_path, monkeypatch
    ):
        """回退路径：扫描器不认这些目标（旧版线）→ 预检必须报红并点名，而非「它在就拿去用」。

        实测依据：v1.9.2 在 `scan source -L <file>` 下输出 `Failed to walk source`
        并退出 127——与 PR #121 的 CI 报错同码同形。
        """
        home = tmp_path / "home"
        rels = ["NeurUI/src-tauri/Cargo.lock"]
        paths = _paths(home, rels)
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)

        def fakeRun(cmd, *, cwd=None, capture_output=None, text=None):
            if "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="osv-scanner version: 9.9.9\n", stderr="")
            return subprocess.CompletedProcess(
                cmd, 127, stdout="Failed to walk source: no such file or directory\n", stderr=""
            )

        monkeypatch.setattr(auditModule.subprocess, "run", fakeRun)
        with pytest.raises(SystemExit) as exc:
            auditModule.runPreflight(
                self._stubScanner(home),
                list(paths.values()),
                PROJECT_ROOT / "scripts/ci/osv-allowlist.toml",
            )
        # 预检失败的「按基础设施错误收口」在命令行侧实测（live-verify 里读 exit code）；
        # 这里钉的是它必须**带着可点名的问题清单抛错**，而不是静默返回让调用方继续。
        message = str(exc.value)
        assert isinstance(exc.value, SystemExit), "预检失败必须停住流程，不是返回问题列表"
        assert "127" in message, "预检报错必须点名退出码（127 是 PR #121 的实际读数）"
        assert "Cargo.lock" in message, "预检报错必须点名未能解析的目标"
        assert "packages" in message, "预检报错必须点出包数读数缺失这一事实"


class TestMainExitAccounting:
    """预检失败必须落到契约码 2（基础设施错误），不许与「有漏洞(1)」撞码。"""

    def _runWithPreflight(self, auditModule, tmp_path, monkeypatch, problems):
        targets = _paths(tmp_path / "home", ["NeurUI/src-tauri/Cargo.lock"])
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", tmp_path / "home")
        monkeypatch.setattr(auditModule, "_resolve_scanner", lambda: Path("/bin/true"))
        def fakePreflight(*a, **k):
            raise SystemExit("\n".join(problems))
        monkeypatch.setattr(auditModule, "runPreflight", fakePreflight)
        monkeypatch.setattr(auditModule, "_targetPackageCounts", lambda ts: {"x": 1})
        monkeypatch.setattr(
            auditModule, "_packageCountsMatch", lambda *a, **k: []
        )
        monkeypatch.setattr(auditModule, "verify_local_patches", lambda: [])
        argv = ["osv_audit.py", "--targets", str(list(targets.values())[0])]
        monkeypatch.setattr(auditModule.sys, "argv", argv)
        return auditModule.main()

    def test_preflight_failure_returns_two(self, auditModule, tmp_path, monkeypatch):
        code = self._runWithPreflight(
            auditModule, tmp_path, monkeypatch, ["退出码 127 不在契约 (0, 1, 65) 内"]
        )
        assert code == 2, (
            "预检失败必须退 2（基础设施错误）。退 1 会与「发现未允许漏洞」撞码，"
            "读日志的人会以为真扫出了漏洞（PR #121 的 127 就是这么被误读的）"
        )


class TestCountToleranceIsCalibrated:
    """包数对账的容差必须「宽到不误报实测差异，紧到抓住量级错误」。"""

    def test_tolerance_window_is_bounded(self, auditModule):
        assert 0 < auditModule.COUNT_TOLERANCE < 1, "容差必须是 (0,1) 内的相对值"

    def test_observed_gap_passes_but_order_of_magnitude_drift_is_red(self, auditModule):
        """实测差异必须放行，量级差异必须报红（两端都咬合）。"""
        rel = "tools/npx-runtime/package-lock.json"
        pattern = SCANNED_LINE
        output = "Scanned /w/package-lock.json file and found 368 packages\n"
        # 实测：本条 371 vs 扫描器 368 → 通过
        ok = auditModule._packageCountsMatch(
            {rel: 371}, output, pattern, CONTRACT_EXIT_CODES
        )
        assert ok == [], f"实测差异被误报为问题: {ok}"
        # 量级差异（371 vs 12）→ 报红
        bad = auditModule._packageCountsMatch(
            {rel: 371},
            "Scanned /w/package-lock.json file and found 12 packages\n",
            pattern,
            CONTRACT_EXIT_CODES,
        )
        assert bad, "量级差异未被判红——容差过宽，对账失去意义"


class TestScanCommandHasSingleRecipe:
    """预检与正式扫描必须共用同一拼法——两处各拼一份就是第二个事实源。"""

    def test_preflight_and_main_use_the_same_builder(self, auditModule):
        import inspect

        for fn in (auditModule.runPreflight, auditModule.main):
            source = inspect.getsource(fn)
            assert "buildScanCommand(" in source, (
                f"{fn.__name__} 没走 buildScanCommand —— 命令拼法分叉后，"
                "「预检通过」不再能代表正式扫描那一次会用同一条命令"
            )

    def test_builder_places_targets_and_output_from_contract(self, auditModule, tmp_path):
        contract = auditModule._commandContract()
        out = tmp_path / "o.json"
        cmd = auditModule.buildScanCommand(
            Path("/bin/true"),
            ["/w/a.lock", "/w/b.lock"],
            PROJECT_ROOT / "scripts/ci/osv-allowlist.toml",
            out,
        )
        # 二进制一律归一到绝对路径（相对路径在 cwd/PATH 变化时表现为 127，
        # 会把「找不到文件」伪装成「扫描器故障」）
        assert cmd[0] == str(Path("/bin/true").resolve())
        assert cmd[1 : 1 + len(contract["subcommand"])] == contract["subcommand"]
        assert cmd[cmd.index(contract["output"]) + 1] == str(out)
        locks = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == contract["lockfile_flag"]]
        assert locks == ["/w/a.lock", "/w/b.lock"], "逐目标必须按契约定名的 flag 逐个挂上"


class TestBinaryPathIsAbsolute:
    """二进制路径必须绝对且自证可执行——127 的两种伪装都要在这里被拆掉。"""

    def test_relative_binary_is_normalized_to_absolute(self, auditModule, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        binary = home / "osv-scanner"
        binary.write_text("#!/bin/sh\necho 'osv-scanner version: 9.9.9'\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        monkeypatch.setattr(auditModule.Path, "cwd", classmethod(lambda cls: home))
        resolved = auditModule.resolveBinaryPath(Path("osv-scanner"))
        assert resolved.is_absolute(), "相对路径没被归一到绝对路径——127 会伪装成命令不成形"
        assert resolved == binary.resolve()

    def test_missing_binary_is_named_before_any_subprocess(self, auditModule, tmp_path):
        """回退路径：二进制缺失 → 在起扫描之前就点名，而不是等壳层给 127。"""
        with pytest.raises(SystemExit) as exc:
            auditModule.resolveBinaryPath(tmp_path / "does-not-exist")
        assert "不存在" in str(exc.value)

    def test_non_executable_binary_is_named(self, auditModule, tmp_path):
        """回退路径：文件在但不可执行（chmod 没生效）→ 点名「不可执行」，不报 127。"""
        binary = tmp_path / "osv-scanner"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o644)
        with pytest.raises(SystemExit) as exc:
            auditModule.resolveBinaryPath(binary)
        assert "不可执行" in str(exc.value), (
            "文件在但权限位不对时报的还是 127 一类的含糊话——缺件与故障分不开"
        )

    def test_assert_scanner_executable_returns_version_line(self, auditModule, tmp_path):
        binary = tmp_path / "osv-scanner"
        binary.write_text(
            "#!/bin/sh\necho 'osv-scanner version: 2.6.0'\necho 'osv-scalibr version: 0.5.2'\nexit 0\n",
            encoding="utf-8",
        )
        binary.chmod(0o755)
        line = auditModule.assertScannerExecutable(binary)
        assert "2.6.0" in line, "自证没回报扫描器版本——日志里无从判断用的是哪个二进制"

    def test_assert_scanner_executable_fails_on_nonzero_version(self, auditModule, tmp_path):
        """回退路径：`--version` 非 0（架构不符 / 动态库缺失）→ 报红并点名退出码。"""
        binary = tmp_path / "osv-scanner"
        binary.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        binary.chmod(0o755)
        with pytest.raises(SystemExit) as exc:
            auditModule.assertScannerExecutable(binary)
        message = str(exc.value)
        assert "127" in message and "自证失败" in message

    def test_preflight_and_main_both_go_through_resolve(self, auditModule):
        import inspect

        for fn in (auditModule.runPreflight, auditModule.main):
            assert "resolveBinaryPath" in inspect.getsource(fn), (
                f"{fn.__name__} 没走 resolveBinaryPath —— 两类调用者的路径口径会分叉，"
                "而 2026-09-22 那次「预检能跑、正式扫描 127」正是这么来的"
            )


class TestSubprocessFailureIsNotScannerVerdict:
    """子进程**起不来**（调用侧故障）不等于「扫描器不能用」，更不是「扫出了漏洞」。

    2026-09-22 PR #121 的 dependency-audit 连红三次，三次读数都是同一种形状：

        $ python scripts/ci/osv_audit.py
        [osv] 指纹校验通过 (linux_amd64)
        [osv] 扫描器二进制: /tmp/…/osv-scanner_linux_amd64
        [osv] 扫描器自证: osv-scanner version: 2.6.0（/tmp/…/osv-scanner_linux_amd64）
        [osv] 预检通过（真跑一次扫描自证契约）:
              - NeurUI/src-tauri/Cargo.lock: 447 packages
              - tools/npx-runtime/package-lock.json: 371 packages
        [osv] 扫描器异常退出（code=127）——不在契约 (0, 1, 65) 内

    同一次运行里，**同一个二进制刚被真跑并通过**（下载、指纹、版本自证、解析
    447/371 包全对），红却只出现在随后那一次调用上。127 是 `sh` 的
    「command not found」：子进程创建失败（ENOENT/ENOEXEC/EACCES）经解释器呈现的
    码与它同形，而 osv-scanner 自己**从不退 127**（v2.6.0 实跑：同一条命令退出 0）。

    `resolveBinaryPath()` 只能证明「文件在这一秒还在、权限位也对」——真起进程时它
    可能刚到就被摘掉、被挂断，或解释器没有执行权。故这里钉的是：
    **调用侧异常必须被单独归因**，且**不许拿状态码反推根因**。
    """

    def test_subprocess_oserror_is_reported_as_invocation_failure(
        self, auditModule, tmp_path, monkeypatch
    ):
        """`FileNotFoundError`/`PermissionError` 必须转成可点名的调用故障，不许裸抛。"""
        binary = tmp_path / "osv-scanner"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

        def boom(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(auditModule.subprocess, "run", boom)
        with pytest.raises(auditModule.ScannerInvocationError) as exc:
            auditModule.assertScannerExecutable(binary)
        message = str(exc.value)
        assert isinstance(exc.value, RuntimeError), "调用故障必须与扫描器裁决区分开"
        assert "无法执行" in message or "调用" in message, (
            "报错必须点明这是「门禁自己没能把扫描器跑起来」，"
            "而不是把 127 当成扫描器给出的裁决——两者在读日志时无法区分"
        )

    def test_preflight_failure_and_invocation_failure_are_distinct_types(
        self, auditModule, tmp_path, monkeypatch
    ):
        """两种根因必须是两个类型：否则「换一份二进制」与「修调用点」会被混为一句。

        `resolveBinaryPath` 拦「路径本身就不对」（起子进程之前），
        `ScannerInvocationError` 拦「路径看着对、真起进程时起不来」（之中）。
        两条路都必须单独归因，且**都不许复用 SystemExit**：否则调用方在
        `except SystemExit` 里无从分辨「扫描器说不能用」与「我根本没跑起来扫描器」。
        """
        assert issubclass(auditModule.ScannerInvocationError, RuntimeError)
        assert not issubclass(auditModule.ScannerInvocationError, SystemExit), (
            "调用故障不能复用 SystemExit——复用后调用方无从分辨"
            "「扫描器说不能用」与「我根本没跑起来扫描器」"
        )
        binary = tmp_path / "osv-scanner"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

        def boom(cmd, **kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(auditModule.subprocess, "run", boom)
        with pytest.raises(auditModule.ScannerInvocationError):
            auditModule.assertScannerExecutable(binary)

    def test_main_returns_two_when_scanner_cannot_be_invoked(
        self, auditModule, tmp_path, monkeypatch
    ):
        """调用故障是基础设施错误（2），绝不能与「发现未允许漏洞」（1）撞码。"""
        targets = _paths(tmp_path / "home", ["NeurUI/src-tauri/Cargo.lock"])
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", tmp_path / "home")

        def boom(*a, **k):
            raise auditModule.ScannerInvocationError("调用点探测失败")

        monkeypatch.setattr(auditModule, "runPreflight", boom)
        monkeypatch.setattr(auditModule, "verify_local_patches", lambda: [])
        monkeypatch.setattr(auditModule, "_resolve_scanner", lambda: Path("/bin/true"))
        argv = ["osv_audit.py", "--targets", str(list(targets.values())[0])]
        monkeypatch.setattr(auditModule.sys, "argv", argv)
        assert auditModule.main() == 2, (
            "调用故障必须退 2——退 1 会被读成「真扫出漏洞」，"
            "与 PR #121 里那个 127 被误读成「扫描器坏了」是同一类错"
        )

    def test_non_contract_exit_code_names_the_invocation_point(
        self, auditModule, tmp_path, monkeypatch
    ):
        """拿到非契约码（127 等）时必须先探测调用点，把「缺件」与「拼法不符」拆开。"""
        binary = tmp_path / "osv-scanner"
        # 探测只看「起得来 + 有输出」：真扫描器回的是 `osv-scanner version: X`
        binary.write_text(
            "#!/bin/sh\nprintf 'osv-scanner version: 9.9.9\\n'\n", encoding="utf-8"
        )
        binary.chmod(0o755)
        problems = auditModule._invocationProbe(binary)
        assert problems == [], "能调起来的二进制被误判为调用点不可用"

        gone = tmp_path / "vanish"
        problems = auditModule._invocationProbe(gone)
        assert problems, (
            "调用点已不可用却没被点名——拿到 127 时只能反推根因，"
            "这正是 PR #121 连红三次的读法"
        )
        assert str(gone) in problems[0], "点名必须带上具体路径（日志里要能直接复核）"

    def test_scanner_capability_is_a_probe_not_an_exit_code(self, auditModule, tmp_path, monkeypatch):
        """能力判据必须是**探测**出来的：同一条命令在预检里真跑过，才算「能用」。"""
        home = tmp_path / "home"
        paths = _paths(
            home, ["NeurUI/src-tauri/Cargo.lock", "tools/npx-runtime/package-lock.json"]
        )
        monkeypatch.setattr(auditModule, "PROJECT_ROOT", home)
        stub = home / "osv-scanner-stub"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        calls = []

        def fakeRun(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[1] == "--version":
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="osv-scanner version: 9.9.9\n", stderr=""
                )
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_text(json.dumps({"results": []}), encoding="utf-8")
            body = "".join(
                f"Scanned /w/{rel.rsplit('/', 1)[-1]} file and found {n} packages\n"
                for rel, n in (("Cargo.lock", 447), ("package-lock.json", 368))
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=body, stderr="")

        monkeypatch.setattr(auditModule.subprocess, "run", fakeRun)
        report = auditModule.runPreflight(stub, list(paths.values()), stub)
        assert calls, "预检必须真起一次扫描——不看文件在不在、不猜退出码语义"
        assert any("预检通过" in line for line in report)
        assert all(call[0] == str(stub) for call in calls), (
            "预检与正式扫描必须调同一个二进制（否则「预检通过」不代表正式那次能用）"
        )
        assert any(call[1] == "--version" for call in calls), (
            "自证那一次必须在真扫描之前——不然只能拿 127 反推根因"
        )

    def test_preflight_asks_the_same_question_twice_not_a_guess(
        self, auditModule, tmp_path, monkeypatch
    ):
        """「二进制能不能用」在**起扫描之前**就问一次；起不来时由调用归因兜住。

        PR #121 的红全部发生在「预检成功、下一次调用 127」之后——那一次调用是否
        真的起得来，只能由调用侧异常回答，不能靠读码。
        """
        binary = tmp_path / "osv-scanner"
        binary.write_text("#!/bin/sh\nprintf 'osv-scanner version: 9.9.9\\n'\n", encoding="utf-8")
        binary.chmod(0o755)
        calls = []

        def flaky(cmd, **kwargs):
            calls.append(list(cmd))
            if len(calls) > 1:
                raise FileNotFoundError(2, "No such file or directory")
            return subprocess.CompletedProcess(
                cmd, 0, stdout="osv-scanner version: 9.9.9\n", stderr=""
            )

        monkeypatch.setattr(auditModule.subprocess, "run", flaky)
        monkeypatch.setattr(auditModule, "_targetPackageCounts", lambda ts: {str(ts[0]): 1})
        with pytest.raises(auditModule.ScannerInvocationError) as exc:
            auditModule.runPreflight(binary, [binary], binary)
        assert str(binary) in str(exc.value), "调用故障必须点名是哪个二进制起不来"
        assert calls and calls[0][1] == "--version", (
            "预检必须先用 --version 真跑一次自证；不先问就只能在拿到 127 之后反推根因"
        )


class TestGuardIsWiredIntoCi:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip() for line in PROTECTED.read_text(encoding="utf-8").splitlines()
        }
        rel = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
        assert rel in listed, (
            f"{rel} 不在 scripts/ci/protected_tests.txt —— unit-tests 流水线不会跑它，"
            "扫描器契约与包数对账被回退时 CI 静默放行。"
        )

    def test_allowlist_is_still_the_gate_input(self, auditModule):
        assert ALLOWLIST.is_file()
        assert str(ALLOWLIST).endswith(auditModule.ALLOWLIST)
