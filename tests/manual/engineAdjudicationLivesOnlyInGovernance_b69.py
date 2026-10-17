# -*- coding: utf-8 -*-
r"""活体（批 69·§6-295 乙）：那条"无 agent ⇒ 引擎直调"的回落支，今天必须经治理。

装配点全部走生产：真 `create_app()` + `fastapi.TestClient` + 真 `create_access_token()`，
端点函数按真路由表取（`app.openapi()["paths"]`），引擎用真单例 `get_tool_engine()`。

改前实状（同一份脚本在基线树上的读数）：
- 第 ①② 腿 **FAIL**——`{"file_path": "/etc/shadow"}` 与换键名的 `{"target": "/etc/shadow"}` 都
  把探针工具真跑了（回包 `code=0` 带着工具回显的受保护路径），因为那一支唯一的守卫是
  `DefaultGuard`（恒 `safe=True`，`neurova/` 内无一处传 `tool_guard=`）；
- 第 ⑤ 腿 **FAIL**——两把引擎都还带着那个恒 safe 的门（`__init__` 还收 `tool_guard`）。
第 ③④⑥ 腿两侧同绿：它们是**对照**，钉"接治理"没被做成一律拒、也没把主路改坏。

② 那条的探针工具**必须也注册进同一把引擎**——不然基线侧报的是"未找到可用执行路径"而不是
"真跑了"，那条腿就白绿一次（判据要能反证，取值不能太干净＝形态集 239 那一族）。

反证形态＝同一份脚本在 HEAD 基线树跑（本批生产字节退回旧形态），不必改判据。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaGuardB69")
DATA = REPO / "data"

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.execution_engine.tool_engine import ToolEngine  # noqa: E402

SHADOW = "/etc/shadow"
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


app = create_app()
EXECUTE_PATH = next((p for p in app.openapi()["paths"] if p.endswith("/tools/execute")), "")
HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b69-probe-user'})}"}

import neurova.api.endpoints as EP  # noqa: E402
from neurova.api.endpoints import tool_layers as TL  # noqa: E402

ran = {"count": 0, "lastEcho": ""}


def peek(**kwargs):
    ran["count"] += 1
    ran["lastEcho"] = str(kwargs.get("file_path") or kwargs.get("target") or kwargs.get("note") or "ok")
    return {"toolRan": True, "echoed": ran["lastEcho"]}


def postThrough(client, tool_name, arguments):
    """返回 (回包, 工具这次有没有真跑)——后者按执行次数增量判，不看回包措辞。"""
    before = ran["count"]
    response = client.post(EXECUTE_PATH, headers=HDR,
                           json={"tool_name": tool_name, "arguments": arguments})
    return response.json(), ran["count"] > before


with TestClient(app) as client:
    engine = TL.get_tool_engine()
    engine.register_tool("b69_probe_tool", peek, "活体探针：把收到的参数回显")
    # 动态来源那一腿也要能咬：不注册进同一把引擎，基线侧报的是"未找到可用执行路径"而不是"真跑了"
    engine.register_tool("mcp.demo.b69peek", peek, "活体探针（换键名那一形）")

    agentInPlace = EP.get_agent_instance()
    # ④ 主路（agent 在场）：治理在引擎之前拦——这条腿两侧都该绿
    throatBody, throatRan = postThrough(client, "b69_probe_tool", {"file_path": SHADOW})

    # ①② 支路（无 agent ⇒ 引擎直调）：本批要根修的就是这一支
    EP.get_agent_instance = lambda agent_id="": None
    keyNameBody, keyNameRan = postThrough(client, "b69_probe_tool", {"file_path": SHADOW})
    renamedBody, renamedRan = postThrough(client, "mcp.demo.b69peek", {"target": SHADOW})
    # ③ 对照：无可裁决内容仍要放行（既有反向锁依赖它）
    benignBody, benignRan = postThrough(client, "b69_probe_tool", {"note": "hello"})

    noGuardAttr = not hasattr(engine, "tool_guard")
    initArgs = list(ToolEngine.__init__.__code__.co_varnames[:ToolEngine.__init__.__code__.co_argcount])

leg("①受保护路径经真 HTTP 被拒，且工具没跑",
    not keyNameRan and keyNameBody.get("code") == 1 and "治理" in str(keyNameBody.get("error")),
    f"回包={str(keyNameBody)[:150]}；该次工具真跑={keyNameRan}")

leg("②换键名的动态来源调用同样被拒（scan_all 那一刀接上了）",
    not renamedRan and renamedBody.get("code") == 1,
    f"mcp.demo.b69peek + target ⇒ {str(renamedBody)[:150]}；该次工具真跑={renamedRan}")

leg("③无可裁决内容仍放行（不许做成一律拒）",
    benignRan and benignBody.get("code") == 0,
    f"工具真跑={benignRan}；回包={str(benignBody)[:120]}")

leg("④主路不受本批影响：agent 在场仍由治理拦在引擎之前",
    not throatRan and throatBody.get("code") == 1 and type(agentInPlace).__name__ == "Agent",
    f"agent={type(agentInPlace).__name__}；工具真跑={throatRan}；回包={str(throatBody)[:150]}")

leg("⑤真装配的两把引擎都没有裁决口了",
    noGuardAttr and "tool_guard" not in initArgs,
    f"hasattr(engine,'tool_guard')={not noGuardAttr}；__init__ 形参={initArgs}")

AFTER = fingerprint()
leg("⑥仓内 data/ 未被写入", BEFORE == AFTER, f"md5 {BEFORE[:12]} -> {AFTER[:12]}（数据根={ROOT}）")

print("\n" + ("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}"))
sys.exit(0 if not FAILURES else 1)
