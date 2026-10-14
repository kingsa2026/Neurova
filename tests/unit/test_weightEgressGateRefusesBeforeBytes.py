# -*- coding: utf-8 -*-
"""跑测层的「真权重出网」门（§6-201 登记的跑测环境缺陷家族，批 44 立）。

实状（本批现算，非记忆）：
- `models/**/*.data`（moss 权重 670MB）是未跟踪件，而入 git 的 5 只 `.onnx` 让
  目录在**任何**仓外 worktree 里都存在 ⇒ 「目录存在＝有权重」这个前置是假的。
  真缺的是那两份 `.data`，而 `ModelDownloader.is_model_available` 早就按
  `required_files` 逐件数着（含 `.data`）——只是没人在用例侧用它。
- 于是干净 worktree 里凡走到 `ensure_model` 的用例都发真 HTTPS 下载 + 退避 sleep：
  实测 `test_tts_lazy_release.py::test_ttl_release_switches_to_light_engine`
  HEAD 仓外 worktree 单格 31s、本树 19.32s，全局 `timeout = 30` 的 thread 法一到点
  就把整场打死 ⇒ A/B 拿不到汇总行（批 42、批 43 各因此烧掉一轮宽域自证）。

门要钉住的不变量：**跑测期谁想在这一层取字节，立刻点名红，而不是等 30 秒墙钟**。
真权重用例改挂 `@pytest.mark.real_model(<模型名>)`，前置由门按 `is_model_available`
单源决定 skip/放行——门对这一族同样关着，缺件不许现场补下载。
"""

import ast
import importlib
import subprocess
from pathlib import Path

import pytest

# 出网那一层的调用点形状按**被调名字**认，不按文件名认：新开第四处下载点也必须被这条扫到
_EGRESS_CALLEES = {"snapshot_download", "hf_hub_download", "HubApi"}
_KNOWN_EGRESS_MODULE = "neurova.tts.model_downloader"


def _gate(request):
    return request.config.pluginmanager.get_plugin("weightEgressGate")


def test_weightEgressGateIsInstalled(request):
    """门得先存在——没装上的后果不是「少一道保险」，而是整场 A/B 没有汇总行。"""
    assert _gate(request) is not None, (
        "跑测层的权重出网门没装上（conftest 未注册 weightEgressGate）："
        "此刻任何走到 ensure_model 的用例都会发真 HTTPS 拉 670MB，"
        "30 秒后 pytest-timeout 的 thread 法打死整场")


def test_everyRegisteredSiteRefusesBeforeAnyBytes(tmp_path, request):
    """登记表里每一处下载点都必须「先点名拒绝、后一个字节也不写」，并被门记下。"""
    gate = _gate(request)
    assert gate is not None, "门没装上（见上一格）"
    assert gate.sites, "门的登记表是空的——覆盖面守卫就此失去对象"

    for moduleName, attr in gate.sites:
        site = importlib.import_module(moduleName)
        modelDir = tmp_path / attr
        with pytest.raises(RuntimeError, match="跑测层禁止真出网取权重"):
            getattr(site, attr)({}, modelDir, None)
        assert not modelDir.exists() or not list(modelDir.iterdir()), (
            f"{moduleName}.{attr} 在被拦下前已往 {modelDir} 落文件——拒绝点太靠后")

    assert len(gate.trips) >= len(gate.sites), (
        f"门没记下这几笔拦截（现记 {gate.trips}）：拒绝桩和门是两份东西")


def test_missingWeightsSkipInsteadOfDownloading(tmp_path, request):
    """real_model 用例的前置只认 is_model_available 一处：缺件＝skip，不现场补下载。"""
    gate = _gate(request)
    assert gate is not None, "门没装上（见第一格）"
    incompleteRoot = tmp_path / "weights"
    incompleteRoot.mkdir()

    with pytest.raises(pytest.skip.Exception, match="真权重不齐"):
        gate.requireWeightsOrSkip(("moss-tts-nano",), baseDir=incompleteRoot)
    assert not any(p.is_file() for p in incompleteRoot.rglob("*")), (
        "缺件那条支路上有落盘——skip 的前置判定顺带取了字节")


def test_egressCallSitesAreAllCoveredByTheGate(request):
    """覆盖面守卫：门登记表与「仓内直接调外部权重下载的那几处」必须逐处相等。

    比的是**调用点**（模块 + 所在模块级函数名），不是模块名——只按模块比的话，
    三处里悄悄删掉一处照样看着「全覆盖」，这条格就白配了（本批变异 M1 实测咬不住）。
    """
    gate = _gate(request)
    assert gate is not None, "门没装上（见第一格）"

    found = _scanEgressCallSites()
    assert (_KNOWN_EGRESS_MODULE, "_download_via_modelscope") in found, (
        f"扫描器看不见已知那处下载点（现读 {sorted(found)}）——"
        "多半漏认了 `from modelscope import snapshot_download as ms_snapshot` 这形")
    registered = set(gate.sites)
    uncovered = sorted(found - registered)
    stale = sorted(registered - found)
    assert not uncovered, (
        f"这些调用点直接取外部权重却没进门：{uncovered}"
        "（加进 tests/conftest.py 的 _WEIGHT_EGRESS_SITES，别留第二条出网路）")
    assert not stale, (
        f"门登记表里有 {stale} 已经不再调下载 API——门在桩一件不存在的事，"
        "请随实状删减，别留着当装饰")


# ---------------------------------------------------------------------------
# 扫描辅助
# ---------------------------------------------------------------------------


def _scanEgressCallSites():
    """按 AST 取「模块级函数里直接调外部权重下载」的 (模块点号路径, 函数名)。"""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "neurova"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.split("\0")
    hits = set()
    for rel in [p for p in tracked if p.endswith(".py")]:
        try:
            tree = ast.parse(Path(rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        moduleName = rel[: -len(".py")].replace("/", ".")
        for fn in tree.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _callsEgress(fn):
                hits.add((moduleName, fn.name))
    return hits


def _callsEgress(node):
    """该子树里有没有对下载 API 的调用——含 `import X as 别名` 之后再调别名那一形。"""
    aliases = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                if alias.name in _EGRESS_CALLEES:
                    aliases.add(alias.asname or alias.name)
        callee = _callName(sub)
        if callee in _EGRESS_CALLEES or callee in aliases:
            return True
    return False


def _callName(node):
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if isinstance(fn, (ast.Name, ast.Attribute)):
        return fn.id if isinstance(fn, ast.Name) else fn.attr
    return None
