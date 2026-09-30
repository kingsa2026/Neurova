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
"""

from __future__ import annotations

import pathlib
import re

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.tool_executor import _COMPUTER_TOOL_PARAM_KEYS, COMPUTER_USE_TOOLS

REPO = pathlib.Path(__file__).resolve().parents[3]
PROD_DIRS = [REPO / "neurova"]


def _productionSources() -> list:
    return [p for d in PROD_DIRS for p in d.rglob("*.py")]


def _paramReadHits(paramName: str, sources: list) -> int:
    """该参数名在**声明面之外**被读取的次数。

    声明面 = `builtin_tools` 的 schema 与 `tool_executor` 的放行表；它们出现名字不算读。
    探测**偏保守（宁可漏报不可误报）**：模式 4 会把任何同名形参/解包位置算成读，
    因此本判据抓的是"完全没人碰过这个名字"的极端形态（max_marks 正是这种），
    抓不到"名字被碰过但语义不是读这个参数"的更细情况。
    这个偏向由 test_paramReadDetectorIsNotVacuous 的两条对照钉住，不假装它是严格可达性分析。
    """
    patterns = [
        rf'\.get\(\s*["\']{re.escape(paramName)}["\']',
        rf'\[\s*["\']{re.escape(paramName)}["\']\s*\]',
        rf'\b{re.escape(paramName)}\s*=',
        rf'\b{re.escape(paramName)}\s*(?::|=|,|\))',
    ]
    hits = 0
    for py in sources:
        if py.name == "builtin_tools.py":
            continue  # schema 声明处
        text = py.read_text(encoding="utf-8", errors="replace")
        if py.name == "tool_executor.py":
            # 放行表那一行不算读
            text = "\n".join(ln for ln in text.splitlines() if "frozenset({" not in ln)
        for pat in patterns:
            hits += len(re.findall(pat, text))
    return hits


class TestPhantomKnobSweep:

    def test_maxMarksIsGoneEverywhere(self):
        """幻影旋钮删干净：schema、放行表、执行体三处都不该再有它。"""
        assert "max_marks" not in str(_BUILTIN_SCHEMAS)
        assert "max_marks" not in str(_COMPUTER_TOOL_PARAM_KEYS)
        assert not any("max_marks" in p.read_text(encoding="utf-8", errors="replace")
                       for p in _productionSources()), "max_marks 仍有残留引用"

    def test_unknownParamOnSomSnapshotNowFailsLoudly(self):
        """删声明的收益要可验证：传 max_marks 必须被拒，而不是被无声忽略。"""
        from neurova.tool_executor import normalize_computer_params

        with pytest.raises(ValueError) as exc:
            normalize_computer_params("computer_som_snapshot", {"max_marks": 5})
        assert "max_marks" in str(exc.value), "拒绝信息没点名是哪个非法参数"

    def test_noAdvertisedParamIsUnread(self):
        """治理面每个工具的每个广告参数，都必须有读取点。"""
        sources = _productionSources()
        unread = []
        for tool in sorted(COMPUTER_USE_TOOLS):
            for param in sorted(_COMPUTER_TOOL_PARAM_KEYS.get(tool, frozenset())):
                if _paramReadHits(param, sources) == 0:
                    unread.append(f"{tool}.{param}")
        assert not unread, f"这些参数被广告给模型却无人读取（幻影旋钮）: {unread}"

    def test_paramReadDetectorIsNotVacuous(self):
        """正对照 + 负对照：探测函数本身必须先被证明能用，上一条的绿才有意义。"""
        sources = _productionSources()
        # 负对照：已知被读的参数，不得算成未读
        assert _paramReadHits("url", sources) > 0, "探测连 browser_navigate.url 都认不出 ⇒ 恒假"
        # 正对照：一个绝不可能被读的名字，必须算成 0
        assert _paramReadHits("zzz_definitely_not_a_real_param", sources) == 0, "探测恒真"


class TestFakeDefaultsAreGone:

    def test_ariaSnapshotDescriptionDoesNotClaimUnexistentDefault(self):
        """描述不许承诺代码里没有的默认值。"""
        desc = _BUILTIN_SCHEMAS["browser_dom_snapshot"]["description"]
        params = _BUILTIN_SCHEMAS["browser_dom_snapshot"]["parameters"]["properties"]
        blob = desc + str(params)
        assert "1200" not in blob, "仍承诺『默认节点 1200』，而代码里不传就是不裁剪"
        assert "默认 32" not in blob, "仍承诺默认深度 32"

    def test_trimHelperHonestAboutNoDefault(self):
        """判据咬合实现：不传预算时 _trim_snapshot_tree 必须原样透传（描述的实话依据）。"""
        from neurova.computer_use.browser_manager import _trim_snapshot_tree

        tree = "- heading \"a\"\n  - list\n" + "\n".join(f"- item {i}" for i in range(500))
        out, truncated = _trim_snapshot_tree(tree, None, None)
        assert out == tree and truncated is False, (
            "不传预算却在裁剪 —— 那描述里的『无默认值』就又成了谎话"
        )
