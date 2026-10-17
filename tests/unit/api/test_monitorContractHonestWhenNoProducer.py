# -*- coding: utf-8 -*-
"""`/api/v1/monitor/connections` 的诚实契约（批 78·D1 丙）。

§6-305 探针量到的实状：真 `create_app()` + lifespan + 真 HTTP 流量下，`ExecutionMonitor` 的
**14 个写入方法计数全 0**（`create_alert`／`record_metric`／`start_trace`／`end_trace`／
`add_trace_log`／`record_step`／`record_error`／`record_tool_call`／`start_execution`／
`complete_execution`／`fail_execution`／`set_event_bus`／两个 `register_*_handler`），
告警表除探针正控那条外恒空，`logs/executions` 目录 0 个文件。

而端点今天这么报（改前实状）：

    ConnectionStatus(name="Execution Monitor",
                     detail=f"{n_alerts} open alerts",
                     status="warning" if n_alerts else "connected")

⇒ **"没人往这张表写"被翻译成了"一切正常"**。面板 `MonitorPage.vue:51` 就是按
`item.status === 'connected'` 上色，于是那行显示绿点 ＋ "0 open alerts"。

修法按教义第 2 条取"诚实形态"而不是加兜底：这一行不再由告警条数反推健康，直接点名"无告警生产者"。
后端改文案即足以让面板那行自动变非绿（它读 `status` 上色、读 `detail` 显示），
所以本批不动前端、不动 11 语言。

判据四格：两格是本次要转绿的行为/形状断言（①④），两格**设计成两侧都绿**并写明作用——
②是①的根据（真跑一遍确认确实没有写侧），③是②的正控（缺了它，②那串 0 就是"谁都没动"的空集假绿）。
"""
from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MONITOR_ENDPOINT = REPO_ROOT / "neurova" / "api" / "endpoints" / "monitor.py"

#: §6-305 那批写入方法名——本批不许改它们的签名，只用来做运行时计数
WRITERS = ("create_alert", "record_metric", "start_trace", "end_trace", "add_trace_log",
           "record_step", "record_error", "record_tool_call", "start_execution",
           "complete_execution", "fail_execution", "set_event_bus",
           "register_alert_handler", "register_metric_handler")
MONITOR_ROW_NAME = "Execution Monitor"


def _adminHeaders():
    from neurova.api.auth import create_access_token

    # 身份走生产签 token 函数，并带上端点要求的角色（monitor 那几路挂 require_admin()）。
    # 少了 role 会拿到 403——那会把"没权限"读成"没走到"（形态集 283 就是这么栽过一次）。
    return {"Authorization": f"Bearer {create_access_token({'sub': 'b78-user', 'role': 'admin'})}"}


def _connections(client):
    resp = client.get("/api/v1/monitor/connections", headers=_adminHeaders())
    assert resp.status_code == 200, f"connections 端点没通：{resp.status_code} {resp.text[:200]}"
    body = resp.json()
    rows = body.get("data") if isinstance(body, dict) and "data" in body else body
    assert isinstance(rows, list), f"connections 回包不是数组：{type(rows).__name__}"
    return rows


def test_monitorRowDoesNotClaimConnectedWithoutAProducer():
    """①行为格（本次要转绿）：这一行不许再把"表恒空"报成"一切正常"。

    改前实测 `status='connected'` ＋ `detail='0 open alerts'`；本批要求它既不报 connected，
    detail 也不许是那条"数字 + open alerts"的老文案（那句式本身就是在替"没有生产者"化妆）。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    with TestClient(create_app()) as client:
        rows = _connections(client)

    row = next((r for r in rows if r.get("name") == MONITOR_ROW_NAME), None)
    assert row is not None, f"connections 里没有 {MONITOR_ROW_NAME} 这一行：{[r.get('name') for r in rows]}"
    assert row.get("status") != "connected", \
        f"无写侧却仍报 connected（面板会上绿点）：{row}"
    detail = str(row.get("detail", ""))
    assert "open alerts" not in detail, f"detail 仍在用告警条数反推健康：{row}"


def test_connectionsDerivesMonitorHealthFromNothing():
    """④形状格（本次要转绿）：那一行的 `status` 不许再由告警条数三元推出来。

    钉的是代码形态，不是词：`get_connections` 函数体内构造 `ConnectionStatus` 的调用里，
    `status` 实参不许是一个 `IfExp`（老写法 `status="warning" if n_alerts else "connected"` 正是它）。
    按词扫会把注释里的解释句一起扫进去（形态集 241／268 同族），所以走 AST。
    """
    tree = ast.parse(MONITOR_ENDPOINT.read_text(encoding="utf-8", errors="replace"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_connections"), None)
    assert fn is not None, "找不到 `get_connections`——端点被搬走了，本判据要跟着改"

    offenders = []
    for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
        func = call.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "ConnectionStatus":
            continue
        for kw in call.keywords or []:
            if kw.arg == "status" and isinstance(kw.value, ast.IfExp):
                offenders.append(ast.unparse(call))
    assert not offenders, f"这一行又回到「按条数猜健康」的写法：{offenders}"


def test_monitorHasNoWritersOnTheRealPath():
    """②根据（设计成两侧都绿）：真 app + 真流量下，14 个写入方法计数必须确实全 0。

    这条不是装饰——①的"不许报 connected"是**有条件的**（条件是确实没写侧）。
    哪天有人接了写侧（D1 甲），这条会先红，逼他连同①的期望一起改判，而不是留下一个
    永远自称"未接线"的新谎言。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.shared_core.execution_engine import get_execution_engine

    monitor = get_execution_engine().get_execution_monitor()
    assert monitor is not None, "监控器取不到——②没有对象可数"

    counts = {w: 0 for w in WRITERS}
    originals = {}
    for w in WRITERS:
        fn = getattr(monitor, w, None)
        assert fn is not None, f"`ExecutionMonitor` 上少了写入方法 {w}——签名面变了，本判据要跟着改"
        originals[w] = fn

        def make(key, f):
            def inner(*a, **k):
                counts[key] += 1
                return f(*a, **k)
            return inner

        setattr(monitor, w, make(w, fn))
    try:
        with TestClient(create_app()) as client:
            rows = _connections(client)
            client.get("/api/v1/monitor/alerts", headers=_adminHeaders())
            client.get("/api/v1/monitor/status", headers=_adminHeaders())
            execPath = next((p for p in create_app().openapi()["paths"]
                             if p.endswith("/tool-layers/tools/execute")), "")
            client.post(execPath, json={"tool_name": "file_read",
                                       "arguments": {"path": "README.md"}}, headers=_adminHeaders())
            assert isinstance(rows, list) and rows
    finally:
        for w, fn in originals.items():
            setattr(monitor, w, fn)

    nonzero = {k: v for k, v in counts.items() if v}
    assert not nonzero, f"写侧出现了调用（{nonzero}）——D1 已改判成甲，①的期望必须一起改"


def test_alertsReaderIsLiveWhenAProducerWrites():
    """③正控（设计成两侧都绿）：写一条进监控器，`/alerts` 必须读回那一条。

    没有这条，②那串 0 就分不清"确实没人写"与"读侧坏了所以下面全空"（形态集 283/266）。
    走**未包装**的类方法写，免得计数被别的格的 wrapper 干扰。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.execution_engine.execution_monitor import AlertLevel
    from neurova.shared_core.execution_engine import get_execution_engine

    monitor = get_execution_engine().get_execution_monitor()
    assert monitor is not None
    type(monitor).create_alert(monitor, AlertLevel.WARNING, "b78 正控", "判据写入的一条告警",
                               source="judgment")

    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/monitor/alerts", headers=_adminHeaders())
        assert resp.status_code == 200, f"alerts 端点没通：{resp.status_code}"
        body = resp.json()
        rows = body.get("data") if isinstance(body, dict) and "data" in body else body
    titles = [r.get("title") for r in rows] if isinstance(rows, list) else []
    assert "b78 正控" in titles, f"写了却读不回来（读侧才是坏的）：{titles}"
