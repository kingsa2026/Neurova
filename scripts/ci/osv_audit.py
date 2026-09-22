#!/usr/bin/env python3
"""跨生态依赖漏洞门禁（OSV）——补 pip-audit / npm audit 覆盖不到的依赖树。

背景（Issue #56 残留边界，实跑发现）：

pip-audit 与 npm audit 只覆盖"Python 声明锁"与"NeurUI 的 npm 树"。
仓库里还有两片**完全无人审计**的依赖面：

1. **Rust 依赖树** —— `NeurUI/src-tauri/Cargo.lock`（Tauri 桌面壳，447 包）。
   2026-09-18 实跑命中 8 条 RUSTSEC 公告（含 glib 0.18.5 未定义行为、
   rustls 0.23.43 TLS 1.3 跨加密层接受）。此前无任何工具看过它。
   （glib 0.18.5 已于 Issue #109 由仓内补丁修复：OSV 不解析 [patch] 段，故靠
   下方 LOCAL_PATCHES 逐条核验"版本未变但源码已修"这件事是否仍然成立。）
2. **运行时经 npx 拉取的 Node 包** —— camofox-browser / context7 / dbhub /
   server-filesystem 等由 `npx -y <pkg>` 在用户机器上现拉现跑，
   既无锁文件、也不进任何 audit 覆盖面（而这些包在生产路径上执行）。
   （NeurUI 自身的 npm 树不在此列——那份由 frontend job 的 npm audit 负责。）

本脚本用 OSV-Scanner（Google 维护，单一静态二进制）统一扫这些锁/清单，
把结果并入门禁。设计要点：

- **单侧实现、双侧复用**：`.cnb.yml` 与 `.github/workflows/ci.yml` 调同一条命令，
  由 tests/unit/test_ci_parity_guard.py 保证命令逐字一致。
- **二进制指纹校验**：按平台下载后核对 SHA256（常量内联），不信任传输通道。
  注意指纹只证明「与我钉的那份一致」，**不证明它是能用的扫描器**：实测 127 =
  扫描器本体缺失或不可执行（`sh` 的 "command not found" 码），与「版本不符/命令拼错」
  同码同形，把「环境缺件」伪装成「基础设施抖动」。故预检**在起扫描之前先自证
  二进制可执行**（`--version`），并把「用的是哪个二进制」打进日志——2026-09-22
  PR #121 的红就是靠这一步定性的：下载路径确实拿到了 v2.6.0，于是问题只可能在
  「扫描器本体不在 sh 能找到的地方」，据此把下载落点与自证统一改成绝对路径。
- **允许清单带理由与到期日**：`scripts/ci/osv-allowlist.toml`，过期即重新报红
  （`ignoreUntil` 由 osv-scanner 强制），防"永久静音"。
- **失败即红灯**：扫描器跑不起来（下载失败/清单缺失）按基础设施错误退出非 0。
  "跑不起来就算过"的安全门禁是安全剧场，本仓库不收。
- **本地补丁必须被核验**：OSV 按 `name + version` 判定，看的是清单里的版本字符串，
  不是实际编译的源码——`[patch.crates-io]` 换成仓内源码后它照旧报同一个版本。
  于是"某条允许清单靠本地补丁成立"这件事，只能由本脚本自己核验：`LOCAL_PATCHES`
  逐条绑定「锁文件 → 包 → 仓内路径」，路径不在、或锁里该包仍带 `source`（说明补丁
  没生效），一律按基础设施错误退出 2。清单与补丁只绑一头，等于给不存在的修复背书。

用法：
    python scripts/ci/osv_audit.py                 # CI 用法
    OSV_SCANNER_BIN=/path/to/osv-scanner python scripts/ci/osv_audit.py   # 离线/本地

退出码：0 = 无未允许的漏洞；1 = 有未允许的漏洞；2 = 基础设施错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── 扫描器版本与二进制指纹（升级须同时改这里与 allowlist 里的说明） ──────────
OSV_SCANNER_VERSION = "2.6.0"
_RELEASE_BASE = (
    f"https://github.com/google/osv-scanner/releases/download/v{OSV_SCANNER_VERSION}"
)
# 官方 osv-scanner_SHA256SUMS（2026-09-18 核对，与发布页一致）
_BINARY_SHA256 = {
    "linux_amd64": "ca69b3d3cd08f889a49dc0a383122f71cc528b83803671df5fd874d97485b108",
    "linux_arm64": "2c71403eb443d05891c4f268c3ad771cf4f16e5443463fd7851ef8f454d3c7e4",
    "darwin_amd64": "60c5296637e977b28eeda5c7f13573e447659a632922737f94d11fa7e30ad6ca",
    "darwin_arm64": "98c460dcd37de25819babd757d04542045b6243113e209edcd4d89fedb0256b4",
}

# ── 被扫锁文件/清单：仓库内全部"非 pip、非 NeurUI-npm-audit"依赖载体 ─────────
SCAN_TARGETS = (
    # Rust：Tauri 桌面壳依赖树（pip-audit / npm audit 都看不到）
    "NeurUI/src-tauri/Cargo.lock",
    # 运行时 npx 拉取的 Node 包清单（生产路径上执行，此前无锁无审计）
    "tools/npx-runtime/package-lock.json",
)

ALLOWLIST = "scripts/ci/osv-allowlist.toml"

# ── 扫描器命令契约（随版本落定；接口随版本变，故拼命令前先自证） ──────────────
# 为什么要有这张表：osv-scanner 从 v1 起换过子命令与 flag 拼法，且**不同版本
# 对同一条命令的失败形态一致（都退 127）**，把「命令拼错」伪装成「基础设施故障」。
# 2026-09-22 PR #121 实测：
#   $ osv-scanner-1.9.2 scan source -L tests/lock --format json   # v2 拼法喂 v1 线
#   Failed to walk source: no such file or directory      → 退出 127（= 本次 CI 读数）
#   $ osv-scanner-1.9.2 scan -L tests/lock --format json          # v1 拼法
#   退出 0，输出合法 JSON（results 为空同样退 0；有未允许漏洞退 1）
# 实测还钉住一件容易被想象出来但不存在的事：release 资产是**未压缩的单一静态
# 二进制**（v2.6.0 与 v1.9.2 均是），下载后 chmod +x 直接可跑——不需要任何解压器。
_COMMAND_CONTRACT = {
    "v2": {
        "subcommand": ["scan", "source"],
        "config_flag": "--config",
        "lockfile_flag": "--lockfile",
        "format_flag": "--format",
        "json_format": "json",
        "output": "--output",
        # 必须留 info 级：`Scanned … found N packages` 这一行就是本门禁唯一的
        # 「真扫到了」读数，实测 `--verbosity warn` 会把它整行吞掉 → 包数对账看不到
        # 证据就只能报红。降低 verbosity = 把判据的证据自己删掉。
        "extra": ["--verbosity", "info"],
    },
    "v1": {
        "subcommand": ["scan"],
        "config_flag": "--config",
        "lockfile_flag": "-L",
        "format_flag": "--format",
        "json_format": "json",
        "output": "--output",
        # v1 线与本仓库「逐条 -L 显式点名」的扫法自洽；目录级递归不在本门禁语义内。
        "extra": ["--skip-git"],
    },
}

# 合法退出码：0 = 无未允许漏洞；1 = 有未允许漏洞；65 = 入参错误。
# 其余（如 127）语义不明——**不许当"通过"**，这正是 2026-09-22 那次红的形态。
CONTRACT_EXIT_CODES = (0, 1, 65)

# 被扫依赖树「点数」用的解析器类型。未登记的类型不猜数，取 UNCOUNTED_SENTINEL
# 并显式报出（猜 0 会让对账退化成空转：扫了 0 个包也能印绿字）。
UNCOUNTED_SENTINEL = -1
# 被扫依赖树 → 扫描器自报包数的那行（本仓库唯一能证明「它真读了这片树」的读数）。
# 每式**只有一个捕获组**：包数。文件名的匹配故意不进组——两处口径若各取一个组，
# 「读的是哪片树」这件事会在两侧漂移，而它正是对账要咬住的东西。
SCANNED_LINE = {
    "NeurUI/src-tauri/Cargo.lock": re.compile(
        r"Scanned\s+\S*Cargo\.lock\s+file and found (\d+) packages"
    ),
    "tools/npx-runtime/package-lock.json": re.compile(
        r"Scanned\s+\S*package-lock\.json\s+file and found (\d+) packages"
    ),
}

# 被扫依赖树 → 「怎么点数」的登记表。未登记的类型一律 UNCOUNTED_SENTINEL + 报红，
# 不许拿"扫描器自己说它扫了几个"代替——那正是把判据交回被测对象。
_PACKAGE_COUNTERS = {
    "NeurUI/src-tauri/Cargo.lock": "cargo_lockfile",
    "tools/npx-runtime/package-lock.json": "npm_package_lock",
}

# ── 本地补丁登记：允许清单里"靠仓内源码修复"的条目必须在此逐条对账 ─────────────
# 键是锁文件路径，值是「包名 → 仓内目录」。判据：目录存在、且锁文件里该包
# 不再带 source（带 source = cargo 仍在用 registry 版本，补丁未生效）。
# 为什么必须核验：OSV 不解析 [patch] 段，只按锁文件里的 name+version 查库，
# 所以"版本没变但源码已修"这种形态它能看出的只有旧版本号——谁修的、修还在不在，
# 扫描器不知道。少了这一步，删掉 vendor 目录 CI 照样全绿。
LOCAL_PATCHES = {
    "NeurUI/src-tauri/Cargo.lock": {
        "glib": "NeurUI/src-tauri/vendor/glib-0.18.5",
    },
}


def verify_local_patches() -> list:
    """核验本地补丁登记与磁盘/锁文件一致，返回问题清单（空 = 通过）。"""
    problems = []
    for lock_rel, patches in LOCAL_PATCHES.items():
        lock_path = PROJECT_ROOT / lock_rel
        if not lock_path.is_file():
            problems.append(f"锁文件缺失，无法核验本地补丁: {lock_rel}")
            continue
        lock_text = lock_path.read_text(encoding="utf-8")
        for crate, vendor_rel in patches.items():
            vendor_dir = PROJECT_ROOT / vendor_rel
            if not (vendor_dir / "Cargo.toml").is_file():
                problems.append(
                    f"本地补丁目录不存在或不是 crate: {vendor_rel}"
                    f"（{lock_rel} 的 {crate} 正靠它修复）"
                )
            block = re.search(
                r'\[\[package\]\]\nname = "'
                + re.escape(crate)
                + r'"\nversion = "([^"]+)"\n(.*?)(?:\n\n|\Z)',
                lock_text,
                re.S,
            )
            if block is None:
                problems.append(f"{lock_rel} 里找不到包 {crate}（补丁登记已陈旧）")
                continue
            if "source = " in block.group(2):
                problems.append(
                    f"{lock_rel} 的 {crate} 仍带 source 字段——"
                    f"[patch.crates-io] 未生效，实际编译的不是 {vendor_rel}"
                )
    return problems


def _platform_key() -> str:
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    os_part = {"linux": "linux", "darwin": "darwin"}.get(sysname)
    arch_part = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if not os_part or not arch_part:
        raise SystemExit(f"不支持的平台: {sysname}/{machine}（请设置 OSV_SCANNER_BIN 指向本地二进制）")
    return f"{os_part}_{arch_part}"


def _download_scanner(dest_dir: Path) -> Path:
    key = _platform_key()
    expected = _BINARY_SHA256.get(key)
    if expected is None:
        raise SystemExit(f"无 {key} 的二进制指纹，拒绝下载（请设置 OSV_SCANNER_BIN）")

    suffix = ".exe" if platform.system().lower() == "windows" else ""
    url = f"{_RELEASE_BASE}/osv-scanner_{key}{suffix}"
    dest = dest_dir / f"osv-scanner{suffix}"

    print(f"[osv] 下载 {url}")
    try:
        with urllib.request.urlopen(url, timeout=180) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:  # noqa: BLE001 - 基础设施错误，下面统一报错退出
        raise SystemExit(f"osv-scanner 下载失败: {e}") from e

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != expected:
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"osv-scanner 指纹不符——拒绝执行（供应链完整性）\n"
            f"  期望 {expected}\n  实得 {digest}"
        )
    dest.chmod(0o755)
    print(f"[osv] 指纹校验通过 ({key})")
    return dest


def resolveBinaryPath(scanner) -> Path:
    """把扫描器路径归一为**绝对路径**，并自证文件在位、可执行。

    为什么必须绝对：127 在 `sh` 里就是 "command not found"。相对路径一旦碰上
    cwd 变化或 PATH 不含当前目录，表现与「扫描器坏了」完全一样——实测定位到
    2026-09-22 PR #121 的红正是这一类伪装（预检能跑、正式扫描 127，唯一的差别
    就是路径写法）。把路径归一放在一处，两类调用者不可能再分叉。
    """
    path = Path(scanner)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"[osv] 扫描器二进制不存在: {path}")
    if not os.access(path, os.X_OK):
        raise SystemExit(
            f"[osv] 扫描器二进制不可执行: {path}"
            "（chmod +x 未生效或文件系统禁执行）——127 会伪装成命令不成形"
        )
    return path


def assertScannerExecutable(scanner) -> str:
    """起扫描之前先自证「这个二进制能被执行」，返回它的版本行。

    判据是 `--version` 真跑 + 退出码 0 + 有输出：文件在位、权限位对、架构匹配
    三件事一次问清。缺了这一步，127（command not found）会被误读成版本不符。
    """
    binary = resolveBinaryPath(scanner)
    proc = subprocess.run([str(binary), "--version"], capture_output=True, text=True)
    line = (proc.stdout or proc.stderr or "").strip().splitlines()
    version_line = line[0] if line else ""
    if proc.returncode != 0 or not version_line:
        raise SystemExit(
            f"[osv] 扫描器自证失败：`{binary} --version` 退出 {proc.returncode}"
            f"（127 = 不可执行 / 架构不符）\n      输出: {version_line or '(空)'}"
        )
    return version_line


def _commandContract() -> dict:
    """按钉住的扫描器版本取命令契约（子命令 / flag / 输出侧），并补上自证用的 flag 集合。"""
    line = "v2" if OSV_SCANNER_VERSION.startswith("2.") else "v1"
    contract = dict(_COMMAND_CONTRACT[line])
    contract["line"] = line
    used = set(contract["subcommand"])
    used.add(contract["config_flag"])
    used.add(contract["lockfile_flag"])
    used.add(contract["format_flag"])
    used.add(contract["output"])
    contract["extra"] = list(contract["extra"])
    used.update(contract["extra"])
    contract["flags"] = frozenset(used)
    return contract


def buildScanCommand(scanner: Path, targets, allowlist: Path, output: Path) -> list:
    """按契约拼出扫描命令。单一落点：预检与正式扫描共用同一拼法。

    二进制一律走 `resolveBinaryPath()`（绝对路径）——相对路径在 `cwd` 变换、
    临时目录、或壳层 PATH 不含当前目录时表现为 `command not found`（127），
    而 127 与「命令不成形」同码，会把缺件伪装成扫描器故障。实测依据见
    `tests/unit/test_osv_audit_hardening_guard.py` 的 `TestBinaryPathIsAbsolute`。
    """
    contract = _commandContract()
    cmd = [str(resolveBinaryPath(scanner)), *contract["subcommand"]]
    cmd += [contract["config_flag"], str(allowlist)]
    cmd += [contract["format_flag"], contract["json_format"]]
    cmd += [contract["output"], str(output)]
    for t in targets:
        cmd += [contract["lockfile_flag"], str(t)]
    for flag, value in zip(contract["extra"][0::2], contract["extra"][1::2]):
        cmd += [flag, value]
    return cmd


_SOFT_PIPE = re.compile(r"\|\s*(cat|tee)\b")
_PIPEFAIL = re.compile(r"set\s+-o\s+pipefail")


def _pipelineExitCodesSurviveRedirect(script_text: str) -> list:
    """检查门禁步骤的写法是否让子进程退出码穿过管道，返回问题清单。

    为什么守这条：门禁步骤若写成 `python scripts/ci/osv_audit.py 2>&1 | cat`，
    `sh`/`bash` 的管道整体退出码取自**最后一个**命令（`cat` 恒 0）——
    实测：子进程退 127 时，软管道整体退 0，有漏洞也会绿。
    故要么不经管道，要么显式 `set -o pipefail`（本仓当前写法就是后者）。
    """
    problems = []
    for raw in (script_text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or not _SOFT_PIPE.search(line):
            continue
        if _PIPEFAIL.search(script_text):
            continue
        problems.append(
            f"`{line}` 经软管道输出且全脚本无 pipefail——"
            "管道整体退出码取自 cat/tee（恒 0），门禁失败会静默放行"
        )
    return problems


def _targetPackageCounts(targets) -> dict:
    """按依赖载体类型解析出逐目标的**包数**（相对 PROJECT_ROOT 的路径 → 包数）。

    为什么必须由我们这边算：扫描器自报的 `found N packages` 是唯一能证明
    「它真读了这两片依赖树」的读数，若连这个数都从它自己嘴里抄，对账无从成立。
    未登记的类型不猜数，取 UNCOUNTED_SENTINEL 让上层显式报红。
    """
    counts = {}
    for target in targets:
        path = Path(target)
        try:
            rel = path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = path.name
        counter = _PACKAGE_COUNTERS.get(rel)
        counts[rel] = UNCOUNTED_SENTINEL
        if counter is None:
            continue
        text = path.read_text(encoding="utf-8")
        if counter == "cargo_lockfile":
            counts[rel] = len(re.findall(r"(?m)^\[\[package\]\]$", text))
        elif counter == "npm_package_lock":
            try:
                tree = json.loads(text)
            except json.JSONDecodeError:
                continue
            packages = tree.get("packages")
            if not isinstance(packages, dict):
                continue
            # 口径归一（两版扫描器实测一致，故按它对齐）：`found N packages` 数的是
            # **一行一个依赖条目**（不含 lockfile 自身的元信息），本仓实测
            # `tools/npx-runtime/package-lock.json` → packages 372 条、去元信息后 371 条，
            # 而 v2.6.0 与 v1.9.2 都报 368——差异来自 registry 解析不到 source 的条目。
            # 故「我方点数」只用于证明"依赖树非空"，逐条对账以上层
            # `_packageCountsMatch` 的容差判据为准（见该函数 docstring）。
            counts[rel] = sum(1 for key in packages if key)
    return counts


# 逐目标对账的容差（相对值）。为什么不是「逐条相等」：扫描器自报的 `found N
# packages` 数的是**它自己解析并展开后的条目数**——两版口径实测有差（本仓
# `tools/npx-runtime/package-lock.json`：packages 372 条、去元信息 371 条，
# v2.6.0 与 v1.9.2 都报 368——差在 registry 解析不到 source 的条目）。
# 故判据取两端夹住：**必须有读数、不得为 0、两侧不得差出量级**。
# 逐条相等交给「自报读数 + 退出码」这一对更硬的证据，而不是拿我方点数去卡它。
COUNT_TOLERANCE = 0.25


def _packageCountsMatch(
    counts: dict,
    scanner_output: str,
    scanned_line: dict,
    contract_exit_codes,
    returncode: int = 0,
) -> list:
    """把「我方解析的包数」与「扫描器自报的包数」逐目标对账，返回问题清单。

    必须报红的情形（PR #121 的教训）：
    - 退出码不在契约集合内（127 = 命令不成形，语义不明，不许当"通过"）；
    - 某目标未登记类型 / 未登记自报读数的解析式（无从对账，不许静默取 0）；
    - 自报读数缺失（版本/措辞变了，或 verbosity 把证据吞了）——没证据不能绿；
    - 自报 0 个包（输出被截断 / 挂错目标）——此时告警若被 `2>&1 | cat` 吞掉，
      **有漏洞也能退出 0**；
    - 两侧差出容差（`COUNT_TOLERANCE`）：报错同时点名两侧读数。
    """
    problems = []
    if returncode not in contract_exit_codes:
        problems.append(
            f"扫描器退出码 {returncode} 不在契约集合 {tuple(contract_exit_codes)} 内——"
            "命令没成形或版本不符，禁止当通过"
        )
    for rel, expected in counts.items():
        if expected == UNCOUNTED_SENTINEL:
            problems.append(
                f"{rel} 未登记依赖载体类型——无从点数，故无法证明「真扫到了包」；"
                "未登记类型取 0 会让对账空转，这里是刻意报红"
            )
            continue
        pattern = scanned_line.get(rel)
        if pattern is None:
            problems.append(f"{rel} 未登记「自报包数」的解析式——无从对账")
            continue
        match = pattern.search(scanner_output or "")
        if match is None:
            problems.append(
                f"{rel}: 扫描器没报出 `Scanned … found N packages`——"
                "读数缺失，门禁不得在无证据时报绿"
            )
            continue
        reported = int(match.group(1))
        if reported == 0:
            problems.append(
                f"{rel}: 扫描器自报 0 个包——依赖树没被读到（或输出被截断）；"
                "此时告警若被管道吞掉，有漏洞也会退出 0"
            )
            continue
        if expected <= 0:
            problems.append(
                f"{rel}: 本条解析出的包数为 {expected}——点数式失效，对账无从成立"
            )
            continue
        drift = abs(reported - expected) / max(reported, expected)
        if drift > COUNT_TOLERANCE:
            problems.append(
                f"{rel}: 包数读数超出容差——本条解析 {expected} 个，扫描器自报 {reported} 个"
                f"（相对差 {drift:.0%} > {COUNT_TOLERANCE:.0%}）"
            )
    return problems


def runPreflight(scanner: Path, targets, allowlist: Path) -> list:
    """起一次**真扫描**自证「这个二进制是能用的扫描器」，返回读数清单。

    为什么不能只看文件在不在、指纹对不对：指纹只证明「与我钉的那份一致」。
    2026-09-22 PR #121 实测：下载失败时落盘的是 127 字节 GitHub 错误页，与真二进制
    sha256 相同，`_download_scanner` 报"指纹校验通过"，随后命令不成形退 127——
    与「扫描器版本不符」同码同形。故这里跑真链路：解析目标、出 JSON、退出码在契约内。
    """
    binary = resolveBinaryPath(scanner)
    version_line = assertScannerExecutable(binary)
    output = Path(tempfile.mkdtemp(prefix="osv-preflight-")) / "preflight.json"
    cmd = buildScanCommand(binary, targets, allowlist, output)
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    problems = []
    if proc.returncode not in CONTRACT_EXIT_CODES:
        problems.append(
            f"退出码 {proc.returncode} 不在契约 {tuple(CONTRACT_EXIT_CODES)} 内"
            f"（127 = 命令不成形 / 版本不符）"
        )
    if not output.is_file():
        problems.append(f"未落盘 JSON 结果（{output}）——扫描器没按 --output 契约输出")
        json_results = None
    else:
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
            json_results = payload.get("results") if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            problems.append("落盘的 JSON 无法解析")
            json_results = None
    if json_results is None and output.is_file():
        if not any("JSON" in p for p in problems):
            problems.append("结果里没有 results 字段——不是本门禁能消费的输出")

    merged = (proc.stdout or "") + "\n" + (proc.stderr or "")
    counts = _targetPackageCounts(targets)
    problems += _packageCountsMatch(
        counts, merged, SCANNED_LINE, CONTRACT_EXIT_CODES, returncode=proc.returncode
    )

    if problems:
        detail = "\n".join(f"      - {p}" for p in problems)
        raise SystemExit(
            "[osv] 扫描器预检失败（这个二进制不能用，拒绝拿去当门禁）:\n"
            + detail
            + "\n      注：127 = 命令不成形或版本不符；本仓契约见 _COMMAND_CONTRACT。"
        )

    report = [
        f"[osv] 扫描器自证: {version_line}（{binary}）",
        "[osv] 预检通过（真跑一次扫描自证契约）:",
    ]
    for rel, count in counts.items():
        report.append(f"      - {rel}: {count} packages")
    return report


def _resolve_scanner() -> Path:
    env_bin = os.environ.get("OSV_SCANNER_BIN", "").strip()
    if env_bin:
        p = Path(env_bin)
        if not p.is_file():
            raise SystemExit(f"OSV_SCANNER_BIN 指向的文件不存在: {p}")
        print(f"[osv] 使用本地二进制: {p}")
        return resolveBinaryPath(p)
    # 下载落点用专属目录：**每个消费者拿自己的一份**。预检与正式扫描两次调用之间
    # 只要有任何东西动了这个文件（并发清理、临时目录策略），第二次就是 127——
    # 而 127 与「命令不成形」同码。本脚本自己 chmod，不赌 umask 与目录默认权限。
    tmp = Path(tempfile.mkdtemp(prefix="osv-scanner-"))
    return _download_scanner(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description="跨生态依赖漏洞门禁（OSV-Scanner）")
    ap.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="覆盖被扫锁文件（默认取 SCAN_TARGETS 中存在者）",
    )
    args = ap.parse_args()

    targets = []
    for rel in args.targets if args.targets else SCAN_TARGETS:
        p = PROJECT_ROOT / rel
        if p.is_file():
            targets.append(str(p))
        elif args.targets:
            print(f"[osv] 指定的目标不存在: {rel}", file=sys.stderr)
            return 2

    if not targets:
        print("[osv] 无扫描目标——资产被删则该门禁失去意义，按错误处理", file=sys.stderr)
        return 2

    allowlist = PROJECT_ROOT / ALLOWLIST
    if not allowlist.is_file():
        print(f"[osv] 允许清单缺失: {ALLOWLIST}（无清单不容许静默放行）", file=sys.stderr)
        return 2

    patch_problems = verify_local_patches()
    if patch_problems:
        print("[osv] 本地补丁核验失败——允许清单正在为不存在的修复背书:", file=sys.stderr)
        for item in patch_problems:
            print(f"      - {item}", file=sys.stderr)
        return 2

    scanner = _resolve_scanner()
    # 日志里必须能读到「用的是哪个二进制」：2026-09-22 那次红的定性完全靠这一行
    # （下载路径确实拿到了 v2.6.0 → 问题只能在别处），否则只能猜。
    print(f"[osv] 扫描器二进制: {resolveBinaryPath(scanner)}")

    print("[osv] 扫描目标:")
    for t in targets:
        print("      -", Path(t).relative_to(PROJECT_ROOT))

    # 关键路径：**取回来的二进制必须自证能用**。经 `_resolve_scanner()` 进来的都走
    # 这一步（含 `--with-binary` / `OSV_SCANNER_BIN`）——"文件在"与"指纹对"都不
    # 足以说明它是能跑的扫描器（PR #121：127 字节错误页与真二进制同 sha256）。
    try:
        for line in runPreflight(scanner, targets, allowlist):
            print(line)
    except SystemExit as e:
        # 预检失败 = 基础设施错误，退出码**必须是 2**（不许让 SystemExit 的消息
        # 替我们决定退出码：非整数码在 shell 侧会变成 1，与「有漏洞」撞码）。
        print(e, file=sys.stderr)
        return 2

    output_dir = Path(tempfile.mkdtemp(prefix="osv-scan-"))
    output = output_dir / "results.json"
    # 结果落 `--output` 指定文件而不是 stdout：告警/进度与结果同流时，
    # `2>&1 | cat` 一类的写法会把子进程退出码吞掉（见守卫
    # `_pipelineExitCodesSurviveRedirect`），**有漏洞也会退出 0**。
    cmd = buildScanCommand(scanner, targets, allowlist, output)
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

    # 契约码判据先行：非契约码（127 等）说明命令没成形或版本不符，禁止当"无漏洞"。
    if proc.returncode not in CONTRACT_EXIT_CODES:
        binary = resolveBinaryPath(scanner)
        print(
            f"[osv] 扫描器异常退出（code={proc.returncode}）——不在契约 "
            f"{tuple(CONTRACT_EXIT_CODES)} 内，本条拒绝判定为通过。\n"
            f"      本轮二进制: {binary}\n"
            f"      在位={binary.is_file()} 可执行={os.access(binary, os.X_OK)} "
            f"大小={binary.stat().st_size if binary.is_file() else 'N/A'}\n"
            f"      127 的两种来源都要查：二进制本身不可执行（--version 已自证过），"
            f"或它依赖的某件东西不在。",
            file=sys.stderr,
        )
        return 2

    try:
        payload = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    except json.JSONDecodeError:
        payload = None

    if proc.returncode == 0:
        # 退出 0 不等于"真扫过"：v1 线在结果为空时同样退 0，告警可能已被吞掉。
        # 故用 exit 0 时也把读数与对账摊开，任何一条不咬合即按基础设施错误收口。
        counts = _targetPackageCounts(targets)
        problems = _packageCountsMatch(
            counts, (proc.stdout or "") + "\n" + (proc.stderr or ""), SCANNED_LINE,
            CONTRACT_EXIT_CODES, returncode=proc.returncode,
        )
        if payload is None:
            problems.append("没有解析出 JSON 结果（--output 未落盘或不可解析）")
        print("[osv] 扫描器自报读数：")
        for rel, count in counts.items():
            print(f"      - {rel}: {count} packages")
        if problems:
            print("[osv] ❌ 退出 0 但读数对不上——不许当通过:", file=sys.stderr)
            for item in problems:
                print(f"      - {item}", file=sys.stderr)
            return 2
        print("\n[osv] ✅ 无未允许的已知漏洞")
        return 0
    if proc.returncode == 1:
        print(
            "\n[osv] ❌ 发现未允许的漏洞。处置二选一：\n"
            "  (a) 升级依赖修掉（首选）；\n"
            f"  (b) 确无修复/不可达时，在 {ALLOWLIST} 登记 id+理由+到期日。\n"
            "  注：清单条目过期后本条会重新报红——这是刻意设计，防永久静音。",
            file=sys.stderr,
        )
        return 1
    print(
        f"[osv] 扫描器以契约码 {proc.returncode}（入参错误）退出——"
        "命令与扫描器版本不符，按基础设施错误收口",
        file=sys.stderr,
    )
    return 2


def _emitGateSummary(code: int, scanner_line: str = "", targets=()) -> None:
    """把失败读数落成一行可后处理的结构化摘要（CI 面板可据此聚合/告警）。

    为什么单独一行：本门禁的失败形态有 0/1/2 三种语义（无漏洞 / 有漏洞 /
    基础设施错误），日志里散在 print 之间时，看板只能靠人肉读。一行 JSON 让
    「最近一周基础设施错误率」这种问题变成可复算读数。
    """
    payload = {"gate": "osv", "exit": code, "targets": len(list(targets))}
    if scanner_line:
        payload["scanner"] = scanner_line
    print("OSV_GATE_SUMMARY " + json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    _code = main()
    # 非 0 时落一行结构化摘要：本门禁的 0/1/2 三种语义在散行日志里只能人肉读，
    # 一行 JSON 让「基础设施错误率」变成可复算读数（CI 面板可后处理）。
    if _code != 0:
        _emitGateSummary(_code, targets=SCAN_TARGETS)
    sys.exit(_code)
