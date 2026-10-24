# -*- coding: utf-8 -*-
"""T-04 · 幻影旋钮与虚假默认值（工单集 T-04，只写不读族）。

## 三条实测断点（其中一条把本单的判据形状改了）

1. **`computer_som_snapshot.max_marks` 是幻影旋钮**：schema 里声明
   （`builtin_tools.py`）、放行表里允许（`tool_executor.py:_COMPUTER_TOOL_PARAM_KEYS`），
   但**全仓无任何读取点**——`mark_screenshot(png, detector=None)` 根本没有预算形参，
   唯一真值是 `som.py` 的模块常量 `_MAX_MARKS = 60`。模型传什么都被无声忽略。
   ⇒ 处置：**删声明**（不是补实现）。本仓协作红线禁止"只写不读的配置"；
   删掉后 `normalize_computer_params` 的未知键拒绝会让它**响亮地失败**，
   比"能传但没用"更可诊断。没有真实需求证据前不为其新建预算通路。

2. **`browser_dom_snapshot` 的"默认节点 1200/深度 32"是虚假默认值**：
   `_trim_snapshot_tree` 的实况是"不传预算原样透传"（`browser_manager.py:796`），
   两个后端都没有 1200/32 这两个默认值。⇒ 把描述改成实话。

3. **实现侧 docstring 承诺了一个类型上无法兑现的事**：`dom_snapshot` 的 docstring
   写"超限裁剪并如实标注 truncated"，但 `BrowserResult` **没有 `truncated` 字段**，
   `_trim_snapshot_tree` 算出的第二个返回值在调用处被丢弃（`tree, _truncated = ...`）。
   ⇒ 本单只把承诺改成实况并登记待办（要如实上报须先给 BrowserResult 加承载字段）——
   那是跨多个方法的数据结构变更，不混进"修谎报"这一批。

## 判据形状：不修"我找到的那一个"，而是让整类变红

`test_noAdvertisedParamIsUnread` 把参数面当作可枚举集合，逐个查它有没有读取点。
配两条对照防纸糊：正对照（已知未读的名字必须被算出）与负对照（已知被读的名字
不得被算出）——本会话已在两处栽过"探测函数恒真/恒假"，判据自带对照是硬要求。

**范围边界（显式，不静默放宽）**：只扫 `computer_*` / `browser_*` 这一族。
其余 51 个内置工具的参数面没有同等强度的读取点索引，扩范围会先产生误报，
留作后续单独一轮（见工单集）。

## 成本形状（§6-402 批 K 改的就是这一处，判据本身没变）

原实现是「每个广告参数 × 全仓每个 `.py` × 4 条正则」，且每参数各读一遍盘：
单跑本格实测 **28.60s–37.11s**（同一台机器、同一份代码，两次差 8.5s——机器负载
就够把它推过墙）。`pyproject.toml` 的 `timeout=30.0` 配的是 `method=thread`，
而 thread 法**打断不了正在跑的 Python 栈**，pytest-timeout 的处理是 dump 之后
终止整个进程 ⇒ `pytest tests/unit` 在 14% 处直接消失、没有汇总行（实测 exit=1，
2026-10-22 夜那轮）。**一格慢到超时不是这一格红，是把整场跑测连带打死**——
本仓此前所有"整批跑"的数因此不可信，这也是全仓预存红一直数不齐的原因之一。

改法只动成本、不动语义：读盘走 `tests/ast_scan`（按内容戳缓存，同进程一份源码
只读一次），扫法从「按参数扫语料」倒过来成「按语料扫参数」——4 条读法各做**一次**
全量 alternation，命中数按名字归账。于是总代价与参数个数无关。
这个形状由 `test_sweepCostIsBoundToCorpusNotToParamCount` 钉住（数的是**读盘次数**，
不数秒——判据不与机器快慢捆绑，理由见 `tests/unit/test_ci_ast_scan_budget_guard.py` 头部）。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.tool_executor import _COMPUTER_TOOL_PARAM_KEYS, COMPUTER_USE_TOOLS
from tests import ast_scan

REPO = pathlib.Path(__file__).resolve().parents[3]
PROD_ROOT = REPO / "neurova"

#: 对照名字：一个绝不可能被读、一个已知必然被读（见 `test_paramReadDetectorIsNotVacuous`）
CONTROL_NAMES = frozenset({"url", "zzz_definitely_not_a_real_param"})

#: 四类"读法"。模式 4 偏保守（任何同名形参/解包位置都算读），故本判据抓的是
#: "完全没人碰过这个名字"的极端形态，抓不到"名字被碰过但语义不是读这个参数"。
_READ_SHAPES = (
    r'\.get\(\s*["\']({names})["\']',
    r'\[\s*["\']({names})["\']\s*\]',
    r'\b({names})\s*=',
    r'\b({names})\s*(?::|=|,|\))',
)


def _advertisedNames() -> list:
    names = set(CONTROL_NAMES)
    for tool in COMPUTER_USE_TOOLS:
        names |= set(_COMPUTER_TOOL_PARAM_KEYS.get(tool, frozenset()))
    # 长名在前：交替式里短名先试会在 `url=` 撞上 `url_limit=` 时靠回溯纠正，
    # 但顺序确定化省掉回溯成本，也避免今后加前缀同名参数时行为随定义顺序漂移。
    return sorted(names, key=lambda n: (-len(n), n))


def _sweepReadCounts() -> dict:
    """一遍扫完全仓，返回 `{名字: 命中次数}`——代价与参数个数无关。

    声明面不算读：`builtin_tools.py` 整个跳过（schema 声明处），
    `tool_executor.py` 去掉放行表那几行（`frozenset({`）后再数。
    """
    patterns = [
        re.compile(shape.format(names="|".join(re.escape(n) for n in _advertisedNames())))
        for shape in _READ_SHAPES
    ]
    counts: dict = dict.fromkeys(_advertisedNames(), 0)
    corpus = ast_scan.sourceRefsUnder(PROD_ROOT, ".py")
    # 面自证：先证语料非空，再谈「计数为零」（根被改窄时零计数与干净同形）。
    assert len(corpus) > 100, f"扫描面现读 {len(corpus)} 个文件——PROD_ROOT 指错时本判据恒绿"
    for ref in corpus:
        if ref.path.name == "builtin_tools.py":
            continue
        text = ref.code
        if ref.path.name == "tool_executor.py":
            text = "\n".join(ln for ln in text.splitlines() if "frozenset({" not in ln)
        for pat in patterns:
            for name in pat.findall(text):
                counts[name] += 1
    return counts


class TestPhantomKnobSweep:

    def test_maxMarksIsGoneEverywhere(self):
        """幻影旋钮删干净：schema、放行表、执行体三处都不该再有它。"""
        assert "max_marks" not in str(_BUILTIN_SCHEMAS)
        assert "max_marks" not in str(_COMPUTER_TOOL_PARAM_KEYS)
        # 面自证：本格断的是「零残留」，而零残留既可能是「真删干净」也可能是「根写窄了扫了个空」。
        scanned = len(ast_scan.filesUnder(PROD_ROOT, ".py"))
        assert scanned > 700, f"生产树扫描面现读 {scanned} 个 .py，低于下限＝PROD_ROOT 写错本格恒绿"
        # hints 预筛是充分条件：连 "max_marks" 这七个字节都没出现的文件不可能命中
        leftovers = [
            ref.path.relative_to(REPO).as_posix()
            for ref in ast_scan.sourceRefsUnder(PROD_ROOT, ".py", hints=("max_marks",))
        ]
        assert not leftovers, f"max_marks 仍有残留引用：{leftovers}"

    def test_unknownParamOnSomSnapshotNowFailsLoudly(self):
        """删声明的收益要可验证：传 max_marks 必须被拒，而不是被无声忽略。"""
        from neurova.tool_executor import normalize_computer_params

        with pytest.raises(ValueError) as exc:
            normalize_computer_params("computer_som_snapshot", {"max_marks": 5})
        assert "max_marks" in str(exc.value), "拒绝信息没点名是哪个非法参数"

    def test_noAdvertisedParamIsUnread(self):
        """治理面每个工具的每个广告参数，都必须有读取点。"""
        counts = _sweepReadCounts()
        unread = []
        for tool in sorted(COMPUTER_USE_TOOLS):
            for param in sorted(_COMPUTER_TOOL_PARAM_KEYS.get(tool, frozenset())):
                if counts[param] == 0:
                    unread.append(f"{tool}.{param}")
        assert not unread, f"这些参数被广告给模型却无人读取（幻影旋钮）: {unread}"

    def test_paramReadDetectorIsNotVacuous(self):
        """正对照 + 负对照：探测函数本身必须先被证明能用，上一条的绿才有意义。"""
        counts = _sweepReadCounts()
        # 负对照：已知被读的参数，不得算成未读
        assert counts["url"] > 0, "探测连 browser_navigate.url 都认不出 ⇒ 恒假"
        # 正对照：一个绝不可能被读的名字，必须算成 0
        assert counts["zzz_definitely_not_a_real_param"] == 0, "探测恒真"

    def test_sweepCostIsBoundToCorpusNotToParamCount(self):
        """成本判据：再扫一遍不得多读一次盘，但必须**确实**走了一遍缓存的语料。

        数的是读盘次数而不是秒数——墙钟会把判据与机器快慢捆绑，那是本仓点名过的
        近亲形态（理由见 `test_ci_ast_scan_budget_guard.py` 头部）。
        两条断言成对，缺一不可，且**与用例执行顺序无关**（本文件里别的格会先把
        语料读进缓存，所以不能拿"第一遍必须 miss 若干"当前提——我第一版就是这么写的，
        单独跑这一格时才暴露它是顺序依赖的假前提）：

        - `misses` 不涨：形状若回退成「每参数各扫一遍全仓并各自读盘」（旧实测
          28.6s–37.1s，撞 `timeout=30 method=thread` 会把整场跑测终止），这里会红；
        - `hits` 至少涨满一个语料：否则"没多读盘"可能只是**根本没走共享预算**
          （自己 `read_text` 的话，缓存计数一动不动，只看第一条就漏放行）。
        """
        corpus = len(ast_scan.filesUnder(PROD_ROOT, ".py"))
        assert corpus >= 800, (
            "生产语料现读 %d 个 .py——PROD_ROOT 指错时『没多读盘』会假绿（面自证）" % corpus)
        cache = ast_scan._cachedCode
        if not hasattr(cache, "cache_info"):
            pytest.fail("ast_scan._cachedCode 不再是带 cache_info 的缓存入口——"
                        "本格的判据前提没了，要么改回共享预算、要么连同本格一起重新设计")

        before = cache.cache_info()
        first = _sweepReadCounts()
        mid = cache.cache_info()
        second = _sweepReadCounts()
        after = cache.cache_info()

        assert second == first, "同一份代码扫两遍结果不同 ⇒ 扫法被外部状态污染，判据不可复现"
        assert after.misses == mid.misses, (
            f"第二遍又多读了 {after.misses - mid.misses} 个文件 ⇒ 缓存没生效，"
            "每调一次判据就重读全仓（正是把整场跑测打死的那个形状）"
        )
        gainedHits = after.hits - mid.hits
        assert gainedHits >= corpus, (
            f"第二遍只从缓存拿到 {gainedHits} 次命中，而语料有 {corpus} 个文件 ⇒ "
            "这一遍压根没走共享读盘口，「没多读盘」是假象（自己 open 的文件不进缓存计数）"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
