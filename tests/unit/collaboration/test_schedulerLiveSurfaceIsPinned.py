# -*- coding: utf-8 -*-
"""§6-312 乙案的前置判据：把调度器**在役面**钉住，让"按符号瘦 `workflow/models.py`"这刀有依据可红。

为什么先立这一档（批 84 的台账原话）：与本作相关的四档测试**一档都不在受保护子集** ⇒ 真做退役时
"CI 没红"不能当"改对了"的证据。本档把"瘦之前必须原样成立"的几条钉成常驻格子；
无论 §6-312 最后裁甲／乙／丙都用得上，且它自己不碰生产码。

与既有 `test_workflow_scheduler.py` 的分工（不另起平行面，教义第 6 条）：那档已覆盖
排程期 `next_run_at`、完成后续排、单次置 completed、handler 派发、未注册即失败、重启后任务仍在。
本档只钉它没钉的四件事：

① `FlowContext` 的真实用法只有"无参构造后交给 handler"，且调度器与 handler 都没读也没写它的字段
   ——这一条就是"编排方法群可以摘"的许可证。探测器必须**双向**自证：合成一段真读
   `context.add_event(...)` 的源码要被点名，纯类型标注不得误报（形态集 283：每个零都要先证能产生非零）。
② `ScheduledTask` 的**字段位**经真落盘—重载逐字段等值（既有档只验 name/cron/next_run 三个）。
   `asdict → json → ScheduledTask(**item)` 就是这份存储的 schema，瘦同文件邻居时最容易顺手掉的正是它。
③ 抛异常那条路：`status=failed` ＋ `last_error` ＋ `run_count` 计数 ＋ 事件带错误文本。
④ `is_due()` 的门（非 pending 一律不再触发）与 `compute_next_run` 的三条沉默语义
   （两者皆无→None；不可解析 cron→None **不抛**；`interval_seconds=0` 不得吞掉 cron 那一支）
   ＋ cron 的 `day_of_week` 是 APScheduler 语义（0=周一，与"标准 cron 0=周日"差一格）。
"""

from __future__ import annotations

import ast
import dataclasses
import json
import math
import pathlib
import time
from datetime import datetime

import pytest

from neurova.collaborate.workflow.scheduler import AgentScheduler
from neurova.collaborate.workflow.models import FlowContext, ScheduledTask, compute_next_run
from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: 在役消费者——**显式清单**（不收目录：多一个文件就多一处未审视的面；本仓对 glob 型常驻格裁过乙）
LIVE_CONSUMER_FILES = (
    "neurova/collaborate/workflow/scheduler.py",
    "neurova/api/endpoints/scheduler.py",
    "neurova/api/endpoints/agent_package.py",
)

#: 构造与落盘各按自身时钟取值，比对"没被碰过"时只能跳过这三格
CLOCK_AND_ID_FIELDS = frozenset({"started_at", "updated_at", "flow_id"})


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    """干净实例＋隔离 store（不写 `data/scheduler_tasks.json`）。

    单例重置沿用既有档的写法；`monkeypatch.setenv` 自动收尾，不把 env 留给后续用例。
    """
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "sched_b87.json"))
    AgentScheduler._instance = None
    instance = AgentScheduler()
    yield instance
    AgentScheduler._instance = None


def _flowContextSurface(source: str, where: str) -> dict:
    """这份源码里对 `FlowContext` 的用法：无参构造点，以及除"类型标注／形参名/import"外的一切取用。

    判代码形态不判词（形态集 241/268 一族）：注释与 docstring 里提一句不算被读；
    `context.add_event(...)`、`context["k"]` 这种真读必须抓到。
    """
    constructions, uses = [], []
    try:
        tree = ast.parse(source, filename=where)
    except SyntaxError:
        return {"constructions": [], "uses": [f"{where}: SyntaxError"]}

    annotationIds = set()
    for node in ast.walk(tree):
        for attrName in ("annotation", "returns"):
            holder = getattr(node, attrName, None)
            if isinstance(holder, ast.AST):
                annotationIds |= {id(n) for n in ast.walk(holder)}
    callFuncs = {id(c.func) for c in ast.walk(tree) if isinstance(c, ast.Call)}

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "FlowContext":
            if id(node) in annotationIds:
                continue
            if id(node) in callFuncs:
                call = next(c for c in ast.walk(tree)
                            if isinstance(c, ast.Call) and c.func is node)
                if call.args or call.keywords:
                    uses.append(f"{where}:{node.lineno} 带参构造 FlowContext(...)")
                else:
                    constructions.append(f"{where}:{node.lineno}")
            else:
                uses.append(f"{where}:{node.lineno} 非构造处引用 FlowContext")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in {"context", "ctx"}:
            uses.append(f"{where}:{node.lineno} 读 context.{node.attr}")
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id in {"context", "ctx"}:
            uses.append(f"{where}:{node.lineno} 下标取用 context")
    return {"constructions": constructions, "uses": uses}


def test_liveSurfaceUsesFlowContextOnlyByConstruction():
    """①静态格：在役面里 `FlowContext` 只有"无参构造"这一种用法，且只有一处。

    少了这一格，"编排方法群是死的"只是档案里的一句话；这一格把它变成会红的东西——
    哪天有人让 handler 或端点去读 `context`，乙案那一刀就必须先重开评估。
    """
    constructions, uses = [], []
    for rel in LIVE_CONSUMER_FILES:
        path = REPO_ROOT / rel
        assert path.is_file(), f"在役清单里的档不见了：{rel}（清单要跟着实状改，不许静默缩面）"
        found = _flowContextSurface(ast_scan.sourceCode(path), rel)
        constructions += found["constructions"]
        uses += found["uses"]

    assert len(constructions) == 1, (
        f"构造点应恰好一处（调度器交付 handler 那一处），实得 {constructions}——"
        "零处＝本档前提已变，先改判再谈退役；多处＝上下文生命周期变复杂了，乙案要重估")
    assert not uses, f"在役面还在读/写 FlowContext 的成员，乙案那一刀不能就这么下：{uses}"


def test_detectorFlagsARealReadAndIgnoresAnnotations():
    """①的双向自证：真读必须被点名（两形都认），import／类型标注不得误报。

    第三枚管"带参构造"——它既不该算许可证里的"无参构造"，也不该被漏掉。
    """
    reading = "def h(task, context):\n    context.add_event('x', {})\n    return context.shared_data['k']\n"
    flagged = _flowContextSurface(reading, "synthetic.py")
    assert len(flagged["uses"]) == 2, f"真读没被抓全（抓到 {flagged['uses']}）——探测器不可信"

    quietSrc = ("from neurova.collaborate.workflow.models import FlowContext\n"
                "def h(task, ctx: FlowContext) -> int:\n    return 1\n")
    quiet = _flowContextSurface(quietSrc, "synthetic2.py")
    assert not quiet["uses"], f"仅 import＋类型标注被算成读用（误报会训练人忽略门禁）：{quiet['uses']}"

    withArgs = _flowContextSurface("def run():\n    return FlowContext(flow_id='x')\n", "synthetic3.py")
    assert not withArgs["constructions"] and len(withArgs["uses"]) == 1, (
        f"带参构造应单列而不计入许可证面，实得 {withArgs}")


def test_handlerGetsFreshUntouchedContext(scheduler):
    """①的行为面：每次执行给一个新的 `FlowContext`，且交付时它没被碰过。

    比静态格更硬的一点：静态格说"没人读"，这一格说"也没人写"——
    逐字段与当场新建的实例比（跳过三个即时钟/随机字段），谁提前写了默认值就会被抓。
    """
    seen = []
    scheduler.register_handler("b87-probe", lambda task, ctx: seen.append(ctx))

    first = scheduler.schedule_task(name="one", action="b87-probe")
    first.scheduled_at = time.time() - 1
    scheduler._execute_task(first)
    second = scheduler.schedule_task(name="two", action="b87-probe")
    second.scheduled_at = time.time() - 1
    scheduler._execute_task(second)

    assert len(seen) == 2 and seen[0] is not seen[1], f"两次执行拿到的不是两个上下文：{seen}"
    assert all(isinstance(c, FlowContext) for c in seen), "handler 收到的不是 FlowContext"
    baseline = vars(FlowContext())
    for ctx in seen:
        assert set(ctx.__dict__) == set(baseline), (
            f"字段集与新建实例不一致（被写过或类本身被动过）：{sorted(set(ctx.__dict__) ^ set(baseline))}")
        drift = {k: (baseline[k], ctx.__dict__[k]) for k in baseline
                 if k not in CLOCK_AND_ID_FIELDS and ctx.__dict__[k] != baseline[k]}
        assert not drift, f"调度器在交付前就写了上下文的字段：{drift}"


def test_everyScheduledTaskFieldSurvivesRealPersistReload(tmp_path, monkeypatch):
    """②存储契约格：非默认值填满每个字段位，经**真落盘**再读回，逐字段等值。

    走真装配点（`add_task → _persist` ＋新实例从同一 store 重载），不手抄序列化。
    守的是：瘦同文件死半区时 `ScheduledTask` 的字段位一个都不许掉；
    `last_result`／`last_error` 走 `json.dump(default=str)`，读回来必须是原值而不是 None。
    """
    store = tmp_path / "b87-store.json"
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(store))
    AgentScheduler._instance = None
    writer = AgentScheduler()
    task = ScheduledTask(
        task_id="b87-task-1", name="满字段", description="每条都填", scheduled_at=1_700_000_000.0,
        interval_seconds=120, cron_expression="*/5 * * * *", agent_id="agent-x", action="send_message",
        parameters={"message": "hi", "nested": {"k": [1, 2]}}, status="running",
        created_at=1_600_000_000.0, updated_at=1_600_000_001.0, last_run_at=1_600_000_002.0,
        next_run_at=1_600_000_060.0, run_count=7, max_runs=42,
        last_result={"ok": True}, last_error="上一轮的错误",
    )
    assert writer.add_task(task) is True
    assert store.exists(), "add_task 没落盘（持久化这条腿断了）"

    AgentScheduler._instance = None
    reader = AgentScheduler()
    restored = reader.get_task("b87-task-1")
    assert restored is not None, "重启后任务没被读回（存储面被改坏了）"
    original, after = dataclasses.asdict(task), dataclasses.asdict(restored)
    assert set(after) == set(original), (
        f"字段集变了（掉了 {sorted(set(original) - set(after))}，多了 {sorted(set(after) - set(original))}）")
    drift = {k: (original[k], after[k]) for k in original if after[k] != original[k]}
    assert not drift, f"字段值经落盘变了：{drift}"

    raw = json.loads(store.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and raw[0]["task_id"] == "b87-task-1", f"落盘形状变了：{str(raw)[:120]}"
    AgentScheduler._instance = None


def test_raisingHandlerMarksFailedAndEmitsErrorEvent(scheduler):
    """③失败路径格：抛异常 ⇒ failed＋last_error＋run_count 计数＋事件带错误文本。

    既有档只覆盖"没注册 handler 即失败"；**注册了但抛**这条路（生产上是 agent 不可达／技能缺失）
    没钉过。乙案不动这里，但退役批次最容易顺手把 `_emit_event` 的 error 字段裁掉。
    """
    events = []
    scheduler.add_event_handler(lambda e: events.append(e))

    def boom(task, ctx):
        raise RuntimeError("技能缺失：b87")

    scheduler.register_handler("b87-boom", boom)
    task = scheduler.schedule_task(name="will-fail", action="b87-boom")
    task.scheduled_at = time.time() - 1
    scheduler._execute_task(task)

    assert task.status == "failed", f"抛异常后状态不是 failed：{task.status}"
    assert task.last_error and "b87" in task.last_error, f"错误文本没落到 last_error：{task.last_error!r}"
    assert task.run_count == 1, f"失败也该计数，实得 {task.run_count}"
    failed = [e for e in events if e.get("event_type") == "task_failed"]
    assert len(failed) == 1, f"没发 task_failed 事件（通知桥就收不到）：{events}"
    assert failed[0].get("task_id") == task.task_id and "b87" in failed[0].get("error", ""), (
        f"事件载荷缺 task_id/error：{failed[0]}")
    started = [e for e in events if e.get("event_type") == "task_started"]
    assert len(started) == 1 and {"event_type", "task_id", "task_name", "timestamp"} <= set(started[0]), (
        f"事件面形状变了（通知桥依赖这几个键）：{started}")


def test_isDueGateAndComputeNextRunSilence():
    """④门与沉默语义：非 pending 不再触发；三条不该抛的形态都给 None；cron 的 0 是周一。

    `interval_seconds=0` 那一枚管住一个具体改坏方向：把 `if interval_seconds and ...` 写成
    `>= 0` 就会让 cron 任务永不续排——而它看起来只是"补个边界"。
    """
    assert not ScheduledTask(status="failed", scheduled_at=time.time() - 10).is_due(), \
        "failed 的任务还会触发（重试语义被改宽）"
    assert ScheduledTask(status="pending", next_run_at=time.time() - 1).is_due(), \
        "pending 且已过 next_run_at 竟不触发"

    assert compute_next_run() is None, "两者皆无应回 None（单次任务不排程）"
    assert compute_next_run(cron_expression="nonsense expression here") is None, "不可解析的 cron 应回 None 而不是抛"
    assert compute_next_run(cron_expression="0 9 * *") is None, "不足 5 段应回 None"

    base = datetime(2026, 10, 19, 12, 0).timestamp()  # 2026-10-19 是周一
    mondayOnly = compute_next_run(cron_expression="0 9 * * 0", after=base)
    assert mondayOnly is not None and abs(mondayOnly - datetime(2026, 10, 26, 9, 0).timestamp()) < 5, (
        f"day_of_week 不是 0=周一（APScheduler 语义，前端可视化构建器同一口径）：{mondayOnly}")
    assert compute_next_run(interval_seconds=90, after=base) == base + 90, "interval 应直接加在 after 上"
    # 这一枚的取值要落在分歧点上：`interval_seconds=0` 被当成"给了值"时，返回的是 base 本身，
    # 只断"不是 None"会被它蒙过去（变异自证实测打空过一次，形态集 239）。要断的是**它给出的是 cron 的那一刻**。
    cronKeptWhenIntervalZero = compute_next_run(cron_expression="0 9 * * *", interval_seconds=0, after=base)
    assert cronKeptWhenIntervalZero is not None and \
        abs(cronKeptWhenIntervalZero - datetime(2026, 10, 20, 9, 0).timestamp()) < 5, (
        f"interval=0 把 cron 那一支吞掉了（返回的不是次日 09:00 而是 {cronKeptWhenIntervalZero}）——续排会静默失效")


def test_statisticsAndDueSweepAfterOneFullCycle(scheduler):
    """收尾格：走完一轮后，统计／过滤／排程三处读数说的是同一件事。

    `_check_and_execute_tasks()` 是真入口（线程循环里调的就是它），所以这一格跑的是真链路形状。
    `get_statistics()` 的键面也在这里钉住——它是面板读数，裁掉任何一个键面板就少一格。
    """
    scheduler.register_handler("b87-ok", lambda task, ctx: {"done": True})
    due = scheduler.schedule_task(name="due-now", action="b87-ok")
    due.scheduled_at = time.time() - 5
    later = scheduler.schedule_task(name="not-yet", action="b87-ok", interval_seconds=3600)

    before = scheduler.get_statistics()
    assert set(before) == {"total_tasks", "pending_tasks", "running_tasks", "completed_tasks",
                           "failed_tasks", "cancelled_tasks", "is_running"}, f"统计键面变了：{sorted(before)}"
    assert before["total_tasks"] == 2, f"两个任务都该在账上：{before}"

    scheduler._check_and_execute_tasks()

    assert due.status == "completed", f"到期任务没被执行：{due.status}"
    after = scheduler.get_statistics()
    assert after["completed_tasks"] == 1, f"完成计数不对：{after}"
    assert [t.task_id for t in scheduler.list_tasks(status="pending")] == [later.task_id], (
        "pending 过滤把已完成的还留着（或把待触发的漏掉了）")
    assert math.isclose(later.next_run_at - time.time(), 3600, abs_tol=30), (
        f"未到期任务的排程被动过：{later.next_run_at}")
