# -*- coding: utf-8 -*-
r"""活体（批 72·§6-299 丙）：工具归属从注册面一路走到对外契约，中间不被动字面量。

装配点全部走生产，不用 Mock 冒充业务对象：
- **写侧**是真 `MCPToolClient._sync_tools_to_engine(...)`（它才是 MCP 工具进注册面的那条路，
  打的是 `tags=["mcp", server_id]`）；
- **读侧**是真 `GET /api/v1/tool-layers/tools`（`create_app()` + lifespan + 真 JWT）。
两头之间就是本批要证的那一段：列表面不再把外部 server 提供的工具说成内置。

改前实状（同一份脚本在基线树上的读数）：①③④ 三腿 **FAIL**——
① 那条 MCP 工具在列表面里读回 `source='builtin'`、`server_id=None`（写侧带的 tags 被丢在列表面里）；
③ `?source=mcp` 过滤为空、而 `?source=builtin` 里混进了它；
④ 无 tag／无 owner 的动态注册也被顶替成 `builtin`。
② 那条是**对照**（真内置 `file_read` 仍该是 `builtin`），两侧同绿——本批改的是猜，不是这条事实。
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

ROOT = isolatedDataRoot(prefix="neurovaOwnershipB72")
DATA = REPO / "data"

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402

SERVER_ID = "srv-live-b72"
MCP_TOOL = f"mcp.{SERVER_ID}.peek"
DYNAMIC_TOOL = "b72_bare_dynamic"
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
LIST_PATH = next((p for p in app.openapi()["paths"] if p.endswith("/tool-layers/tools")), "")
HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b72-user'})}"}

with TestClient(app) as client:
    from neurova.api.endpoints import tool_layers as TL
    from neurova.execution_engine.tool_engine import ToolStatus
    from neurova.tool_layers.mcp_client import MCPToolClient

    engine = TL.get_tool_engine()
    MCPToolClient(user_id="b72-user")._sync_tools_to_engine(
        SERVER_ID, [{"name": "peek", "description": "活体探针"}], engine=engine)
    engine.register_tool(tool_name=DYNAMIC_TOOL, tool_func=lambda **kw: {"ran": True},
                         description="活体探针（无 tag 无 owner）", status=ToolStatus.AVAILABLE)

    def listing(source=None):
        url = LIST_PATH + (f"?source={source}" if source else "")
        entries = {t["tool_id"]: t for t in client.get(url, headers=HDR).json()}
        return entries

    all_ = listing()
    mcpOnly = listing(source="mcp")
    builtinOnly = listing(source="builtin")

entry = all_.get(MCP_TOOL) or {}
leg("①MCP 工具经真写侧进注册面后，对外契约带出来源与所属 server",
    entry.get("source") == "mcp" and entry.get("server_id") == SERVER_ID,
    f"列表面条目={ {k: entry.get(k) for k in ('tool_id', 'source', 'server_id')} }")

builtinEntry = all_.get("file_read") or {}
leg("②对照：真内置（源 2）仍是 builtin，本批不许把它改坏",
    builtinEntry.get("source") == "builtin" and builtinEntry.get("server_id") is None,
    f"file_read 条目={ {k: builtinEntry.get(k) for k in ('source', 'server_id')} }")

leg("③?source= 过滤按注册声明分得开",
    MCP_TOOL in mcpOnly and MCP_TOOL not in builtinOnly and "file_read" in builtinOnly,
    f"source=mcp 面含它={MCP_TOOL in mcpOnly}；source=builtin 面仍混着它={MCP_TOOL in builtinOnly}")

dynEntry = all_.get(DYNAMIC_TOOL) or {}
leg("④无 tag／无 owner 的动态注册回中性值，不再顶替成 builtin",
    dynEntry.get("source") == "dynamic",
    f"条目={ {k: dynEntry.get(k) for k in ('tool_id', 'source', 'server_id')} }")

AFTER = fingerprint()
leg("⑤仓内 data/ 未被写入", BEFORE == AFTER, f"md5 {BEFORE[:12]} -> {AFTER[:12]}（数据根={ROOT}）")

print("\n" + ("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}"))
sys.exit(0 if not FAILURES else 1)
