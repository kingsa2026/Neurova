# -*- coding: utf-8 -*-
"""取证档的结论必须由读数派生——常驻闸（§6-471）。

## 这一格防的是什么

`tests/manual/context_persistence_baseline_90.py` 的三份结论今天全是假的，而同一份报告里
紧邻的读数全是对的（2026-11-02 实跑原文）：

    模拟重启后的新实例：常驻 0 条；recall_evicted = 20（归档活不过重启）
    结论：写入进程的归档在新进程里取不到 → A1 当前为红
    无会话池（session_id=None）召回条数 = 0，且无 filter_by_scope 闸口 → 房间内容可见

取证档手工跑、不进 CI，所以散文里的结论从来没人复核；它一旦过时，读的人就拿它当今天的事实源
（本仓已差点把「生产复刻了第二份作用域规则」按这句登记成真）。修法不是把结论改对——改对的那
一句同样会在下一次实现变化后再次过时——而是**结论只能由读数派生**，派生口径收在
`tests/manual/_forensicsVerdicts.py` 单点，本档钉住那一句「不许再写死」。

判据分两层：形态格扫取证档源码（写死结论的整串字面量一出现即红；反向一并钉"派生通道确实接上了"，
免得有人拿**删掉结论行**当修法）；行为格钉三个纯函数各自的三态，含"解析不出来必须点名不可用"，
以及 0 与 20 必须给出**不同**的话（防恒返）。
"""
from pathlib import Path

import pytest

from tests.manual._forensicsVerdicts import a1Verdict, tailCount, visibilityVerdict

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tests" / "manual" / "context_persistence_baseline_90.py"

#: 2026-11-02 实测为假的那几句原文。整串钉，不钉散词——散词（"不可见"／"活不过"）
#: 是派生分支的产物，钉它们会把正确修法判红。
HARDCODED = (
    "（归档活不过重启）",
    "结论：写入进程的归档在新进程里取不到 → A1 当前为红",
    "且无 filter_by_scope 闸口 → 房间内容可见",
    "（恒空：本轮会话 id 与归档会话 id 不等）",
    '"1 现状 P1-3：写入口不可达"',
    '"8 读侧缺陷"',
)


@pytest.fixture(scope="module")
def scriptSource():
    assert SCRIPT.is_file(), f"取证档路径变了：{SCRIPT}——这时「没有写死结论」不代表任何事"
    return SCRIPT.read_text(encoding="utf-8")


def test_noHardcodedVerdictSurvives(scriptSource):
    """写死结论的整串字面量一出现即红。"""
    present = [phrase for phrase in HARDCODED if phrase in scriptSource]
    assert not present, (
        "取证档里又出现写死的结论（它会在下一次实现变化后与同页读数互相矛盾）：\n"
        + "\n".join("  " + p for p in present)
        + "\n修法：结论从 `tests/manual/_forensicsVerdicts.py` 派生，不在此写字面量。"
    )


def test_derivationIsActuallyWired(scriptSource):
    """反向钉：只把结论行删掉不算修好——派生通道必须接上。"""
    assert "from tests.manual._forensicsVerdicts import" in scriptSource, "没接单点 import"
    for name in ("tailCount(", "a1Verdict(", "visibilityVerdict("):
        assert name in scriptSource, f"单点函数 {name} 没被调用——结论行是被删了还是另写了一份？"


def test_tailCountThreeShapes():
    assert tailCount("reader 常驻 0 / recall_evicted 20", "recall_evicted") == 20
    assert tailCount("reader 常驻 0 / recall_evicted 0", "recall_evicted") == 0
    assert tailCount("reader 子件炸了", "recall_evicted") is None
    assert tailCount(None, "recall_evicted") is None


def test_a1VerdictFollowsItsReading():
    zero, positive = a1Verdict(0), a1Verdict(20)
    assert "红" in zero and "绿" not in zero, zero
    assert "绿" in positive, positive
    assert zero != positive, "0 与 20 给出同一句话 ⇒ 结论不跟读数走"
    unavailable = a1Verdict(None)
    assert "不可用" in unavailable, unavailable
    assert "绿" not in unavailable and "红" not in unavailable, (
        "解析不出来时既不能说绿也不能说红——只能点名不可用：%s" % unavailable
    )


def test_visibilityVerdictFollowsItsReading():
    blocked, leaked = visibilityVerdict(0), visibilityVerdict(3)
    assert blocked == "不可见", blocked
    assert "失效" in leaked, leaked
    assert blocked != leaked
