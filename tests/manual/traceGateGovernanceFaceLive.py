# -*- coding: utf-8 -*-
"""live-verify（批 §6-206）：推理链持久化门接进治理面后，真链路上能不能拨、拨了写不写。

原判据（2026-09-05 事故根修）一字未动，本支只证一件新事：这道门此前**只有裸 env 能拨**，
而全仓没有任何生产赋值点 ⇒ 门永远关着且没人能开。现改走 `resolve_flag`，要自证的是：

1. 真 `create_app()` 起来后，治理面 `GET /api/v1/governance/settings` **看得见**这个键，默认 False；
2. 真 `PUT` 拨成 True ⇒ 盘上落值 ⇒ `resolve_flag` 现读 True ⇒ 真 agent 的真
   `ReasoningTraceManager.finish_trace()` 真的把链交棒给引擎（L0 计数 +1）；
3. 拨回 False ⇒ 同一条再跑一次，L0 **不动**（门还在，收口没把防线拆掉）；
4. 反证（优先级）：治理 True 而 `NEUROVA_TRACE_PERSIST=0` ⇒ L0 不动——env 显式 0 仍压住治理面；
   这一格若有人把 `resolve_flag` 换成"治理优先"就会翻红；
5. 关机收敛后按**内容**对账：A1 正文库里带 `reasoning_trace` 的行数只算"开"的那几轮。

管理面依赖用 `app.dependency_overrides[gov._governance_admin_dep]`（按端点实际 import 的那个
名字走，仓内现行做法），不伪造管理员凭证、不动生产 users.db。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.traceGateGovernanceFaceLive
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = "trace_persistence_enabled"
ENV = "NEUROVA_TRACE_PERSIST"


def _reasoningRowsInBody(dbPath: str) -> int:
    """A1 正文库里带 reasoning_trace 指纹的行数（只读连接，不让 sqlite 顺手建库）。"""
    if not Path(dbPath).exists():
        return -1
    con = sqlite3.connect("file:%s?mode=ro" % Path(dbPath).as_posix(), uri=True)
    try:
        return con.execute(
            "SELECT count(*) FROM memories WHERE metadata LIKE '%reasoning_trace%'"
        ).fetchone()[0]
    finally:
        con.close()


def main() -> int:
    from tests.manual._liveVerifyIsolation import (
        isolatedAgentWorkspaces,
        isolatedDataRoot,
    )

    failures: list[str] = []
    readings: dict = {}

    isolatedDataRoot(prefix="neurovaTraceGate")
    isolatedAgentWorkspaces(prefix="neurovaTraceGate")

    from fastapi.testclient import TestClient

    import neurova.api.endpoints.governance as gov
    from neurova.api.app import create_app
    from neurova.security.governance_settings import resolve_flag, settings_path
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager

    app = create_app()
    app.dependency_overrides[gov._governance_admin_dep] = lambda: {"id": 1, "role": "admin"}

    with TestClient(app) as client:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
        engine = getattr(agent, "cognitive_engine", None)
        memory = getattr(agent, "memory_manager", None)
        readings["agent_has_engine"] = engine is not None
        readings["agent_has_memory_manager"] = memory is not None
        if engine is None or memory is None:
            print(json.dumps(readings, ensure_ascii=False, indent=2))
            print("[FAIL] 真 agent 的认知引擎/正文库没装配起来，本支无从取证")
            return 1

        traceManager = ReasoningTraceManager(engine=engine)

        def runOneTrace(tag: str) -> str:
            tid = traceManager.start_trace("晚上好 " + tag)
            traceManager.add_step(tid, "retrieve", "q", "找到 0 条记忆")
            traceManager.finish_trace(tid, "晚上好呀", total_tokens=42)
            return tid

        def l0Count() -> int:
            return int(engine.get_statistics()["l0_buffer"])

        # ── 1. 读面：键可见、默认关 ──
        got = client.get("/api/v1/governance/settings")
        readings["get_status"] = got.status_code
        payload = got.json().get("data", {}) if got.status_code == 200 else {}
        readings["key_visible_in_get"] = KEY in payload
        readings["default_value"] = payload.get(KEY)

        # ── 2. 默认（两侧都不设）不写 ──
        os.environ.pop(ENV, None)
        before = l0Count()
        runOneTrace("off")
        readings["l0_delta_when_closed"] = l0Count() - before

        # ── 3. PUT 拨开：盘上落值 → resolve_flag 认 → 引擎收到 ──
        putOn = client.put("/api/v1/governance/settings", json={KEY: True})
        readings["put_on_status"] = putOn.status_code
        readings["put_on_echo"] = putOn.json().get("data", {}).get(KEY) if putOn.status_code == 200 else None
        onDisk = json.loads(settings_path().read_text(encoding="utf-8")) if settings_path().exists() else {}
        readings["persisted_on_disk"] = onDisk.get(KEY)
        readings["resolve_flag_after_put"] = resolve_flag(KEY, ENV)
        before = l0Count()
        runOneTrace("on")
        readings["l0_delta_when_open"] = l0Count() - before

        # ── 3b. §6-207 读侧过滤：经真 app 的统一检索口，回声行取不到、也不被记账 ──
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode

        # 对照物先落一条普通正文行（同一查询下必须捞得到，否则"取不到"没有反证力）
        control = UnifiedMemoryNode(content="晚上好时先给结论再展开", temperature=60.0)
        engine.store(control)
        engine.close()          # 把上一轮的开闸产物与本条一起 flush 进正文库
        rows = [m for m in memory.iterBodyMemories(limit=500)]
        echo = [m for m in rows if (m.metadata or {}).get("cse_category") == "reasoning_trace"]
        readings["body_has_echo_row"] = len(echo)
        echoCreditBefore = (int(echo[0].access_count or 0), float(echo[0].temperature)) if echo else None

        hits = asyncio.run(agent.unified_retriever.retrieve("晚上好", limit=10))
        readings["retriever_returns_something"] = len(hits) > 0
        readings["echo_leaked_into_context"] = any(
            (h.get("category") if isinstance(h, dict) else getattr(h, "category", None))
            == "reasoning_trace" for h in hits)
        readings["ordinary_row_still_returns"] = any(
            "晚上好" in (h.get("content") if isinstance(h, dict) else getattr(h, "content", ""))
            for h in hits)
        echoAfter = [m for m in memory.iterBodyMemories(limit=500)
                     if (m.metadata or {}).get("cse_category") == "reasoning_trace"]
        readings["echo_row_not_credited"] = (
            echoAfter and echoCreditBefore is not None
            and (int(echoAfter[0].access_count or 0), float(echoAfter[0].temperature))
            == echoCreditBefore)

        # ── 4. 反证：治理 True 而 env 显式 0 ⇒ 仍不写（优先级没被换向）──
        os.environ[ENV] = "0"
        readings["resolve_flag_env_zero"] = resolve_flag(KEY, ENV)
        before = l0Count()
        runOneTrace("forced-off")
        readings["l0_delta_env_zero"] = l0Count() - before
        os.environ.pop(ENV, None)

        # ── 5. 拨回关 ⇒ 再跑仍不写（防线还在）──
        putOff = client.put("/api/v1/governance/settings", json={KEY: False})
        readings["put_off_status"] = putOff.status_code
        readings["resolve_flag_after_put_off"] = resolve_flag(KEY, ENV)
        before = l0Count()
        runOneTrace("closed-again")
        readings["l0_delta_after_close"] = l0Count() - before
        bodyPath = memory.persistenceDbPath()
        # 自己收敛一次：L0 是缓冲，正文库要在 flush 后才有行（close 只 flush，不关库）
        engine.close()
        readings["engine_closed"] = True

    # ── 6. 收敛后按内容对账：只有"开"那一轮进过正文库 ──
    readings["body_rows_with_reasoning_trace"] = _reasoningRowsInBody(bodyPath)

    if readings.get("get_status") != 200:
        failures.append("治理设置读面没通（%s）" % readings.get("get_status"))
    if readings.get("key_visible_in_get") is not True:
        failures.append("GET 面看不到这个键 ⇒ 只是把 env 换了个名字读，没真收到治理面")
    if readings.get("default_value") is not False:
        failures.append("默认值被改了：%s（收口不得翻转现网默认）" % readings.get("default_value"))
    if readings.get("l0_delta_when_closed") != 0:
        failures.append("默认状态下推理链仍被写入 ⇒ 门被拆了（%s）" % readings.get("l0_delta_when_closed"))
    if readings.get("put_on_echo") is not True or readings.get("persisted_on_disk") is not True:
        failures.append("PUT 没落盘：echo=%s disk=%s"
                        % (readings.get("put_on_echo"), readings.get("persisted_on_disk")))
    if readings.get("body_has_echo_row") != 1:
        failures.append("正文库里回声行数=%s，应为 1（门开着却没存下来）"
                        % readings.get("body_has_echo_row"))
    if readings.get("echo_leaked_into_context") is not False:
        failures.append("回声行经真统一检索口进了上下文（过滤器没生效）：%s"
                        % readings.get("echo_leaked_into_context"))
    if readings.get("ordinary_row_still_returns") is not True:
        failures.append("同一查询下普通正文行也取不到 ⇒ 过滤器成了总闸或这条查询本来就捞不到，"
                        "上一格「没泄漏」的读数就是空转")
    if readings.get("echo_row_not_credited") is not True:
        failures.append("被丢掉的回声行仍被记账（先记账后过滤的形状复现）")
    if readings.get("resolve_flag_after_put") is not True:
        failures.append("治理面写了值而消费方读不到 ⇒ 又一个幻影旋钮")
    if readings.get("l0_delta_when_open") != 1:
        failures.append("门开了却没交棒给引擎（l0_delta=%s）——这条链没接通"
                        % readings.get("l0_delta_when_open"))
    if readings.get("resolve_flag_env_zero") is not False:
        failures.append("env 显式 0 没能压住治理面 ⇒ 优先级口径漂了")
    if readings.get("l0_delta_env_zero") != 0:
        failures.append("env=0 时仍写入（%s）" % readings.get("l0_delta_env_zero"))
    if readings.get("resolve_flag_after_put_off") is not False:
        failures.append("拨回 False 后消费方仍读到开")
    if readings.get("l0_delta_after_close") != 0:
        failures.append("拨回关之后仍写入（%s）" % readings.get("l0_delta_after_close"))
    if readings.get("body_rows_with_reasoning_trace") != 1:
        failures.append("正文库里 reasoning_trace 行数=%s，应为 1（只有开着那一轮进过）"
                        % readings.get("body_rows_with_reasoning_trace"))

    print(json.dumps(readings, ensure_ascii=False, indent=2))
    for f in failures:
        print("[FAIL] " + f)
    if failures:
        return 1
    print("LIVE-PASS：治理面可读可写可回滚，开则交棒入库、关则不写，env 显式 0 仍能压住；"
          "§6-207 读侧——回声行存得下却经统一检索口取不到，也不被记账，普通行照常返回")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
