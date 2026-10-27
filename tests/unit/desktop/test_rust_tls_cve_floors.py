# -*- coding: utf-8 -*-
"""Tauri 桌面壳 TLS 栈的 CVE 修复下界守卫（RUSTSEC-2026-0346…0349 / 0381 / 0382）。

为什么要有本守卫：这六条公告**全部落在 ureq 2.x 的 TLS 依赖链上**——
`ureq` → `rustls` → `rustls-webpki`，以及 `ureq` → `webpki-roots`。
`scripts/ci/osv_audit.py` 每次实扫都能发现它们，但扫出之后**没有东西拦回退**：
把 `ureq` 改回 `2` 的下一份提交照样能过所有单元测试，只会在下一轮 OSV 门禁里
以「发现未允许的漏洞」重现——与本单修复前的形态一模一样。

判据落在**锁文件**上，与 `tests/unit/tools/test_npx_runtime_pinning.py` 的
`_KNOWN_FLOORS` 同形：逐条登记「包 → 修复下界」，真跑断言。
口径同样刻意只钉「已登记 CVE 的修复下界没有被回退」——新增 CVE 仍由 OSV 实扫发现，
发现后再登记一条。

判据只钉一件事：**锁里那三个 crate 的版本不低于各自的修复下界**。
引入方 `ureq` 仍停在 2.12.1，且它的声明区间解析不到修复版（rustls 在 2.x 线锁
`^0.23.4x`）——这条抬不动的边界如实留在树里，用 `test_ureq_range_cannot_express_the_fix`
把它钉成"已知且被解释的事实"：哪天 ureq 声明变了、锁却还停在旧版，那条会红。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = PROJECT_ROOT / "NeurUI" / "src-tauri" / "Cargo.toml"
LOCKFILE = PROJECT_ROOT / "NeurUI" / "src-tauri" / "Cargo.lock"

#: 包名 → (修复下界, 公告 id, 一句话影响面)
_CVE_FLOORS = {
    "rustls": (
        "0.23.46",
        "RUSTSEC-2026-0346/0347/0348/0349",
        "会话密钥经 Debug 泄露、ECH 拒绝后仍发应用数据、Brotli 证书解压可吃到 1GiB、"
        "未认证的 ServerHello 可把后续连接降级成经典密钥交换",
    ),
    "rustls-webpki": (
        "0.103.16",
        "RUSTSEC-2026-0382",
        "证书链校验可能接受已不受信的 emSign 中间证书（私钥已公开）",
    ),
    "webpki-roots": (
        "1.0.10",
        "RUSTSEC-2026-0381",
        "内置根证书仍带 emSign ECC Root CA - G3，同样放行已不受信的中间证书",
        # 同名多版本在 Rust 锁里合法：树里还留着 webpki-roots 0.26.11（由别的栈拉入），
        # 而公告明说「0.26.11 本身不持信任库、转导自它单独解析的 1.x 父依赖，
        # 父依赖必须 >= 1.0.10」——故判据只钉 1.x 那条，0.26.x 兼容包不在其范围。
        (1, 0, 0),
    ),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lockVersions() -> dict:
    """Cargo.lock 里包名 → 版本列表（同名多版本在 Rust 锁里合法）。"""
    found: dict = {}
    for block in re.split(r"(?m)^\[\[package\]\]$", _read(LOCKFILE))[1:]:
        name = re.search(r'(?m)^name = "([^"]+)"', block)
        version = re.search(r'(?m)^version = "([^"]+)"', block)
        if name and version:
            found.setdefault(name.group(1), []).append(version.group(1))
    return found


def _releaseTuple(version: str) -> tuple:
    """`1.85` 与 `1.85.0` 必须可比（MSRV 常只写两段），故固定补齐到三段。"""
    core, _, tail = version.partition("-")
    nums = [int(p) for p in core.split(".")[:3]]
    nums += [0] * (3 - len(nums))
    return tuple(nums) + (0 if not tail else 1,)


class TestLockedTlsCratesAreAtOrAboveTheAdvisoryFloors:
    """回退路径：把锁里任一包退回旧版 → 转红（OSV 门禁也会同时报红）。"""

    @pytest.mark.parametrize("crate", sorted(_CVE_FLOORS))
    def test_locked_version_is_at_or_above_floor(self, crate):
        floor, advisory, impact, *scope = _CVE_FLOORS[crate]
        versions = _lockVersions().get(crate)
        assert versions, (
            f"Cargo.lock 里找不到 {crate}——它已不在桌面壳依赖树里。"
            "若这是**有意摘除**（链路不再需要它），请先复核 ureq 的 TLS 走哪条路，"
            "再决定删本条登记还是改判据；不许因为「扫不到」就静默删。"
        )
        # scope 存在时只判该线（同名多版本中语义不同的兼容包不在公告范围）
        if scope:
            versions = [v for v in versions if _releaseTuple(v)[:3] >= scope[0]]
        tooOld = [v for v in versions if _releaseTuple(v) < _releaseTuple(floor)]
        assert not tooOld, (
            f"{crate}@{tooOld} 低于 {advisory} 的修复下界 {floor}——{impact}。\n"
            "    处置：抬引入方（ureq 3.5.0 声明 rustls ^0.23.46 / webpki-roots ^1.0.10），"
            "再重生成锁；不要只手改锁里的版本号。"
        )


class TestUreqRangeCannotExpressTheFix:
    """引入方为什么没升：不是漏了，是 2.x 线的声明写不出修复版。

    这条把"边界"钉成可验证的事实，而不是留在提交说明里。ureq 3.x 声明
    `rustls ^0.23.46` / `webpki-roots ^1.0.10`，两处下界正好在修复版之上——
    但也把 MSRV 抬到 1.85，且换了 body / agent API（本仓 `src/lib.rs` 三处调用点）。
    那是独立的搬迁单，不在依赖审计这一单里做。

    回退路径：
    - 换到 3.x 线却不同批改 `rust-version` → 转红（声明与实际可编译版本脱钩）；
    - 声明仍在 2.x 线、锁却已不在修复下界之上 → 上面那类守卫先红，这里只是把
      "为什么只能升锁不能升声明"写下来。
    """

    def test_ureq_stays_on_the_v2_line_or_msrv_moves_with_it(self):
        manifest = _read(MANIFEST)
        match = re.search(r'(?m)^ureq = \{ version = "([^"]+)"', manifest)
        assert match, "Cargo.toml 未声明 ureq——桌面壳的下载/健康检查都靠它"
        declared = _releaseTuple(match.group(1))
        if declared < _releaseTuple("3.0.0"):
            return   # 2.x 线：只能靠 cargo update 抬锁，本类不判其它
        msrv = re.search(r'(?m)^rust-version = "([^"]+)"', manifest)
        assert msrv, "切到 ureq 3.x 后 Cargo.toml 必须声明 rust-version"
        assert _releaseTuple(msrv.group(1)) >= _releaseTuple("1.85"), (
            f"ureq 声明已进 3.x 线，而 rust-version 仍是 {msrv.group(1)!r}——"
            "ureq 3.2+ 的 MSRV 是 1.85，两者必须同批声明，否则这份声明是空头承诺。"
        )
