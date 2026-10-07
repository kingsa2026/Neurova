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

## 用法

    python scripts/ci/pip_audit_gate.py -r requirements-ci.lock
    python scripts/ci/pip_audit_gate.py -r requirements-full.lock
    python scripts/ci/pip_audit_gate.py -r requirements-full.lock --attempts 5
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time

#: 基础设施错误的**命名证据**（pip-audit 在裁决通路不可用时印在输出里的形态）。
#: 只认这些形态重试；其余非 0 一律按「裁决已成立」处理，立即判红。
#:
#: 为什么按形态而不按退出码：pip-audit 对「有漏洞」与「查不到」都给 1
#: （实测：ReadTimeout 与 Found N known vulnerabilities 同为 exit 1），
#: 按码重试等于把「真有漏洞」也重试三遍，最后照旧判红——只是慢了。
INFRASTRUCTURE_PATTERNS = (
    re.compile(r"ReadTimeout|ConnectTimeout|TimeoutError", re.IGNORECASE),
    re.compile(r"ConnectionError|ConnectionResetError", re.IGNORECASE),
    re.compile(r"Read timed out|timed out", re.IGNORECASE),
    re.compile(r"Temporary failure in name resolution|Name or service not known", re.IGNORECASE),
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
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
    args = parser.parse_args()

    last_code = 2
    last_output = ""
    for attempt in range(1, max(1, args.attempts) + 1):
        code, output = runOnce(args.requirement, args.timeout)
        last_code, last_output = code, output
        if code == 0:
            print(f"[pip-audit] ✅ {args.requirement}: 无未允许的已知漏洞", flush=True)
            return 0
        if not isInfrastructureFailure(code, output):
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
        "  自查顺序：① 漏洞库数据源可达性（osv 服务走 api.osv.dev）；"
        "② 锁文件是否可读；③ 本轮输出末段的原始报错。",
        file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
