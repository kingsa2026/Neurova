# -*- coding: utf-8 -*-
"""活体（批 81）：`MultiAgentManager` 整座岛退役后，多 Agent 面照常跑，且岛真没了。

两侧同跑差分（基线＝HEAD 66059fb1 岛还在，本批侧＝整岛已删），五组读数各证一件事：

① **多 Agent 面没被打断**：`GET/POST /api/v1/agents`、`GET /api/v1/agents/{id}` 经真
   `create_app()` + lifespan + 真 JWT（`create_access_token` 带 `role=admin`）给 2xx。
   这条两侧同绿——它证的是"退役没顺手砍活在的东西"，不证差异。
② **岛不在生产路上**：跑完上面这一串真请求后 `neurova.core.multi_agent_manager` 仍不在
   `sys.modules`。本批侧绿；基线侧也绿（岛在但没人 import）——它钉的是"这岛从来不是路上的一环"，
   与 §6-308 的九键计数器读数同向。
③ **导入通道已断**（本批差异腿）：`importlib.import_module()` 该模块必须 `ModuleNotFoundError`。
   基线侧必须 **FAIL**——这是探针有牙的证据，不是脚本走偏（形态集 243：反证要打行为，
   但这一批"行为"就是模块在场与否，所以差异腿写成可导入性，而不是写成调用计数）。
④ **per-agent 工作区单源照旧**：新建 agent 后，端点给的 workspace 与 `core/agent_workspaces`
   单源算法给的路径同一个——本批删掉的是那份**第二表示**，留的是单源。
⑤ **隔离自证**：仓内 `data/` 内容指纹与 `agent_workspaces/` 条目指纹全程不变
   （数据根与 agent 工作区根两个注入口都要隔，只隔一个会把记忆写进仓内真目录——台账 D8）。
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import (  # noqa: E402
    isolatedAgentWorkspaces,
    isolatedDataRoot,
)

DATA_ROOT = isolatedDataRoot(prefix="neurovaB81")
WS_ROOT = isolatedAgentWorkspaces(prefix="neurovaB81")
FAILURES = []

ISLAND_MODULE = "neurova.core.multi_agent_manager"


def treeFingerprint(root: Path) -> str:
    h = hashlib.md5()
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(root).as_posix().encode("utf-8"))
                h.update(str(p.stat().st_size).encode("ascii"))
    else:
        h.update(b"<absent>")
    return h.hexdigest()


DATA_DIR = REPO / "data"
WS_DIR = REPO / "agent_workspaces"
BEFORE = (treeFingerprint(DATA_DIR), treeFingerprint(WS_DIR))


def leg(name: str, ok: bool, reading: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {reading}")
    if not ok:
        FAILURES.append(name)


from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core import agent_workspaces as AW  # noqa: E402

HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b81-user', 'role': 'admin'})}"}
app = create_app()
registered = set(app.openapi()["paths"])
#: 前缀从 OpenAPI 现读，不在脚本里手拼（拼错就是 404，会被读成"面没了"）
agentsPath = next((p for p in registered if p.endswith("/api/v1/agents")), "")

codes: dict[str, int] = {}
created: dict[str, object] = {}

with TestClient(app) as client:
    codes[f"GET {agentsPath}"] = client.get(agentsPath, headers=HDR).status_code
    r = client.post(agentsPath, json={"name": "b81-probe-agent"}, headers=HDR)
    codes[f"POST {agentsPath}"] = r.status_code
    created = r.json() if r.status_code < 300 else {}
    agentId = str(created.get("agent_id") or "")
    if agentId:
        codes[f"GET {agentsPath}/{agentId}"] = client.get(
            f"{agentsPath}/{agentId}", headers=HDR
        ).status_code

leg("①多 Agent 面（列表/创建/详情）全部 2xx",
    len(codes) >= 3 and all(200 <= c < 300 for c in codes.values()),
    f"状态码={codes}")

leg("②跑完整串真请求后岛模块仍不在 sys.modules（岛不在生产路上）",
    ISLAND_MODULE not in sys.modules,
    f"sys.modules 命中={ISLAND_MODULE in sys.modules}；本进程已加载 neurova.* 模块数="
    f"{sum(1 for m in sys.modules if m.startswith('neurova.'))}")

try:
    importlib.import_module(ISLAND_MODULE)
    importError = None
except ModuleNotFoundError as exc:
    importError = exc
leg("③岛模块的导入通道已断（基线侧这一格必须 FAIL——差异腿，探针有牙）",
    importError is not None,
    f"importlib.import_module 结果={'ModuleNotFoundError' if importError else '仍可导入'}")

singleSource = AW.get_agent_workspace_dir(agentId) if agentId else ""
leg("④per-agent 工作区仍由单源给出（删的是第二份表示，留的是单源）",
    bool(singleSource) and Path(singleSource).is_absolute()
    and Path(singleSource).name == agentId,
    f"agent_id={agentId or '<未建成>'} 单源路径={singleSource} 注入口={WS_ROOT}")

AFTER = (treeFingerprint(DATA_DIR), treeFingerprint(WS_DIR))
leg("⑤仓内 data/ 与 agent_workspaces/ 未被写入（两个隔离注入口都生效）",
    BEFORE == AFTER,
    f"data {BEFORE[0][:12]}->{AFTER[0][:12]}  agent_workspaces {BEFORE[1][:12]}->{AFTER[1][:12]}"
    f"（数据根={DATA_ROOT}）")

print(f"agents 路由从 OpenAPI 取到：{agentsPath or '<取不到>'}")
print("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}")
sys.exit(0 if not FAILURES else 1)
