#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python 依赖漏洞门禁（pip-audit）——把「网络抖动」与「真有漏洞」分开。

## 为什么需要它（本次 CI 红的根因）

构建 `cnb-tec-1k4b4771b` 的 `dependency-audit` 腿红在第二段：

    $ python -m pip_audit -r requirements-full.lock --progress-spinner off
    requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443):
        Read timed out. (read timeout=15)
    Finished, code: 1, duration: 46.6s

**这条红与本次提交一个字的关系都没有**：pip-audit 默认向 pypi.org 现查每个包的
公告，而 15s 的 socket 读超时是它的内置默认（`--timeout` 的默认值）。一次读超时
= 退出码 1 = 阻塞红灯，读日志的人只能原地重跑——这正是本仓在
`scripts/ci/osv_audit.py` 里已经消灭过的形态（见其顶栏「裁决不依赖远端可实时到达」
一节），只是当时只收口了 OSV 那一路，pip-audit 这一路漏在体系外。

## 修法：三件事，都不放宽任何判据

1. **换漏洞库**：`--vulnerability-service osv`。pip-audit 的 `pypi` 服务要对每个包
   各发一次 `pypi.org/pypi/<pkg>/json`，而 `osv` 服务走 `api.osv.dev/v1/querybatch`
   ——**一次批量查询**，往返次数从「包数」降到「1」。同仓 `scripts/ci/osv_audit.py`
   早就把跨生态扫描收口到同一份 OSV 库，Python 侧这次跟着同源，不再有两套漏洞库
   口径（`AGENTS.md` 修复教义第 6 条）。
2. **超时按「一次查询」而不是「一次读」给足**：`--timeout 60`。15s 是 pip-audit 的
   内置默认，与本仓无关；把一条随网络抖动的读超时当判据，就是本单要消灭的形态。
3. **只对「基础设施错误」重试**：读超时/SocketTimeout/DNS 失败重试（默认 3 次、
   指数退避）；**「找到漏洞」立即判红、绝不重试**——重试一条已经成立的裁决，
   等于把判据交给重试次数。

退出码语义与 `scripts/ci/osv_audit.py` 逐字同源（同一套词汇，不新造第二套）：

    0 = 无未允许的漏洞
    1 = 有未允许的漏洞
    2 = 基础设施错误（裁决通路不可用，本轮给不出结论）

**退出码 2 不是「通过」**：它响亮说出「本轮没查成」，与「查了、没有漏洞」在日志里
可分辨。这与本仓门禁的一贯纪律一致：不许把「跑不起来」当成「没问题」。

## 修法第二段（Issue #357）：裁决通路改绑离线库

第一段（Issue #354）把「一次读超时」从红灯变成可重试，但**裁决通路仍只有直连
`api.osv.dev` 一条**——`169` 包的全量锁就是 169 次 POST，长链路上必然撞上抖动。
构建 `cnb-a99-1k4bpgeim` 的红即此：同一构建里 85 包的 `requirements-ci.lock` 过了、
169 包的 `requirements-full.lock` 撞上连接失败，3 次重试耗尽后按基础设施错误退 2
——定性诚实了，但仍然**阻塞合并**，而它与提交内容一个字的关系都没有。

故裁决通路收口为与 `osv_audit.py` 同形的 `resolveVerdictChannel()`：

* 离线库在场（`~/.cache/osv-scalibr/PyPI/all.zip`，与 OSV 那一路**同一份缓存**）
  → 走离线口径（OSV-Scanner `--offline --offline-vulnerabilities`），
  裁决**不再依赖任何远端**；
* 离线库不在场 → 回退直连 pip-audit，并**点名缺哪一份**（可读、可复算）。

`--verdict-channel` 只在自证时显式钉住一条口径，CI 用默认的 `auto`。

## 用法

    python scripts/ci/pip_audit_gate.py -r requirements-ci.lock
    python scripts/ci/pip_audit_gate.py -r requirements-full.lock
    python scripts/ci/pip_audit_gate.py -r requirements-full.lock --attempts 5
    # 自证：显式钉住一条口径（CI 不用）
    python scripts/ci/pip_audit_gate.py -r requirements-full.lock --verdict-channel offline
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: 基础设施错误的**命名证据**（pip-audit 在裁决通路不可用时印在输出里的形态）。
#: 只认这些形态重试；其余非 0 一律按「裁决已成立」处理，立即判红。
#:
#: 为什么按形态而不按退出码：pip-audit 对「有漏洞」与「查不到」都给 1
#: （实测：ReadTimeout 与 Found N known vulnerabilities 同为 exit 1），
#: 按码重试等于把「真有漏洞」也重试三遍，最后照旧判红——只是慢了。
#:
#: **`Could not connect` 这一条不是补出来的措辞，是漏掉的形态。** 实测（本次
#: 构建 `cnb-qr5-1k4bor0bt` 的 `audit CI locked set`）：pip-audit 的服务层把
#: requests 的连接异常收成自家 `ConnectionError`，`_cli` 只印两行——
#:
#:     ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed
#:     ERROR:pip_audit._cli:Tip: your network may be blocking this service. …
#:
#: 前几版判据盯的是 requests/urllib3 的**异常类名与底层措辞**
#: （`ReadTimeout` / `Read timed out` / `Failed to resolve` / `Name or service
#: not known`），而这一条出口把它们全吃掉了，只剩「连不上」这句自述——于是
#: `isInfrastructureFailure` 返回 False，门禁把它读成「裁决已成立」直接退 1，
#: 一次网络抖动就成了阻塞红灯，与提交内容一个字的关系都没有。
#: 根因是「形态清单以库的内部类名为锚」，不是「少列了一条」——故清单按
#: **裁决通路是否可用**这件事收口（`Could not connect` / `blocking this service`），
#: 并保留底层措辞作为冗余证据（网络栈换实现时仍认得出来）。
INFRASTRUCTURE_PATTERNS = (
    # 裁决通路不可用：pip-audit 自己的自述（服务名与实现无关，跨 osv/pypi 都印）。
    re.compile(r"Could not connect", re.IGNORECASE),
    re.compile(r"blocking this service", re.IGNORECASE),
    # 底层网络栈措辞（连不上/超时/解析不了的具体形态）。
    re.compile(r"ReadTimeout|ConnectTimeout|TimeoutError", re.IGNORECASE),
    re.compile(r"ConnectionError|ConnectionResetError", re.IGNORECASE),
    re.compile(r"Read timed out|timed out", re.IGNORECASE),
    re.compile(r"Temporary failure in name resolution|Name or service not known", re.IGNORECASE),
    re.compile(r"Failed to resolve", re.IGNORECASE),
    re.compile(r"SSL(?:Error)?|CERTIFICATE_VERIFY_FAILED", re.IGNORECASE),
    re.compile(r"503 Service Unavailable|502 Bad Gateway|504 Gateway Time-out"),
    re.compile(r"RemoteDisconnected", re.IGNORECASE),
)

#: 判定「裁决已成立」的形态：这几行一出现，无论退出码是什么都不再重试。
VERDICT_PATTERNS = (
    re.compile(r"No known vulnerabilities found", re.IGNORECASE),
    # 单复数都要认：pip-audit 输出 "Found 1 known vulnerability in 1 package"
    # 与 "Found 2 known vulnerabilities in 1 package" 两种形态（实测）。
    re.compile(r"Found \d+ known vulnerabilit(?:y|ies)", re.IGNORECASE),
)

#: 默认重试次数（含首次）。3 次是「抖动一次还能救回」与「真不可达时不要空转」的折中：
#: 每次最长 60s 读超时，最坏 3 × 60s ≪ 门禁 stage 的 20m 预算。
DEFAULT_ATTEMPTS = 3
#: 单次查询的 socket 超时（秒）。**必须高于 pip-audit 的 15s 内置默认**：
#: 换 OSV 服务后一次查询要覆盖整份锁文件（不是单包），15s 本就偏紧；
#: 而这个值的本分是「别把一次网络抖动变成阻塞红灯」。
#: 判据 `tests/unit/test_pip_audit_gate.py` 只钉「> 15」，不钉具体秒数
#: （具体秒数随机器与负载漂移，结构性的是「不得等于那个把抖动编码成红灯的值」）。
DEFAULT_TIMEOUT = 60
#: 重试退避基数（秒）：第 n 次重试前等 `RETRY_BACKOFF * 2**(n-1)`。
RETRY_BACKOFF = 5.0

# ── 离线裁决通路：让 Python 锁的裁决不再绑在 api.osv.dev 的实时可达性上 ────────
#
# 为什么必须补这一段（Issue #357）：本门禁此前的**唯一**裁决通路是
# `python -m pip_audit --vulnerability-service osv`，即对每包各发一次 POST 到
# `api.osv.dev`。169 包的全量锁就是 169 次往返，长链路上必然撞上抖动，而
# `api.osv.dev` 在 runner 上被拦时，门禁只能按基础设施错误退出 2 —— 那仍是
# **阻塞红灯**，与提交内容一个字的关系都没有。
#
# 实证（构建 `cnb-a99-1k4bpgeim` 的 `audit full runtime locked set`，同一构建里
# 85 包的 `requirements-ci.lock` 过了、169 包的 `requirements-full.lock` 没过）：
#
#     ERROR:pip_audit._cli:Could not connect to OSV's vulnerability feed
#     [pip-audit] ⚠️ 第 1 次为基础设施错误（裁决未成立），5s 后重试（共 3 次）
#     [pip-audit] ❌ requirements-full.lock: 3 次尝试均未取得裁决……
#
# 修法与同仓 `scripts/ci/osv_audit.py` **同源**（其顶栏「裁决不依赖远端可实时到达」
# 一节，2026-09-22 A/B 实测：`api.osv.dev` 指到必挂 IP + 清空缓存 → 线上口径
# 3/3 红、离线口径 3/3 全绿）：改走 OSV-Scanner 的**离线漏洞库**
# （`--offline --offline-vulnerabilities`）。判据来源与 OSV 那一路是**同一份
# `PyPI/all.zip`**，CI 两侧已挂的 `~/.cache/osv-scalibr` 卷直接复用——不新造
# 第二套缓存口径（AGENTS.md 修复教义第 6 条）。
#
# 实测（本机，同一份缓存）：
#   * `requirements-ci.lock`  → `found 85 packages`，离线退 0
#   * `requirements-full.lock`→ `found 169 packages`，离线退 0（零网络）
#   * `urllib3==1.26.0`      → 离线报出 24 条命中（判据未退化）
#   * 反向控制：直连口径在同一份全量锁上**解析失败**（`cuda-toolkit` 是本地
#     wheel，deps.dev 解析不到）→ 离线口径反而更可信

#: 离线漏洞库缓存落点。与 `scripts/ci/osv_audit.py` 的 `OSV_DB_CACHE` **同值**：
#: 两侧共用同一份卷，不新造第二套缓存口径（改一处须改另一处，由守卫逐字校验）。
OSV_DB_CACHE = Path.home() / ".cache" / "osv-scalibr"

#: 本门禁只关心 PyPI 这一个生态的离线库（`osv_audit.py` 管 crates.io / npm）。
OFFLINE_ECOSYSTEM = "PyPI"

#: OSV-Scanner 的离线 flag。**必须成对**：只给 `--offline` 而不给
#: `--offline-vulnerabilities` 时扫描器退回「查本地缓存」，缓存缺失时报
#: `no offline version of the OSV database is available` 并退 127——
#: 那正是本门禁要消灭的形态（127 与「命令不成形」同码同形）。
OFFLINE_FLAGS = ("--offline", "--offline-vulnerabilities")

#: OSV-Scanner 比对 requirements 文件时**按文件名认解析器**：实测
#: `requirements.txt` / `requirements-ci.txt` 都被认出，
#: 而 `requirements-ci.lock` 报
#: `could not determine extractor suitable to this file`。
#: 故离线通路把锁文件暂存成 `<原名>.txt` 副本再交给扫描器——只改文件名，
#: 内容逐字不动，包数对账口径因此可复算（实测 85 / 169 与 `==` 行数一致）。
#: 暂存实现**只有一处**：`osv_audit.scannerReadableAlias()`（预取与门禁共用），
#: 本脚本不另抄一份，避免「预取改名规则」与「扫描改名规则」分叉。


def offlineDatabaseProblems() -> list:
    """离线库是否已备齐，返回问题清单（空 = 可走离线）。

    判据是**文件在场**，不是「下载过」——与 `osv_audit.py` 的
    `offlineDatabaseProblems()` 同口径：过期库仍好过一个不可达的库，
    过期只漏报新公告，不可达会让门禁在「网络抖动」与「真有漏洞」之间无从分辨。
    """
    db = OSV_DB_CACHE / OFFLINE_ECOSYSTEM / "all.zip"
    if not db.is_file():
        return [f"离线库缺失: {db}（生态 {OFFLINE_ECOSYSTEM}）"]
    return []


def resolveVerdictChannel() -> tuple:
    """单源决定本次裁决走离线库还是直连，返回 `(用离线吗, 问题清单)`。

    与 `osv_audit.py` 的 `resolveVerdictChannel()` 同形：缓存齐 → 走离线
    （不再依赖 `api.osv.dev`）；缓存不齐 → **回退直连并点名缺哪一份**。

    为什么回退而不判红：预取是 best-effort（CI 里 `|| true`），门禁若要求
    「缓存必须齐」，就把一条**允许失败**的前置步骤变成了红灯来源，而那与
    「真有未允许漏洞」在合并流程里长得一样——读日志的人仍只能重跑，
    正是本单要消灭的形态。
    """
    problems = offlineDatabaseProblems()
    return (not problems), problems


def _scannerModule():
    """按路径加载同目录的 `osv_audit.py`（它与本脚本同为 CI 脚本，不是包内模块）。

    复用而不重写：OSV-Scanner 的下载、SHA256 指纹校验、绝对路径归一、
    平台判定都已在那边落定，这里再抄一份就是第二份实现（教义第 6/7 条）。
    """
    path = Path(__file__).resolve().parent / "osv_audit.py"
    spec = importlib.util.spec_from_file_location("osv_audit_shared_by_pip_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolveScannerBinary() -> Path:
    """拿到可执行的 OSV-Scanner 绝对路径（下载 / 指纹校验都在 `osv_audit.py`）。

    解析顺序与 `osv_audit._resolve_scanner()` 同源：先认 `OSV_SCANNER_BIN`，
    再走官方 release 下载并核对 SHA256。复用而不重写——二进制指纹表、
    平台判定、绝对路径归一都已在那边落定（教义第 6/7 条）。
    """
    return _scannerModule()._resolve_scanner()


def buildOfflineCommand(requirement: str, binary: str = "") -> list:
    """拼出一次**离线**扫描调用（判据来源是本地 `PyPI/all.zip`）。

    与 `buildCommand()` 是一对：`buildCommand` 是直连口径（pip-audit → api.osv.dev），
    本函数是离线口径（OSV-Scanner → 本地库）。两条口径的裁决词汇同源（0/1/2）。

    `binary` 留空时现取（会触发下载/指纹校验，需网络）；自证场景传入固定路径，
    这样「命令形态」这件事能在不起扫描器的前提下被单独钉住。
    """
    return [
        binary or str(resolveScannerBinary()), "scan", "source",
        "--lockfile", requirement,
        "--format", "json",
        *OFFLINE_FLAGS,
    ]


def runOfflineOnce(requirement: str) -> tuple:
    """跑一次离线扫描，返回 `(退出码, 合并输出)`。

    锁文件先**暂存成 `<原名>.txt`**：扫描器按文件名认解析器，`.lock` 认不出
    （实测报 `could not determine extractor suitable to this file`）。
    只改名字、内容逐字不动，且暂存副本随临时目录一并清理。
    """
    with tempfile.TemporaryDirectory(prefix="pip-audit-offline-") as stage:
        staged = _scannerModule().scannerReadableAlias(Path(requirement), Path(stage))
        cmd = buildOfflineCommand(str(staged))
        print(f"[pip-audit] (离线库) $ {' '.join(cmd)}", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    merged = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    print(merged, flush=True)
    return proc.returncode, merged


def isOfflineInfrastructureFailure(returncode: int, output: str) -> bool:
    """离线口径下「没查成」的形态。

    离线时不该出现网络错误；真出现只有一种解释：扫描器二进制没能下载/执行，
    或本地库损坏。故**非契约码**（0/1 之外的任何码）一律按基础设施错误收口，
    并沿用同一套形态清单点名。这与 `osv_audit.py` 的 `CONTRACT_EXIT_CODES`
    同口径（那边是 `(0, 1, 65)`，这边没有入参错误这一路，故为 `(0, 1)`）。
    """
    if returncode in (0, 1):
        return False
    return True


def isInfrastructureFailure(returncode: int, output: str) -> bool:
    """这次非 0 退出是「没查成」还是「查成了、有漏洞」？

    判据顺序刻意如此：**先看有没有成立裁决**。一条 `Found N known vulnerabilities`
    已经把结论写在输出里了，此时输出里可能还夹着上一轮的 timeout 字样（重试后的
    累积输出），按形态重试会把它当成抖动——这正是「重试一条已成立的裁决」。
    """
    if returncode == 0:
        return False
    if any(pattern.search(output) for pattern in VERDICT_PATTERNS):
        return False
    return any(pattern.search(output) for pattern in INFRASTRUCTURE_PATTERNS)


def buildCommand(requirement: str, timeout: int) -> list:
    """拼出一次 pip-audit 调用。单一落点：自证与正式两次共用同一拼法。"""
    return [
        sys.executable, "-m", "pip_audit",
        "-r", requirement,
        "--progress-spinner", "off",
        # OSV 而非 PyPI：一次批量查询取代「每包一次」的网络往返（见顶栏修法第 1 条）。
        "--vulnerability-service", "osv",
        "--timeout", str(timeout),
    ]


def runOnce(requirement: str, timeout: int) -> tuple:
    """跑一次 pip-audit，返回 `(退出码, 合并输出)`。"""
    cmd = buildCommand(requirement, timeout)
    print(f"[pip-audit] $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    merged = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    print(merged, flush=True)
    return proc.returncode, merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Python 依赖漏洞门禁（pip-audit 包装）")
    parser.add_argument("-r", "--requirement", required=True, help="待审计的锁文件")
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS,
                        help=f"含首次的总尝试次数（默认 {DEFAULT_ATTEMPTS}）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"pip-audit 的 socket 超时秒数（默认 {DEFAULT_TIMEOUT}；"
                             "pip-audit 自身默认 15s，与「一次批量查询」的耗时不相称）")
    parser.add_argument("--verdict-channel", choices=("auto", "offline", "live"),
                        default="auto",
                        help="裁决通路：auto = 缓存齐走离线、不齐回退直连（CI 用法）；"
                             "offline/live 供自证显式钉住一条口径，不由 CI 使用")
    args = parser.parse_args()

    # 裁决通路单源决定（与 osv_audit.py 的 resolveVerdictChannel 同形）：
    # 离线库在场 → 离线口径（不依赖 api.osv.dev）；不在场 → 直连口径并点名缺哪一份。
    # `--verdict-channel` 只在自证时收窄范围，不改「自动」这条默认路径的判据。
    offline, problems = resolveVerdictChannel()
    if args.verdict_channel == "live":
        offline, problems = False, ["显式指定直连口径（--verdict-channel live，自证用）"]
    elif args.verdict_channel == "offline" and not offline:
        print(f"[pip-audit] ❌ 显式要求离线口径，但离线库缺失（{problems}）",
              file=sys.stderr, flush=True)
        return 2
    if offline:
        print(
            f"[pip-audit] 裁决通路: 离线库（{OSV_DB_CACHE / OFFLINE_ECOSYSTEM / 'all.zip'}，"
            "不依赖 api.osv.dev）",
            flush=True,
        )
        runner = lambda: runOfflineOnce(args.requirement)  # noqa: E731
        failedOnInfra = isOfflineInfrastructureFailure
    else:
        for item in problems:
            print(f"[pip-audit] ⚠️ 离线库未备齐，回退直连 api.osv.dev：{item}",
                  file=sys.stderr, flush=True)
        print("[pip-audit] 裁决通路: 直连 api.osv.dev", flush=True)
        runner = lambda: runOnce(args.requirement, args.timeout)  # noqa: E731
        failedOnInfra = isInfrastructureFailure

    for attempt in range(1, max(1, args.attempts) + 1):
        code, output = runner()
        if code == 0:
            print(f"[pip-audit] ✅ {args.requirement}: 无未允许的已知漏洞", flush=True)
            return 0
        if not failedOnInfra(code, output):
            # 裁决已成立（有漏洞，或不是可重试的基础设施形态）：立即判红，不重试。
            print(
                f"[pip-audit] ❌ {args.requirement}: 裁决已成立（退出码 {code}），不重试。\n"
                "  处置二选一：\n"
                "  (a) 升级依赖修掉（首选，公告晚于上次锁收口时基本都是这条）；\n"
                "  (b) 确无修复/不可达时，在 scripts/ci/osv-allowlist.toml 登记 "
                "id + 理由 + 到期日（与 OSV 那一路共用同一份清单，不新造第二份）。",
                file=sys.stderr, flush=True)
            return 1
        if attempt < args.attempts:
            backoff = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(
                f"[pip-audit] ⚠️ 第 {attempt} 次为基础设施错误（裁决未成立），"
                f"{backoff:.0f}s 后重试（共 {args.attempts} 次）",
                file=sys.stderr, flush=True)
            time.sleep(backoff)

    print(
        f"[pip-audit] ❌ {args.requirement}: {args.attempts} 次尝试均未取得裁决——"
        "按**基础设施错误**收口（退出码 2，不是「无漏洞」，也不是「发现漏洞」）。\n"
        "  自查顺序：① 离线库是否已预取（"
        f"{OSV_DB_CACHE / OFFLINE_ECOSYSTEM / 'all.zip'}）；"
        "② 直连口径下再看漏洞库数据源可达性（api.osv.dev）；"
        "③ 锁文件是否可读；④ 本轮输出末段的原始报错。",
        file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
