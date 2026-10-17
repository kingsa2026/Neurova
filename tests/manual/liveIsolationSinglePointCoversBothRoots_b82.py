# -*- coding: utf-8 -*-
"""活体（批 82）：只调 `isolatedDataRoot()` 一支，真 app 真建 agent 之后仓内一根都不动。

这一支刻意**不调** `isolatedAgentWorkspaces()`——它验的就是"第二根由单点保证"这件事本身。
两侧同跑（基线＝单点只隔数据根的 HEAD，本批侧＝两根一起隔），四组读数：

① **真链路照跑**：`POST /api/v1/agents` 经真 `create_app()` + lifespan + 真 JWT(`role=admin`) 建出一个
   agent，2xx。这一格两侧同绿——它证的是"改单点没把功能面改坏"，不证差异。
② **本批差异腿**：新建 agent 的工作区落点必须在**临时根**下，不得是仓内 `<repo>/agent_workspaces/<id>`。
   基线侧必须 FAIL（那正是 §6-308 的 D8 实测：`POST /api/v1/agents` 在仓根新建了两个 workspace 目录）。
③ **仓内两根指纹不变**：`data/` 与 `agent_workspaces/` 的内容指纹跑前跑后逐字节同。
   这是"70 档起真 app 的探针往仓里写"这一族的收口证据；基线侧这一格也应 FAIL（仓内多了一个目录）。
④ **正控**：同进程里 `get_agent_workspaces_root()` 取到的就是单点给的那一份（证明②③看的根与
   生产实际用的根是同一个，而不是探针自己另拼的第二个落点——形态集 263 那一族：先证"我看见那一行了"）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# 刻意剥掉这两个 env：本探针要验的就是"单点自己会不会把第二根隔上"，
# 父 shell 里若已注入，幂等分支会直接沿用，读数就变成假的。
for _k in ("NEUROVA_DATA_DIR", "NEUROVA_AGENT_WORKSPACES_DIR"):
    os.environ.pop(_k, None)

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

DATA_ROOT = isolatedDataRoot(prefix="neurovaB82")   # ← 只调这一支
FAILURES = []

WS_IN_REPO = REPO / "agent_workspaces"
DATA_DIR = REPO / "data"


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


BEFORE = (treeFingerprint(DATA_DIR), treeFingerprint(WS_IN_REPO))


def leg(name: str, ok: bool, reading: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {reading}")
    if not ok:
        FAILURES.append(name)


from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core.agent_workspaces import get_agent_workspace_dir, get_agent_workspaces_root  # noqa: E402

HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b82-user', 'role': 'admin'})}"}
app = create_app()
paths = set(app.openapi()["paths"])
agentsPath = next((p for p in paths if p.endswith("/api/v1/agents")), "")

codes: dict[str, int] = {}
created: dict[str, object] = {}
with TestClient(app) as client:
    codes[f"GET {agentsPath}"] = client.get(agentsPath, headers=HDR).status_code
    r = client.post(agentsPath, json={"name": "b82-isolation-probe"}, headers=HDR)
    codes[f"POST {agentsPath}"] = r.status_code
    created = r.json() if r.status_code < 300 else {}

agentId = str(created.get("agent_id") or "")

leg("①真 app 上多 Agent 面照跑（列表/创建）",
    bool(agentsPath) and len(codes) == 2 and all(200 <= c < 300 for c in codes.values()),
    f"路由={agentsPath or '<取不到>'} 状态码={codes} agent_id={agentId or '<未建成>'}")

wsRoot = get_agent_workspaces_root()
inside = agentId and (get_agent_workspace_dir(agentId).resolve() == (WS_IN_REPO / agentId).resolve())
leg("②新建 agent 的工作区必须落在临时根下（基线侧这一格必须 FAIL＝D8 本体）",
    bool(agentId) and not inside and wsRoot.resolve() != WS_IN_REPO.resolve(),
    f"单源给的根={wsRoot} 本次 agent 目录={get_agent_workspace_dir(agentId) if agentId else '<无>'}")

AFTER = (treeFingerprint(DATA_DIR), treeFingerprint(WS_IN_REPO))
leg("③仓内 data/ 与 agent_workspaces/ 内容指纹全程不变",
    BEFORE == AFTER,
    f"data {BEFORE[0][:12]}->{AFTER[0][:12]}  agent_workspaces {BEFORE[1][:12]}->{AFTER[1][:12]}")

leg("④正控：探针读的根＝生产用的根（同一单源解析器，不是另拼的第二份）",
    str(Path(os.environ.get("NEUROVA_AGENT_WORKSPACES_DIR", "")).resolve()) == str(wsRoot.resolve())
    and str(Path(os.environ.get("NEUROVA_DATA_DIR", "")).resolve()) == str(DATA_ROOT.resolve()),
    json.dumps({"env_ws": os.environ.get("NEUROVA_AGENT_WORKSPACES_DIR", "<未注入>"),
                "resolver_ws": str(wsRoot), "env_data": os.environ.get("NEUROVA_DATA_DIR", "<未注入>")},
               ensure_ascii=False))

print("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}")
sys.exit(0 if not FAILURES else 1)
