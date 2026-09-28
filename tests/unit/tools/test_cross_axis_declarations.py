# -*- coding: utf-8 -*-
"""跨轴声明一致性与「快照 vs 会话游标」分轴（Issue #271 的 M5 剩余投影）。

## 为什么需要这道守卫（根因，不是形状）

本仓已把「手写名字表」逐条改造成**声明面投影**（桌面运行档、并行轴、重放轴）。
但投影只解决了「成员从哪来」，**没解决「哪几条轴共用同一份声明」**——
后者才是这一类故障的根因：同一份事实被两条轴读成两件事。

两种形态，各自对应一条已发生过的真实故障：

1. **共声明两轴，却只在一轴扣分**（`computer_screenshot`）。
   它声明 `capability.readOnly=True, writeScopes=("shared",)`；
   `runtime_policy.classify_risk()` 据 `readOnly` 把它判为 `low`
   ——「只读动作任何档都直接放行」。这在运行档轴上是**对的**（截图无副作用、
   不需要审批）；另外两条轴给出**相反**结论：并行轴由「非 none 写作用域」
   （`shared`）判为串行，重放轴判为不可重放（瞬时画面）。三轴共用**同一份**
   `capability` 投影，却各答一个事实——`low` 只是运行档轴的那一个答案。
   处置是**把三轴各自的答案并列钉住**：谁要放宽 `low` 的外推
   （让桌面只读在并行轴上也可并行），必须同时给出「共享桌面上并发截图不会互踩」
   的依据并显式改这三条断言，不能靠改一处声明蒙过去。

2. **同一条轴的两份判据口径不一致**（快照 vs 会话游标）。
   重放名单的注释写着「截图/快照语义只读、却因"重放不回当时画面"必须留在此名单里」，
   而 `browser_dom_read` 分片续读推进的是**同一个页面的游标**
   （`session_id` 跨调用共享），与截图属于**不同**的不可复现语义。
   它的测试朋友 `test_reproducible_flag.py::TestWriteScopedToolsAreNeverReproducible`
   只列了三条 `computer_*` 快照作反向控制，`browser_*` 两份快照
   （`browser_screenshot` / `browser_dom_snapshot`）漏在名单之外 ——
   漏一个就是"只读也可能不可重放"这条反例少一条证据，有人据此把两轴并成一个字段时
   那两条不会红。本文件把「同一族、同一根因」的全部命中点逐条钉住（教义第 5 条）。

## 不新造第二份事实源

本文件的全部读数都取自生产声明面本身：
`neurova/builtin_tools.py` 的 `_BUILTIN_SCHEMAS` / `_NON_REPRODUCIBLE_TOOLS`，
以及 `neurova/computer_use/runtime_policy.py` 的投影出口。判据不复制任何名单。
"""

from __future__ import annotations

import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    _NON_REPRODUCIBLE_TOOLS,
    get_builtin_tool_capability,
)
from neurova.computer_use.runtime_policy import classify_risk, desktopReadOnlyTools

#: 「瞬时快照」族的判定面：**同一轴上的两条子语义各自取数**。
#:
#: - `SNAPSHOT_TOOLS`：把**当时画面/结构**冻结成结果，重放取不回那一刻的现场。
#: - `CURSOR_TOOLS`：推进的是**同一个会话的续读游标**，重放会把游标推过头
#:   （与 session 绑定，跨调用共享）。
#:
#: 两份名单都是**取数结果**而不是断言对象本身：断言在下面逐条对声明面复算。
SNAPSHOT_TOOLS = (
    "computer_screenshot", "computer_som_snapshot", "computer_dom_snapshot",
    "browser_screenshot", "browser_dom_snapshot",
)
CURSOR_TOOLS = ("browser_read", "browser_dom_read")


def _description(tool_name: str) -> str:
    return _BUILTIN_SCHEMAS[tool_name]["description"]


#: 运行档轴上被判为 `low`（直接放行）的桌面工具，其 `low` 语义是**该轴专属**的断言；
#: **不得**被读成"这一族在别的轴上也可放宽"。并行轴由 `capability.writeScopes` 取数
#: （非 none ⇒ 串行），重放轴由 `_NON_REPRODUCIBLE_TOOLS` 取数——三轴各自答一个事实。
CROSS_AXIS_CONFLICT = "computer_screenshot"


class TestSnapshotFamilyIsConsistentlyDeclared:
    """瞬时快照族：只读、但重放不可复现——两者必须**同时**成立（不能只挂一头）。"""

    @pytest.mark.parametrize("tool_name", SNAPSHOT_TOOLS)
    def test_snapshotIsReadOnly(self, tool_name):
        cap = get_builtin_tool_capability(tool_name)
        assert cap is not None and cap.readOnly, (
            f"{tool_name} 是瞬时快照，应当声明为只读（`capability.readOnly=True`）——"
            "非只读会把它算进写作用域那一族，与它实际的语义不符"
        )

    @pytest.mark.parametrize("tool_name", SNAPSHOT_TOOLS)
    def test_snapshotIsNotReproducible(self, tool_name):
        assert tool_name in _NON_REPRODUCIBLE_TOOLS, (
            f"{tool_name} 是瞬时快照（重放取不回当时画面/结构），"
            "必须留在重放名单里——只读 ≠ 可重放，两轴不合并"
        )

    def test_snapshotDeclarationsAreSubsetOfTheDesktopProjection(self):
        """桌面只读投影必须与「快照即只读」这条事实一致（防投影与声明面相左）。"""
        snapshots = {name for name in SNAPSHOT_TOOLS if name.startswith("computer_")}
        missing = sorted(snapshots - desktopReadOnlyTools())
        assert not missing, (
            f"这些桌面快照没被运行档判为只读：{missing}——"
            "运行档会把它算成需要审批的动作"
        )


class TestReadOnlyDesktopToolsAreALowRiskOnlyClaim:
    """只读桌面工具在运行档轴上恒为 `low`；并行轴结论必须另行取数、不得由它代办。"""

    def test_readOnlyDesktopToolsClassifyAsLow(self):
        for tool_name in sorted(desktopReadOnlyTools()):
            assert classify_risk(tool_name) == "low", (
                f"{tool_name} 是只读桌面工具，运行档轴上应为 low（直接放行）"
            )

    def test_sharedDesktopReadsStillCarrySharedWriteScope(self):
        """`low` 那条断言不得被外推到别的轴：它对应的工具仍声明**共享**写作用域。

        这是本文件要钉的那条事实：同一份 `capability` 在三个轴上给出三个答案——
        运行档轴说 `low`（不需要审批）、并行轴说串行（写作用域非 none）、
        重放轴说不可重放（瞬时画面）。`low` 只是**运行档轴**的断言。
        """
        cap = get_builtin_tool_capability(CROSS_AXIS_CONFLICT)
        assert cap is not None, f"{CROSS_AXIS_CONFLICT} 没有能力声明——本组的取数面失效"
        scopes = {getattr(scope, "value", str(scope)) for scope in (cap.writeScopes or ())}
        assert scopes - {"none"}, (
            f"{CROSS_AXIS_CONFLICT} 已不再携带非 none 写作用域（实测 {sorted(scopes)}）——"
            "「三轴各答一个事实」的样例失效了。是并行轴的推导改了，还是声明面被改宽了？"
            "两种都要显式裁定后再同步本条，不能让判据静默空转。"
        )
        assert classify_risk(CROSS_AXIS_CONFLICT) == "low", (
            "运行档轴不再把它判为 low——本组钉的样例需重新裁定"
        )
        assert CROSS_AXIS_CONFLICT in _NON_REPRODUCIBLE_TOOLS, (
            "重放轴不再把它判为不可重放——三轴样例缺一条"
        )


class TestCursorToolsAreADifferentAxis:
    """会话游标族：只读、**可重放**（判据是「同参数重放取回原文」），与快照不同轴。"""

    @pytest.mark.parametrize("tool_name", CURSOR_TOOLS)
    def test_cursorToolIsReadOnly(self, tool_name):
        cap = get_builtin_tool_capability(tool_name)
        assert cap is not None and cap.readOnly, f"{tool_name} 应当声明为只读"

    @pytest.mark.parametrize("tool_name", CURSOR_TOOLS)
    def test_cursorToolIsReproducible(self, tool_name):
        """两族都**只读**，在重放轴上却必须给出**不同**读数。

        这是「不合并」的判据本体：有人把这两族一起塞进重放名单
        （"反正都是共享作用域、都不可并行"）时，本条即红。
        """
        assert tool_name not in _NON_REPRODUCIBLE_TOOLS, (
            f"{tool_name} 推进的是会话续读游标（同参数重放取回同一段文本），"
            "与瞬时快照不同轴；把它并入重放名单会让「只读也可能不可重放」"
            "这条反例失去判别力"
        )

    def test_cursorFamilyIsNotVacuous(self):
        """取数非空自证：本组必须真的取到「只读且可重放」的会话游标工具。"""
        found = [
            name for name in CURSOR_TOOLS
            if (cap := get_builtin_tool_capability(name)) is not None
            and cap.readOnly and name not in _NON_REPRODUCIBLE_TOOLS
        ]
        assert found == list(CURSOR_TOOLS), (
            f"会话游标取数不完整（{found}）——空取数会让上一组的断言恒真通过"
        )
