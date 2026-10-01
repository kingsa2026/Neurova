"""工具耗时的量具必须是单调时钟——`execution_time` 的 0.0 不是"快"，是**量不出来**。

## 为什么会红

`tests/unit/agent/test_tool_loop_funnel_probes.py::test_turn_writes_elapsed_and_structure_key`
断言落库列 `execution_time > 0`，在共享工作树里两侧随机翻（工单集 §31.3 采过样）。
根因不在这条判据，在咽喉的量具：

```
neurova/tool_executor.py        start = time.time()   →   elapsed = time.time() - start
```

Windows 上 `time.time()` 的粒度约 15.6ms（CLOCK_TICK），一个进程内快工具整次调用
落在同一个 tick 里 ⇒ 差值恰好 `0.0`。而轮级累加器照样 `samples += 1` 记成"本轮测到过"，
于是三态里的"测得多少"交出一个**假的 0.0**：同一列上"跑了但很快"与"量不出来"不可分辨，
而 `> 0` 变成一次"时钟跨不跨界"的抽奖。

时长是差值，该用单调时钟（`perf_counter` 系，纳秒级分辨率）。`time.time()` 的正当用途是
"当前时刻"（时间戳、TTL 比较）——那类命中点本单刻意不管：`neurova/` 里 403 处
`time.time() - `，绝大多数是 uptime/TTL，属合法墙钟差值，一并禁墙钟就是误伤。

## 判据口径

- 前两条是结构守卫，**确定性**红：咽喉里作为时长起点/终点的绑定不许走墙钟；
  同时必须真的存在一处单调时钟的时长绑定（防止"把计时删了"被当成修好了——
  那会让该列退回 NULL，"跑了多快"再度无人测量，正是工单 009 的原点）。
- 第三条钉住三态口径本身（没测到→None；测到哪怕 0.0→原样交出），
  免得换量具时顺手把工单 016 定的 NULL≠0 语义改掉。
"""
import ast
from pathlib import Path

from neurova.core import turn_context as tc

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_EXECUTOR = REPO_ROOT / "neurova" / "tool_executor.py"

#: 量时长可用的单调系时钟。`time.time` 刻意不在列内——它答的是"现在几点"。
MONOTONIC_FUNCS = {"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "clock_gettime"}

#: 时长链路上的绑定名，只在"喂给轮级累加器的那个函数"里查（别的文件不并进来管）。
DURATION_BINDS = {"start", "started", "start_time", "t0", "begin", "elapsed"}


def _functionFeedingAccumulator() -> ast.AST:
    tree = ast.parse(TOOL_EXECUTOR.read_text(encoding="utf-8"), filename=str(TOOL_EXECUTOR))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                name = getattr(inner.func, "attr", None) or getattr(inner.func, "id", None)
                if name == "add_turn_tool_elapsed":
                    return node
    raise AssertionError("找不到调用 add_turn_tool_elapsed 的函数——咽喉挪位置了，本守卫要跟着改")


def _clocksUsed(value: ast.AST) -> set:
    return {
        getattr(node.func, "attr", None) or getattr(node.func, "id", None) or ""
        for node in ast.walk(value) if isinstance(node, ast.Call)
    }


def _durationBinds(fn: ast.AST) -> list:
    """返回 [(目标名集合, 用到的时钟名集合, 行号)]——只看时长链上的赋值。"""
    binds = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if targets & DURATION_BINDS:
            binds.append((sorted(targets), _clocksUsed(node.value), node.lineno))
    return binds


def test_chokePointMeasuresDurationOnMonotonicClock():
    offenders = [
        (targets, clocks, lineno)
        for targets, clocks, lineno in _durationBinds(_functionFeedingAccumulator())
        if "time" in clocks and not (clocks & MONOTONIC_FUNCS)
    ]
    assert not offenders, (
        "工具耗时的时长绑定走了墙钟差值 time.time()：Windows 粒度约 15.6ms，"
        "快工具会被量成 0.0，落库的 execution_time 就成了假的测量值。"
        f"命中点（绑定名, 时钟, 行号）：{offenders}"
    )


def test_monotonicDurationBindIsStillThere():
    binds = [
        targets for targets, clocks, _ in _durationBinds(_functionFeedingAccumulator())
        if clocks & MONOTONIC_FUNCS
    ]
    assert binds, (
        "咽喉里没有任何单调时钟的时长绑定——计时被删了：execution_time 会退回 NULL，"
        "「这条经验跑了多久」再度变成没人测（工单 009 的原点）"
    )


def testMeasuredFlagStaysSeparateFromMagnitude():
    """三态本身：未测量→None；测到（哪怕 0.0）→原样交出，且累加按样本计数。"""
    tc.reset_turn_tool_elapsed()
    try:
        assert tc.get_turn_tool_elapsed_measurement() is None, "未测量必须是 None，不是 0.0"
        assert tc.has_turn_tool_measurement() is False
        tc.add_turn_tool_elapsed(0.0)
        assert tc.has_turn_tool_measurement() is True, "0.0 也是测到过，不得折回未测量"
        assert tc.get_turn_tool_elapsed_measurement() == 0.0
        tc.add_turn_tool_elapsed(0.5)
        tc.add_turn_tool_elapsed(0.25)
        got = tc.get_turn_tool_elapsed_measurement()
        assert got is not None and abs(got - 0.75) < 1e-9, got
    finally:
        tc.reset_turn_tool_elapsed()
