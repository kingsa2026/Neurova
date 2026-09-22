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
- **两种根因不许混为一句话**：2026-09-22 PR #121 的 dependency-audit 连红三次，
  每次预检都真的跑通了，红只发生在随后那次调用上（127 = `sh` 的 command not found，
  与「命令拼错」同码同形）。故调用侧故障由 `ScannerInvocationError` 单独归因，
  「路径现在还能不能被调起来」由 `_invocationProbe()` 直接测，**不用状态码猜根因**。
- **裁决不依赖远端可实时到达**：127 的第三个来源是**漏洞库数据源不可达**——
  实测 `api.osv.dev` 被拦时扫描器自己就退 127，并且**照印**一句
  `Total 0 packages affected by 0 known vulnerabilities`（一个包都没查成却给安心话，
  fail-open）。故 ① 认这形态（`VULN_DB_UNREACHABLE`）并按基础设施错误收口；
  ② 裁决证据只取漏洞库那一路的读数（`No issues found` / `Filtered N vulnerabilities`，
  `_dbVerdict()`）——「依赖树被读了」（`End status: … inodes visited`）**不等于**
  「漏洞库被查过」，实测两个场景的 `End status` 逐字相同；
  ③ 把这条外部依赖收进可控面：**优先走离线库**（`--offline --offline-vulnerabilities`
  + 预取缓存，实测下载 47s / 扫描 12.7s，与直连逐条一致），CI 两侧各加一步
  best-effort 预取（`--prefetch-offline-databases || true`），门禁本体
  `--require-offline`：缓存不齐即点名缺哪个生态，不静默回退。
- **本地补丁必须被核验**：OSV 按 `name + version` 判定，看的是清单里的版本字符串，
  不是实际编译的源码——`[patch.crates-io]` 换成仓内源码后它照旧报同一个版本。
  于是"某条允许清单靠本地补丁成立"这件事，只能由本脚本自己核验：`LOCAL_PATCHES`
  逐条绑定「锁文件 → 包 → 仓内路径」，路径不在、或锁里该包仍带 `source`（说明补丁
  没生效），一律按基础设施错误退出 2。清单与补丁只绑一头，等于给不存在的修复背书。

用法：
    python scripts/ci/osv_audit.py                 # CI 用法
    python scripts/ci/osv_audit.py --prefetch-offline-databases   # 预取离线库（CI 前置步）
    python scripts/ci/osv_audit.py --require-offline              # 缺库即报错，不回退直连
    OSV_SCANNER_BIN=/path/to/osv-scanner python scripts/ci/osv_audit.py   # 离线/本地

退出码：0 = 无未允许的漏洞；1 = 有未允许的漏洞；2 = 基础设施错误。

仅安装了 Python 的环境即可跑（不依赖 unzip/tar/jq 等额外 CLI）。
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
        # 离线漏洞库：把「裁决依赖远端 api.osv.dev」这条外部依赖收进可控面。
        # 2026-09-22 PR #121 的真红就是 api.osv.dev 不可达（扫描器退 127 并印
        # 一句「0 漏洞」）。实测（同一天，v2.6.0）：
        #   --offline --download-offline-databases   → 缓存 crates.io 3.4MB + npm 206MB，
        #                                               耗时 47s
        #   --offline --offline-vulnerabilities      → 扫描 12.7s，退出 0，allowlist 生效，
        #                                               与直连结果逐条一致
        # 注意 **两个 flag 必须成对**：只给 --offline 而不给
        # --offline-vulnerabilities 时扫描器会退回「查本地缓存」，实测在缓存缺失或
        # 不完整时报 `no offline version of the OSV database is available` 并退 127——
        # 那正是本门禁要消灭的形态。
        "offline_flags": ["--offline", "--offline-vulnerabilities"],
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
        # v1 线**没有**离线库子命令（实测 1.9.2 的 `scan --help` 无 --offline*），
        # 故留空：拼命令时按契约取，不假设存在。
        "offline_flags": [],
    },
}

# 合法退出码：0 = 无未允许漏洞；1 = 有未允许漏洞；65 = 入参错误。
# **127 不是本门禁的契约码**，但它有一个必须被认出的来源（见下方
# VULN_DB_UNREACHABLE / VERDICT_LINE）：osv-scanner 在**漏洞库数据源不可达**时
# 自己就退 127。2026-09-22 PR #121 的 dependency-audit 连红三次，真因即此——
# 同一容器里下载 GitHub release 成功（出站对 github.com 放行），而
# `api.osv.dev` 被拦（实测指纹与版本自证全过、预检的第一次真扫描把两片树都读了）。
CONTRACT_EXIT_CODES = (0, 1, 65)

# ── 扫描器「查询到第几步」的**证据行**：每个目标一条 ────────────────────────────
# 为什么不能只看退出码：同一个 127 至少有三个来源（二进制缺失/不可执行、调用侧
# 异常、**数据源不可达**），且第三种在读数是 `Total 0 packages affected by
# 0 known vulnerabilities` —— 一句"没扫到漏洞"的话。只判码就分不出
# 「真扫了、真没漏洞」与「一个包都没查成、却印了句安心话」（fail-open）。
#
# 判据取**每目标一行**的 `End status: N dirs visited, M inodes visited, K Extract
# calls`：实测（2026-09-22，v2.6.0）
#   * 正常扫描两片锁文件 → `2 inodes visited, 2 Extract calls`（每个目标一次）；
#   * api.osv.dev 被拦（CI 形态）→ 同一行照印，但退出码 127 且结果里 0 条；
#   * **全部命中被允许清单静默** → 读数只有 `No issues found`（没有 Total 行），
#     退出 0，JSON 里 `results` 为空数组。
# 故「有裁决」不能靠某一句措辞（措辞会随版本与结果形态变），只能靠
# ① 每个目标都被点数（inodes/Extract 计数），② JSON 结果可解析并与退出码一致。
# 缺任一 → 按基础设施错误收口。
END_STATUS_LINE = re.compile(
    r"End status:\s*(\d+)\s+dirs visited,\s*(\d+)\s+inodes visited,\s*(\d+)\s+Extract calls"
)
# 漏洞库**给出裁决**的两种读数（实测原文，v2.6.0）：
#   * 全部命中被允许清单静默 → `Filtered 8 vulnerabilities from output` + `No issues found`
#   * 无命中                → `No issues found`
#   * 无命中且 filters 为空 → `Scanned … No issues found`
# 这两行是「漏洞库这一路答复了」的唯一证据。**不**收那句
# `Total N packages affected by M known vulnerabilities`：实测数据源不可达时它照印
# （M=0），把它当证据就等于把「没查成」读成「没漏洞」——本门禁 2026-09-22 红过的那条。
NO_ISSUES_LINE = re.compile(r"No issues found", re.IGNORECASE)
FILTERED_LINE = re.compile(r"Filtered\s+\d+\s+vulnerabilit", re.IGNORECASE)

# 扫描器自述「漏洞库数据源不可达」（真扫描器实测原文，2026-09-22）。**两条分发
# 路径都要认**，它们同源同因、退出码也一样：
#
# ① 线上查询（默认直连通路）：
#     Error during extraction: (extracting as vulnmatch/osvdev) max retries
#     exceeded: attempt 4: request failed: Post "https://api.osv.dev/v1/querybatch"
#     dial tcp …: i/o timeout
# ② 离线库分发（本仓修后默认通路，缓存缺失/被拦时）：
#     could not load db for crates.io ecosystem: unable to fetch OSV database:
#     could not retrieve OSV database archive: Get
#     "https://osv-vulnerabilities.storage.googleapis.com/crates.io/all.zip"
#     dial tcp: lookup …: connection refused
#     Error during extraction: (extracting as vulnmatch/osvlocal) unable to fetch …
#
# 只认 ① 会让「离线库被拦」漏成「命令不成形 / 版本不符」——正是 PR #121 的误读形态
# （`vulnmatch/osvlocal` 与 `vulnmatch/osvdev` 是同一条链的两端）。
# 这是**环境**问题（CI 出站被拦），不是本仓代码问题；但它绝不能以"绿"的形态通过
# ——扫描器自己就退 127，故按基础设施错误收口（exit 2），并点名数据源。
VULN_DB_UNREACHABLE = re.compile(
    r"(extracting as vulnmatch/osv(?:dev|local)"
    r"|api\.osv\.dev"
    r"|osv-vulnerabilities\.storage\.googleapis\.com"
    r"|could not load db for \w+ ecosystem"
    r"|unable to fetch OSV database"
    r"|no offline version of the OSV database)",
    re.IGNORECASE,
)


class ScannerInvocationError(RuntimeError):
    """门禁自己没能把扫描器跑起来（调用侧故障），**不是**扫描器给出的裁决。

    为什么必须单独一个类型：2026-09-22 PR #121 的 dependency-audit 连红三次，三次
    都是**同一次运行里预检真的跑成功了**（下载、指纹、解析 447/371 包全对），红只
    发生在随后那一次调用上。`resolveBinaryPath` 只证明「文件在这一秒还在、权限位也
    对」——真起进程时它可能刚被摘掉、被挂断，或解释器根本没有执行权；这时壳层给的
    码仍是 127，与「命令不成形」同形。`sh` 的 127 就是 "command not found"，
    而扫描器自己**从不退它**（v2.6.0 实跑：同一条命令退出 0）。

    故本脚本不再拿状态码反推根因：调用侧故障在这里单独归因，
    `main()` 一律按基础设施错误 2 收口，绝不与「发现未允许漏洞(1)」撞码。
    """

_CAUSAL_LINE = re.compile(r"error during extraction|unable to|failed|could not", re.I)


def _causalLine(text: str) -> str:
    """取自述里**说明原因**的那一行。

    为什么不取 tail：扫描器红的时候，最后几行常被「allowlist 未命中条目」列表占满
    （本仓实测），取 tail 会把「说因的那句」挤掉，读日志的人看到的还是无关行。
    故优先找含 error/failed/unable 的行，找不到才回落到最后一行。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in lines:
        if _CAUSAL_LINE.search(line):
            return line[:300]
    return lines[-1][:300] if lines else "(无输出)"


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


# ── 离线漏洞库缓存：把「裁决依赖远端 api.osv.dev」收进可控面 ──────────────────
# 为什么必须做：2026-09-22 PR #121 那次红，真因是 CI 容器对 `api.osv.dev` 不可达
# （同容器对 github.com 放行，故二进制下载与指纹自证全过）。扫描器此时退 127 并
# 印一句「0 漏洞」，门禁只能退 2 报红——于是「CI 网络抖动」与「真有未允许漏洞」
# 在合并流程里长得一样，都得人来看（那一单连红三次，每次都被当抖动重跑）。
#
# 本仓跑过的两条通路（2026-09-22 实测，v2.6.0）：
#   crates.io 离线库   3.4MB
#   npm 离线库       206MB   下载耗时 47s（两者合计）
#   随后 `--offline --offline-vulnerabilities` 扫描 12.7s、退出 0、allowlist 生效，
#   与直连结果逐条一致。
#
# 缓存落点与扫描器自己的默认位置一致（`~/.cache/osv-scalibr/<ecosystem>/all.zip`），
# 故不必额外教它去哪儿找；本脚本只负责「判断齐不齐」与「触发预取」。
# 为什么用扫描器自己的目录而不是本脚本另建一个：另建就等于维护第二份缓存口径，
# 而「哪个生态的库存在哪」是扫描器随版本变的事实——本脚本不抄它。
OSV_DB_CACHE = Path.home() / ".cache" / "osv-scalibr"
# 被扫依赖树 → 它需要的离线库归属（crates.io / npm）。缺一份即整条离线路径不可用：
# 实测缓存只有 crates.io 时，npm 那一路会报
# `no offline version of the OSV database is available` 并退 127。
OFFLINE_DB_SCOPE = {
    "NeurUI/src-tauri/Cargo.lock": "crates.io",
    "tools/npx-runtime/package-lock.json": "npm",
}


def _requiredOfflineScopes(targets) -> list:
    """从被扫目标推出「必须备好哪几个生态的离线库」（相对 PROJECT_ROOT 的路径）。"""
    scopes = []
    for target in targets:
        path = Path(target)
        try:
            rel = path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = path.name
        scope = OFFLINE_DB_SCOPE.get(rel)
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def offlineDatabaseProblems(targets) -> list:
    """检查离线库缓存是否已备齐，返回问题清单（空 = 可供 `--offline` 使用）。

    判据是**文件在场**，不是「下载过」：扫描器把每个生态的库落成
    `<scopes>/<ecosystem>/all.zip`（实测 crates.io/all.zip 3.4MB、npm/all.zip 206MB）。
    只查在场不查新鲜度——新鲜度由预取步骤负责，且**过期库仍好过一个不可达的库**：
    过期只会漏报新公告，不可达会让整条门禁在「网络抖动」与「真有漏洞」之间无从分辨。
    """
    scopes = _requiredOfflineScopes(targets)
    problems = []
    for scope in scopes:
        db = OSV_DB_CACHE / scope / "all.zip"
        if not db.is_file():
            problems.append(f"离线库缺失: {db}（生态 {scope}）")
    if not scopes:
        problems.append("没有可归属到生态的被扫目标——离线库归属表需复核")
    return problems


def prefetch_offline_databases(scanner: Path, targets) -> int:
    """预取离线漏洞库到 `OSV_DB_CACHE`，返回退出码（0 = 齐备）。

    为什么由本脚本而不是 CI 里写死命令：`--download-offline-databases` 的拼法
    与「哪个生态落在哪个子目录」都是扫描器随版本变的事实，二者必须与
    `buildScanCommand` 的离线 flag 同源，否则会出现「预取到 A 处、扫描读 B 处」
    ——那时门禁报的是「离线库缺失」，而缓存其实就在旁边。

    预取**允许失败**（本函数返回非 0，但 CI 步不据此判红）：库过期只漏报新公告，
    而库缺失只是让门禁回退直连。把预取写成硬门禁，等于把「CI 出站策略」升级成
    一个会随网络抖动的红灯——那正是本单要消灭的形态。真正的判据在门禁本体。
    """
    binary = resolveBinaryPath(scanner)
    assertScannerExecutable(binary)
    scopes = _requiredOfflineScopes(targets)
    if not scopes:
        print("[osv] 没有可归属到生态的被扫目标——不预取", file=sys.stderr)
        return 2
    print(f"[osv] 预取离线漏洞库 → {OSV_DB_CACHE}（生态: {', '.join(scopes)}）")
    cmd = [str(binary), "scan", "source", "--offline", "--download-offline-databases"]
    for t in targets:
        cmd += ["--lockfile", str(t)]
    proc = _runScannerProcess(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    # 退出码语义：「已经是最新」与「刚下载完」都不该算失败。实测下载完 rc=1
    # （扫描器先下载、再拿新库扫了一遍并报了允许清单外的历史命中），
    # 「已最新」实测 rc=0。故判据落在**缓存文件是否在场**上，码只打日志。
    problems = offlineDatabaseProblems(targets)
    if problems:
        print(f"[osv] 预取未完成（扫描器退出码 {proc.returncode}）:", file=sys.stderr)
        for item in problems:
            print(f"      - {item}", file=sys.stderr)
        print(
            f"      扫描器自述：{_causalLine((proc.stderr or '') + (proc.stdout or ''))}",
            file=sys.stderr,
        )
        return 2
    for scope in scopes:
        db = OSV_DB_CACHE / scope / "all.zip"
        print(f"[osv]       - {scope}: {db.stat().st_size // (1 << 20)} MB")
    return 0


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


def _runScannerProcess(cmd, **kwargs):
    """起扫描器进程；把「起不来」单独归因，不再让它伪装成扫描器的退出码。

    子进程创建失败在 Python 侧是 OSError 子类（`FileNotFoundError` / `PermissionError`
    等），而壳层看到的是 127——与「命令不成形」同码。故这里在**任何状态码判据之前**
    捕获调用侧故障，转成 `ScannerInvocationError`（上层按基础设施错误 2 收口）。
    本仓所有 `subprocess.run` 调用点共用它，异常语义不会各写一份。
    """
    try:
        return subprocess.run(cmd, **kwargs)
    except OSError as e:
        raise ScannerInvocationError(
            f"无法执行扫描器命令：{cmd[0]}（{type(e).__name__}: {e}）"
            "——这是门禁没把扫描器跑起来，不是扫描器给出的裁决"
        ) from e


def _endStatus(scanner_output: str):
    """从读数里取 `End status: …` 三个计数，返回 `(dirs, inodes, extract)` 或 `None`。

    这是「扫描器真的把每个目标都读了」的**每目标**读数——本门禁据此证明
    「不是只读了第一片树就退出」。措辞会随版本变，故只在缺失时报「无证据」，
    不把它当作唯一的裁决来源（裁决另看 JSON 与退出码是否自洽）。
    """
    match = END_STATUS_LINE.search(scanner_output or "")
    if match is None:
        return None
    return tuple(int(g) for g in match.groups())


def _dbVerdict(scanner_output: str):
    """取「漏洞库这一路给出的裁决」，`None` = 没拿到。

    为什么要单独一根轴：`End status: … 2 inodes visited, 2 Extract calls` 数的是
    **扫了几个依赖清单**，`Filtered N vulnerabilities` / `No issues found` 才是
    **漏洞库查询的裁决**。2026-09-22 实测两者会分叉——同一条 `End status` 在两
    个场景里逐字相同：

        # 出站正常
        End status: 0 dirs visited, 2 inodes visited, 2 Extract calls, 29ms elapsed
        Filtered 8 vulnerabilities from output
        No issues found                                          → exit 0

        # api.osv.dev 被拦（本机用黑洞代理复刻，实测）
        End status: 0 dirs visited, 2 inodes visited, 2 Extract calls, 29ms elapsed
        Error during extraction: (extracting as vulnmatch/osvdev) … api.osv.dev …
                                                                 → exit 127

    只咬依赖树读数时，这两个场景**不可区分**；而后者印的那句「Total 0 packages
    affected by 0 known vulnerabilities」会让下游把它读成「真没漏洞」（fail-open）。
    故裁决一律从这一路取：拿到 `No issues found` 或 `Filtered N vulnerabilities`
    才算「漏洞库给了答复」；只有那份「0 漏洞」的安心话不算（实测它在数据源不可达
    时照印）。

    返回值取那句裁决原文（便于打进日志），取不到则 `None`。
    """
    text = scanner_output or ""
    for pattern in (NO_ISSUES_LINE, FILTERED_LINE):
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return None


def _verdictProblems(returncode: int, scanner_output: str, payload, targets) -> list:
    """检查「这次调用到底有没有拿到可信裁决」，返回问题清单。

    三条判据（2026-09-22 实测校准，缺任一即按基础设施错误收口）：

    1. **每个目标都被点数**：`End status: … N inodes visited, K Extract calls` 里
       的 N 必须 ≥ 目标数。只读到第一片树就把自己关掉（IO 错误、出站半途被拦）
       是本门禁此前看不见的形态——它仍会印 `Total 0 … 0 known vulnerabilities`。
    2. **结果与退出码自洽**：
       - 退出 0：JSON 可解析，且要么 `results` 为空、要么读数里有 `No issues found`
         （全部命中被允许清单静默时实测就是这个形态）；
       - 退出 1：JSON 可解析，且 `results` **非空**（空数组 + 退出 1 自相矛盾，
         此前会被读成「扫出漏洞了」）。
    3. **不许用一句安心话代替证据**：`Total 0 packages affected by 0 known
       vulnerabilities` 在「一个目标都没查成」时同样会印（实测：api.osv.dev 被拦时
       它照印，退出码却是 127），所以那句话本身不构成通过依据。
    """
    problems = []
    status = _endStatus(scanner_output)
    expected_targets = len(list(targets))
    if status is None:
        problems.append(
            f"扫描器以 {returncode} 退出且读数里没有 `End status: …` 这一行——"
            "拿不到「读了几个目标」的读数，按基础设施错误收口。自查顺序："
            "① 二进制缺失/不可执行（已在起扫描前自证）；② 调用侧异常（已单独归因）；"
            "③ **漏洞库数据源不可达**：osv-scanner 在 api.osv.dev 被拦时自己就退 127，"
            "且仍会印 `Total 0 packages affected by 0 known vulnerabilities`"
        )
    elif status[1] < expected_targets:
        problems.append(
            f"扫描器只读了 {status[1]} 个目标（本次挂了 {expected_targets} 个）——"
            "有目标没被读，此前的「0 漏洞」读数对它们无效"
        )
    results = payload.get("results") if isinstance(payload, dict) else None
    if results is None:
        problems.append(
            f"没有可解析的 JSON 结果（--output 未落盘或不可解析）——"
            f"退出码 {returncode} 不足以构成裁决"
        )
        return problems
    if returncode == 0 and results:
        problems.append(
            f"退出 0 但 JSON 里有 {len(results)} 段命中——结果与退出码自相矛盾，"
            "不许当通过（要么扫描器版本/契约不符，要么告警被吞）"
        )
    if returncode == 0 and not results and _dbVerdict(scanner_output) is None:
        # 依赖树读数足数、结果为空、退出 0 —— 看起来最像「真没漏洞」的形态，
        # 但漏洞库那一路**没给裁决**。两个场景（数据源不可达 / 真无漏洞）在
        # 依赖树一层完全同形，区别只在这一路；分不出就必须报红，不许赌。
        problems.append(
            "退出 0 且空结果，但读数里没有漏洞库给出的裁决"
            "（既无 `No issues found`、也无 `Filtered N vulnerabilities`）——"
            "依赖树读数足数只证明「清单被读了」，不证明「漏洞库被查过」；"
            "实测 api.osv.dev 被拦时扫描器照印 "
            "`Total 0 packages affected by 0 known vulnerabilities` 并退非零，"
            "该形态与「真无漏洞」在依赖树这一层同形，故不得据以报绿"
        )
    if returncode == 1 and not results:
        problems.append(
            "退出 1 但 JSON 里 0 段命中——结果与退出码自相矛盾，"
            "不许当成「扫出未允许漏洞」（该形态此前会被读成后者）"
        )
    if returncode == 1 and not NO_ISSUES_LINE.search(scanner_output or "") and not results:
        problems.append("退出 1 且读数与结果都拿不到命中名单——无法据以处置")
    return problems


def _missingVerdictProblem(returncode: int) -> str:
    """读数缺失时的问题描述——把非契约退出码的来源摊开，读日志的人不必再猜。"""
    return (
        f"扫描器以 {returncode} 退出但读数不完整——拿不到裁决证据，"
        "按基础设施错误收口。自查顺序：① 二进制缺失/不可执行（已在起扫描前自证）；"
        "② 调用侧异常（起进程失败，已单独归因）；③ **漏洞库数据源不可达**："
        "osv-scanner 在 api.osv.dev 被拦时自己就退 127，且仍会印 "
        "`Total 0 packages affected by 0 known vulnerabilities` —— "
        "这是本条拒绝就它下结论的原因（一个包都没查成时那句话照印）"
    )


def _invocationProbe(scanner) -> list:
    """探测「这个路径现在还能不能被调起来」，返回问题清单（空 = 能调起来）。

    判据刻意**不看业务结果**（锁文件 / allowlist / 退出码语义都不参与）：
    这里只问一件事——同一个路径，预检调得起来、正式那次调得起来吗。
    能调起来返回空清单（它自己退什么码由各自的判据管），调不起来就点名 errno。
    缺了这一步，只能拿 127 反推根因——而那正是 PR #121 连红三次的读法。
    """
    try:
        proc = subprocess.run(
            [str(scanner), "--version"], capture_output=True, text=True, timeout=60
        )
    except OSError as e:
        return [
            f"{scanner} 无法执行（{type(e).__name__}: {e}）——"
            "预检通过说明它此前可用，正式扫描却在调用点失败"
        ]
    except subprocess.TimeoutExpired:
        return [f"{scanner} --version 超时（60s）——调用点已不可用"]
    lines = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip().splitlines()
    return [] if lines else [f"{scanner} --version 无任何输出——调用点已不可用"]


def assertScannerExecutable(scanner) -> str:
    """起扫描之前先自证「这个二进制能被执行」，返回它的版本行。

    判据是 `--version` 真跑 + 退出码 0 + 有输出：文件在位、权限位对、架构匹配
    三件事一次问清。缺了这一步，127（command not found）会被误读成版本不符。
    """
    binary = resolveBinaryPath(scanner)
    # 起进程这一步也可能失败（文件刚到就被摘掉、解释器没有执行权、被挂断），
    # 壳层给的码还是 127 —— 故与扫描调用共用同一个归因落点，不许裸抛 OSError。
    proc = _runScannerProcess([str(binary), "--version"], capture_output=True, text=True)
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
    contract["offline_flags"] = list(contract.get("offline_flags", []))
    used.update(contract["offline_flags"])
    contract["flags"] = frozenset(used)
    return contract


def buildScanCommand(
    scanner: Path, targets, allowlist: Path, output: Path, offline: bool = False
) -> list:
    """按契约拼出扫描命令。单一落点：预检与正式扫描共用同一拼法。

    二进制一律走 `resolveBinaryPath()`（绝对路径）——相对路径在 `cwd` 变换、
    临时目录、或壳层 PATH 不含当前目录时表现为 `command not found`（127），
    而 127 与「命令不成形」同码，会把缺件伪装成扫描器故障。实测依据见
    `tests/unit/test_osv_audit_hardening_guard.py` 的 `TestBinaryPathIsAbsolute`。

    `offline=True` 时补上离线库 flag（成对，见契约表注释）。调用方按
    「缓存是否已备好」决定，不由本函数猜——缓存缺失时擅自离线会得到
    `no offline version of the OSV database is available`（实测退 127）。
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
    if offline:
        cmd += list(contract["offline_flags"])
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
            "禁止当通过（127 的来源不止一个：二进制/调用点问题、漏洞库数据源不可达、"
            "命令与版本不符；调用方须逐条点名，不许按码猜）"
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


def runPreflight(scanner: Path, targets, allowlist: Path, offline: bool = False) -> list:
    """起一次**真扫描**自证「这个二进制是能用的扫描器」，返回读数清单。

    为什么不能只看文件在不在、指纹对不对：指纹只证明「与我钉的那份一致」。
    2026-09-22 PR #121 实测：下载失败时落盘的是 127 字节 GitHub 错误页，与真二进制
    sha256 相同，`_download_scanner` 报"指纹校验通过"，随后命令不成形退 127——
    与「扫描器版本不符」同码同形。故这里跑真链路：解析目标、出 JSON、退出码在契约内。

    `offline` 与正式扫描**必须同值**：预检若直连、正式跑离线（或反之），两者用的
    就不是同一条通路——「预检通过」不再代表正式那次能给出裁决，而这正是 2026-09-22
    连红三次的读法。故由 `main()` 决策一次、两处透传同一份。
    """
    binary = resolveBinaryPath(scanner)
    version_line = assertScannerExecutable(binary)
    output = Path(tempfile.mkdtemp(prefix="osv-preflight-")) / "preflight.json"
    cmd = buildScanCommand(binary, targets, allowlist, output, offline=offline)
    proc = _runScannerProcess(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    problems = []
    merged = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode not in CONTRACT_EXIT_CODES:
        if VULN_DB_UNREACHABLE.search(merged):
            problems.append(
                f"漏洞库数据源不可达（退出码 {proc.returncode}）——"
                "读数自述 api.osv.dev 查询失败；这不是二进制或拼法问题，"
                "且扫描器此时仍会印 `Total 0 packages affected by 0 known vulnerabilities`"
            )
        else:
            problems.append(
                f"退出码 {proc.returncode} 不在契约 {tuple(CONTRACT_EXIT_CODES)} 内"
                f"（127 = 命令不成形 / 版本不符）"
            )
    payload = None
    if not output.is_file():
        problems.append(f"未落盘 JSON 结果（{output}）——扫描器没按 --output 契约输出")
    else:
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            problems.append("落盘的 JSON 无法解析")
        else:
            if not isinstance(payload, dict) or "results" not in payload:
                problems.append("结果里没有 results 字段——不是本门禁能消费的输出")
                payload = None

    counts = _targetPackageCounts(targets)
    problems += _packageCountsMatch(
        counts, merged, SCANNED_LINE, CONTRACT_EXIT_CODES, returncode=proc.returncode
    )
    if proc.returncode in CONTRACT_EXIT_CODES:
        problems += _verdictProblems(proc.returncode, merged, payload, targets)
    elif VULN_DB_UNREACHABLE.search(merged):
        pass  # 已在上面点名「数据源不可达」，不再叠一条泛化描述

    if problems:
        detail = "\n".join(f"      - {p}" for p in problems)
        raise SystemExit(
            "[osv] 扫描器预检失败（本次无法给出可信裁决，拒绝当门禁）:\n"
            + detail
            + "\n      注：非契约退出码有多个来源（二进制缺失/不可执行、调用侧异常、"
            "漏洞库数据源不可达、命令与版本不符）；上面每条问题已逐条点名，"
            "按点名的那条处置，勿按码猜。"
        )

    report = [
        f"[osv] 扫描器自证: {version_line}（{binary}）",
        f"[osv] 裁决通路: {'离线库（不依赖 api.osv.dev）' if offline else '直连 api.osv.dev'}",
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
            raise SystemExit(f"[osv] OSV_SCANNER_BIN 指向的文件不存在: {p}")
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
    ap.add_argument(
        "--prefetch-offline-databases",
        action="store_true",
        help="只预取离线漏洞库后退出（CI 的前置步骤；门禁本体不靠它成功与否）",
    )
    ap.add_argument(
        "--require-offline",
        action="store_true",
        help="离线库不齐即退 2（默认：不齐则回退直连并在日志里点名）",
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

    try:
        scanner = _resolve_scanner()
    except SystemExit as e:
        # 归属解析失败（OSV_SCANNER_BIN 指的文件不在）同样是基础设施错误：不许让
        # SystemExit 的消息替我们决定退出码（非整数码在 shell 侧会变成 1，与
        # 「发现未允许漏洞」撞码）。
        print(e, file=sys.stderr)
        return 2
    # 二进制缺失/不可执行在**起扫描之前**就点名，不让壳层把它包成 127 再回来
    # （127 的三个来源混在一起时，读日志的人只能猜——PR #121 三次红就是这么读的）。
    try:
        binary = resolveBinaryPath(scanner)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    # 日志里必须能读到「用的是哪个二进制」：2026-09-22 那次红的定性完全靠这一行
    # （下载路径确实拿到了 v2.6.0 → 问题只能在别处），否则只能猜。
    print(f"[osv] 扫描器二进制: {binary}")

    print("[osv] 扫描目标:")
    for t in targets:
        print("      -", Path(t).relative_to(PROJECT_ROOT))

    if args.prefetch_offline_databases:
        # 预取是 CI 的前置步骤，只做这一件事就退出；判据在门禁本体里。
        try:
            return prefetch_offline_databases(scanner, targets)
        except ScannerInvocationError as e:
            print(f"[osv] 预取时调用故障（扫描器没被跑起来）: {e}", file=sys.stderr)
            return 2

    # 裁决通路决策**在预检之前**做一次，两处（预检 / 正式）透传同一个值。
    # 缓存齐备就走离线：本仓的裁决不该依赖一个 CI 出站不在本仓手里的远端域名
    # （2026-09-22 PR #121 三次红全因它不可达）。缓存不齐就直连——库过期只会漏报
    # 新公告，而缺库硬走离线会让整条门禁变成「永远退 127」的哑弹（实测）。
    offline_problems = offlineDatabaseProblems(targets)
    offline = not offline_problems
    if offline:
        print(f"[osv] 离线库缓存齐备，裁决走离线通路: {OSV_DB_CACHE}")
    elif args.require_offline:
        # CI 侧显式要求离线时，缺库**不静默回退**：回退直连会把「预取步骤坏了」
        # 藏成「这次网络恰好通」，下一次抖动才红，读日志的人无从归因。
        print("[osv] 离线库缓存不齐且显式要求离线——拒绝回退直连:", file=sys.stderr)
        for item in offline_problems:
            print(f"      - {item}", file=sys.stderr)
        return 2
    else:
        # 不静默降级：点名缺什么、以及「本次仍会现查远端」，让读日志的人知道
        # 下一次网络抖动会红在这里。
        print("[osv] 离线库缓存不齐，本次回退直连 api.osv.dev（网络不可达即无法裁决）:")
        for item in offline_problems:
            print(f"      - {item}")

    # 关键路径：**取回来的二进制必须自证能用**。经 `_resolve_scanner()` 进来的都走
    # 这一步（含 `--with-binary` / `OSV_SCANNER_BIN`）——"文件在"与"指纹对"都不
    # 足以说明它是能跑的扫描器（PR #121：127 字节错误页与真二进制同 sha256）。
    try:
        for line in runPreflight(scanner, targets, allowlist, offline=offline):
            print(line)
    except ScannerInvocationError as e:
        # 门禁自己没把扫描器跑起来（调用侧故障）：**必须在任何状态码判据之前**
        # 单独归因，按基础设施错误 2 收口。若与「扫描器给出的裁决」混为一句，
        # 读日志的人只能原地重跑一次（PR #121 连红三次的处置方式）。
        print(f"[osv] 调用故障（扫描器没被跑起来）: {e}", file=sys.stderr)
        return 2
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
    # buildScanCommand 内部走 resolveBinaryPath，与 runPreflight 自证过的是同一份
    # 绝对路径；调用侧故障（起不来）由 _runScannerProcess 单独归因。
    cmd = buildScanCommand(scanner, targets, allowlist, output, offline=offline)
    proc = _runScannerProcess(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

    versions = _invocationProbe(scanner)

    # 契约码判据：非契约码说明命令没成形或版本不符，禁止当"无漏洞"。
    if proc.returncode not in CONTRACT_EXIT_CODES:
        # 127 是壳层的 "command not found"，与「命令拼错」同码同形。本次预检刚拿同一条
        # 命令跑通过，所以这里先用探测点定根因，再回落到「命令不成形」；两种情况都要给
        # 可点名的读数，不许只印一个码让人去猜（PR #121 三次红就是这么被当成抖动重跑的）。
        binary = resolveBinaryPath(scanner)
        problems = _invocationProbe(binary)
        if problems:
            print(
                f"[osv] 扫描器异常退出（code={proc.returncode}）——"
                "不在契约内，且调用点已不可用：",
                file=sys.stderr,
            )
            for item in versions:
                print(f"      - {item}", file=sys.stderr)
            print(f"      本轮二进制: {binary}", file=sys.stderr)
            return 2
        # 先认「漏洞库数据源不可达」——2026-09-22 PR #121 的真因：出站被拦，
        # 扫描器自己退 127 且仍印 `Total 0 packages affected by 0 known vulnerabilities`。
        # 点名数据源，不要让人去换二进制、也不要让它以绿的形态过。
        merged = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if VULN_DB_UNREACHABLE.search(merged):
            print(
                f"[osv] ❌ 漏洞库数据源不可达（扫描器退出 {proc.returncode}）——"
                "本条无法给出裁决，按基础设施错误收口：\n"
                "      - 读数自述: api.osv.dev 查询失败（extracting as vulnmatch/osvdev）\n"
                "      - 注意：扫描器此时仍会印 `Total 0 packages affected by "
                "0 known vulnerabilities`，那不是「无漏洞」",
                file=sys.stderr,
            )
            return 2
        # 调用点还在（能调起来），那问题就在「命令拼法 / 版本不符」。两种读数都带上：
        # 二进制身份（定位「用的是哪份」）+ 扫描器自述的**说因那一行**（不取 tail：
        # 实测 tail 常被 allowlist 的未命中条目列表占满，把说因那句挤掉）。
        print(
            f"[osv] 扫描器异常退出（code={proc.returncode}）——不在契约 "
            f"{tuple(CONTRACT_EXIT_CODES)} 内，本条拒绝判定为通过。\n"
            f"      本轮二进制: {binary}\n"
            f"      在位={binary.is_file()} 可执行={os.access(binary, os.X_OK)} "
            f"大小={binary.stat().st_size if binary.is_file() else 'N/A'}",
            file=sys.stderr,
        )
        print(
            f"      扫描器自述：{_causalLine((proc.stderr or '') + (proc.stdout or ''))}",
            file=sys.stderr,
        )
        return 2

    try:
        payload = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    except json.JSONDecodeError:
        payload = None

    merged_output = (proc.stdout or "") + "\n" + (proc.stderr or "")

    if proc.returncode == 0:
        # 退出 0 不等于"真扫过"：v1 线在结果为空时同样退 0，告警可能已被吞掉。
        # 故用 exit 0 时也把读数与对账摊开，任何一条不咬合即按基础设施错误收口。
        counts = _targetPackageCounts(targets)
        problems = _packageCountsMatch(
            counts, (proc.stdout or "") + "\n" + (proc.stderr or ""), SCANNED_LINE,
            CONTRACT_EXIT_CODES, returncode=proc.returncode,
        )
        # 「退出 0」不是裁决：还要结果与退出码自洽、每个目标都被点数。
        problems += _verdictProblems(proc.returncode, merged_output, payload, targets)
        if VULN_DB_UNREACHABLE.search(merged_output):
            problems.append(
                "漏洞库数据源不可达（读数自述 api.osv.dev 查询失败）——"
                "本条无法给出裁决，扫了 0 个漏洞也不代表无漏洞"
            )
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
        verdict = _verdictProblems(proc.returncode, merged_output, payload, targets)
        if verdict:
            print(
                "[osv] ❌ 扫描器以 1 退出，但拿不到可据以处置的裁决：",
                file=sys.stderr,
            )
            for item in verdict:
                print(f"      - {item}", file=sys.stderr)
            return 2
        print(
            "\n[osv] ❌ 发现未允许的漏洞。处置二选一：\n"
            "  (a) 升级依赖修掉（首选）；\n"
            f"  (b) 确无修复/不可达时，在 {ALLOWLIST} 登记 id+理由+到期日。\n"
            "  注：清单条目过期后本条会重新报红——这是刻意设计，防永久静音。",
            file=sys.stderr,
        )
        return 1
    print(
        f"[osv] 扫描器以契约码 {proc.returncode} 退出——命令与扫描器版本不符，"
        "按基础设施错误收口（不是「发现漏洞」，也不是「无漏洞」）",
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
