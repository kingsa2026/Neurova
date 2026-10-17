# -*- coding: utf-8 -*-
r"""活体（批 70·§6-298）：把恒空那一档拆掉之后，主路的读数必须与拆之前**逐条相等**。

这一批不新增能力、不改变可达性——它只做退役。所以判据不是"新行为对不对"，而是
**差分**：同一份脚本在 HEAD 基线树与本批侧各跑一次，四条 READOUT 读数必须完全一致。
不相等就说明"那一档其实有人在用"，本批按回归处置（回第 3 段修根因），不许拿"应该没区别"过关。

读数四项（全部经真装配：`create_app()` + lifespan 起的真 agent + 真 `agent.tool_executor`）：
① 未知工具经真咽喉的落点读数；
② 只注册在端点单例里的工具经真咽喉的落点读数（§6-297 取证读数②的那一形，本批不许改变它）；
③ builtin 工具（`recall_history`，空会话）的执行读数；
④ `on_tool_executed` 实际收到的 tool_source 取值集合——"mcp" 这个标签在两侧都应无产出者
   （恒空那档全仓不可达，§6-297 结构事实）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaB70Retire")
DATA = REPO / "data"

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402

FAILURES = []


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


BEFORE = fingerprint()


def leg(name, ok, reading):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {reading}")
    if not ok:
        FAILURES.append(name)


def summarize(outcome):
    if not isinstance(outcome, dict):
        return {"type": type(outcome).__name__}
    return {
        "keys": sorted(str(k) for k in outcome)[:6],
        "error": str(outcome.get("error"))[:70] if outcome.get("error") else None,
        "success": outcome.get("success"),
    }


app = create_app()
sources = []

with TestClient(app) as client:
    from neurova.api.endpoints import get_agent_instance
    from neurova.api.endpoints import tool_layers as TL

    agent = get_agent_instance()
    executor = agent.tool_executor
    executor.on_tool_executed = lambda **kw: sources.append(str(kw.get("tool_source")))

    engine = TL.get_tool_engine()

    def probe_tool(**kwargs):
        return {"ran": True}

    engine.register_tool(tool_name="b70_singleton_only", tool_func=probe_tool, description="活体探针")

    r1 = summarize(asyncio.run(executor.execute("b70_unknown_tool", {})))
    r2 = summarize(asyncio.run(executor.execute("b70_singleton_only", {})))
    r3 = summarize(asyncio.run(executor.execute("recall_history", {"query": "b70-nobody"})))
    hadError = r2.get("error") or ""
    r2RanTool = "b70_singleton_only" not in hadError

leg("①未知工具经真咽喉有诚实错误读数（不是假成功）",
    r1.get("error") and "未知工具" in r1["error"],
    f"读数={json.dumps(r1, ensure_ascii=False)}")

leg("②只注册在端点单例里的工具，主路仍落回'未知工具'（本批不改可达性）",
    bool(r2.get("error")) and "未知工具" in str(r2.get("error")),
    f"读数={json.dumps(r2, ensure_ascii=False)}；该工具被主路跑起来={r2RanTool}")

leg("③builtin 档照常执行（有读数，不是异常）",
    r3.get("error") is None or "未知工具" not in str(r3.get("error")),
    f"读数={json.dumps(r3, ensure_ascii=False)}")

leg("④on_tool_executed 收到的 tool_source 集合里没有 'mcp'（那一档无产出者）",
    "mcp" not in sources,
    f"收到的 tool_source={sources}")

AFTER = fingerprint()
leg("⑤仓内 data/ 未被写入", BEFORE == AFTER, f"md5 {BEFORE[:12]} -> {AFTER[:12]}（数据根={ROOT}）")

print("READOUT " + json.dumps({"r1": r1, "r2": r2, "r3": r3, "sources": sorted(set(sources))},
                              ensure_ascii=False, sort_keys=True))
print("\n" + ("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}"))
sys.exit(0 if not FAILURES else 1)
