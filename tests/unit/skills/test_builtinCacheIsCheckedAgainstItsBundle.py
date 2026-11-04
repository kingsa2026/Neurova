# -*- coding: utf-8 -*-
r"""内置包的池内缓存必须先与随包 zip 对表，才准当安装源（§6-512 钉行、§6-514 钉现象、① 落地）。

病灶（读数版）：`market_registry._marketSourceDir` 过去"目录存在就交给安装"，从不校验。
于是同一只发布包两种结果——干净机器现解 zip 装得成；装过一次、盘上留着旧版缓存的机器
从旧版取字节，被安装安全门按 `critical(dangerous_exec)` 拒：旧版
`neurova/skills/market_bundles/adaptive-presentation-studio.zip` 里那份
`scripts/package_check.py` 是裸 `compile(script.read_text(...), str(script), "exec")`，
随包新版同一处早已改成 `ast.parse`（§6-512 逐条 CRC 钉到行）。

边界按已拍的来：**条目带 `bundle_zip` 才归这套机制管**；包名由**持有 catalog 条目的那一层**
（端点用它自己的 importer 问 `builtinBundleName`）递下来，本层与两个纯函数一律不查 catalog、
不碰 `get_market_importer()` 单例——在只该消费参数的位置上新造一次查询，就是第二个事实源，
上一批我正是这么把 `tests/unit/skills` 跑出 9 条红的（§6-518）。

判据全部走**在役入口**（`_marketSourceDir` 与 `builtinCacheDrift`），不 mock 业务对象。
"""

from __future__ import annotations

import ast
import zipfile
from pathlib import Path

import pytest

from neurova.skills.market_importer import (BUILTIN_BUNDLE_DIR, builtinCacheDrift,
                                            read_builtin_bundle)
from neurova.skills.market_registry import _marketSourceDir

REPO = Path(__file__).resolve().parents[3]
SID = "builtin--adaptive-presentation-studio"
BUNDLE = "adaptive-presentation-studio.zip"
#: 两侧共有、且历史上真被改写过的那一项（§6-512 的触发行就在此）
PROBE_MEMBER = "scripts/package_check.py"


def _zipText(name: str = BUNDLE, member: str = PROBE_MEMBER) -> str:
    with zipfile.ZipFile(BUILTIN_BUNDLE_DIR / name) as zf:
        return zf.read(member).decode("utf-8")


def _seedCacheFromBundle(marketRoot: Path) -> Path:
    """把随包 zip 原样解到市场根下当"缓存"（＝缓存与包一致的基准态）。"""
    cache = marketRoot / SID
    cache.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUILTIN_BUNDLE_DIR / BUNDLE) as zf:
        zf.extractall(cache)
    return cache


def test_staleCacheIsNotServedAsInstallSource(tmp_path):
    """缓存里那项与随包不同 ⇒ 交出去的源必须已是随包那版（红在今天：原样交出旧字节）。"""
    cache = _seedCacheFromBundle(tmp_path)
    member = cache / PROBE_MEMBER
    assert member.is_file(), f"前置失效：随包资产里没有 {PROBE_MEMBER}"
    member.write_text("compile(open('x').read(), 'x', 'exec')  # 旧版残留\n", encoding="utf-8")
    assert builtinCacheDrift(BUNDLE, cache) == [PROBE_MEMBER], "漂移检测自己就先瞎了"

    source = _marketSourceDir(SID, tmp_path, BUNDLE)

    assert source is not None, "缓存目录被清掉后没重建——重解失败被当成无字节可装"
    served = (source / PROBE_MEMBER).read_text(encoding="utf-8")
    assert served == _zipText(), (
        f"取源交出去的还是盘上那一版旧字节（前 40 字：{served[:40]!r}）；"
        "安装安全门扫的、装进 agent 目录的都是它——同一版本两种结果由本机盘上状态决定")
    assert builtinCacheDrift(BUNDLE, source) == [], "重解后仍报漂移，下次装还要再解一遍"


def test_freshCacheIsNotRewritten(tmp_path):
    """反向不空转：缓存本就等于随包时**不许**重解。

    没有这一格，"每次都无脑重解"也能过上一格——那会把同步那条路（`market_importer`
    的 `bundle_name` 分支：`rmtree` 后重解）省的力气反向吃回去。重解必 `rmtree`，
    必然换 inode／改 mtime，所以这里只量盘上事实，不 spy 函数名。
    """
    cache = _seedCacheFromBundle(tmp_path)
    marker = cache / PROBE_MEMBER
    before = (marker.stat().st_mtime_ns, marker.stat().st_ino)

    source = _marketSourceDir(SID, tmp_path, BUNDLE)

    assert source is not None
    assert (marker.stat().st_mtime_ns, marker.stat().st_ino) == before, (
        "缓存本就与随包一致，基准文件却被换过了——无脑重解")


def test_entryWithoutBundleIsLeftAlone(tmp_path):
    """非内置条目（`bundle_zip` 为空）一字不动：既有契约"缓存里什么字节就装什么字节"照旧。"""
    other = tmp_path / "aliyun--demo"
    other.mkdir(parents=True)
    (other / "handler.py").write_text("# 测试自造的缓存字节\n", encoding="utf-8")

    source = _marketSourceDir("aliyun--demo", tmp_path, "")

    assert source == other
    assert (source / "handler.py").read_text(encoding="utf-8") == "# 测试自造的缓存字节\n"
    assert builtinCacheDrift("", other) == [], "空包名也被拿去对表"


def test_resolvedSourceLayerNeverLooksUpCatalog():
    """结构面：取源这一层不许再查 catalog、再碰 importer 单例（第二个事实源的入口）。

    上一批的 9 条红就是在这里加了 `get_market_importer()._lookup_catalog_entry(...)`
    造成的——它查的是全局那份 catalog，而调用方手上是自己那份（§6-518）。
    """
    src = (REPO / "neurova" / "skills" / "market_registry.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_marketSourceDir")
    called = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
              for n in ast.walk(target) if isinstance(n, ast.Call)}
    assert "_lookup_catalog_entry" not in called and "get_market_importer" not in called, (
        f"取源层又去查 catalog 了：{sorted(x for x in called if x)}")

    importerSrc = (REPO / "neurova" / "skills" / "market_importer.py").read_text(encoding="utf-8")
    itree = ast.parse(importerSrc)
    for name in ("builtinCacheDrift", "refreshBuiltinCache"):
        fn = next(n for n in itree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        got = {getattr(n.func, "attr", None) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "_lookup_catalog_entry" not in got, f"{name} 又自己查 catalog 了"

    api = (REPO / "neurova" / "api" / "endpoints" / "marketplace.py").read_text(encoding="utf-8")
    assert api.count("bundle_name=importer.builtinBundleName(") == 2, (
        "端点两处 link_market_skill_to_agent 必须都递包名，漏一处就是接了一半")


def test_builtinBundleIsReadable():
    """面自证：本档依赖的随包资产在位（缺了就四格全绿却什么也没判）。"""
    assert read_builtin_bundle(BUNDLE), f"随包资产缺失：{BUNDLE}"
    with zipfile.ZipFile(BUILTIN_BUNDLE_DIR / BUNDLE) as zf:
        assert len([i for i in zf.infolist() if not i.is_dir()]) > 100
    assert _zipText().strip(), f"{PROBE_MEMBER} 读不出内容"
