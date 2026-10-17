# -*- coding: utf-8 -*-
"""`core/multi_agent_manager.py` 整座岛退役判据（批 81 落地，裁定乙＝§6-308 票面推荐项）。

§6-308 取证的实状：这座岛（453 行）**连被 import 都没有**——真 `create_app()` + lifespan 跑完
9 个真端点（含 `POST /api/v1/agents` 真建一个 agent）之后 `neurova.core.multi_agent_manager`
不在 `sys.modules`；主动 import 它并给 9 个公开方法包计数 wrapper，再跑同一批真请求 ⇒ 计数全 0。
来历是"引入即孤岛"（该符号在 `neurova/` 的 git 史里只命中 `7835c367`「pyc 骨架恢复」一次）。

它留着有三处害，都在这份判据里有对应形状：
- 它是 **agent 工作区的第二份表示**：`get_workspace_dir()` 回"注入点目录/agent_id"，
  真单源是 `core/agent_workspaces.get_agent_workspace_dir()`（被 `api/endpoints/agent.py` 消费）。
  教义第 6 条：发现第二份定义时收口到一份并删掉另一份，不是"两边都留着"。
- 它的执行面**报假成功**：`execute_with_shared_cerebellum` 在没人注入共享组件时（生产唯一可能形态）
  回 `{"success": True}`，而 `_plan_orchestrator`／`_execution_engine`／`_infrastructure` 实值全 None。
- 它"有 759 行专用测试"会被下一个会话读成"这块有人用"——两座（`tests/integration/` 494 行 28 格、
  `tests/unit/core/` 265 行 22 格）都不在受保护子集，前者今天 `20 failed / 8 passed`，
  失败原因全是测试引用了模块里没有的东西（`Workspace`／`event_bus=`／`persona=`／`is_initialized`／`.agents`）。
  专用测试与实现同批退役，不留"实现已删、测试还在引用"。

判据两轨：主格钉"这座岛不再存在、且全仓无导入通道取它"；交付锁走**真 app + 真端点**，
钉"多 Agent 对外面与工作区单源一点没动"——少这一轨，"删了个大文件"就只剩形状。
"""
from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ISLAND = REPO_ROOT / "neurova" / "core" / "multi_agent_manager.py"
ISLAND_MODULE = "neurova.core.multi_agent_manager"
WORKSPACE_SINGLE_SOURCE = REPO_ROOT / "neurova" / "core" / "agent_workspaces.py"
AGENT_ENDPOINT = REPO_ROOT / "neurova" / "api" / "endpoints" / "agent.py"


def _importsIsland(path: pathlib.Path) -> bool:
    """该文件是否**经导入通道**取这座岛（模块路径全名判，不按 `MultiAgentManager` 这个字样扫文本）。

    不按词扫有两个理由：`get_agent`/`NeurovaAgent` 这类名字在别处各有实装（按名扫会误伤），
    而本判据文件自己也要写出模块全名一次——按词扫会被自己咬（形态集 241／268 同族）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == ISLAND_MODULE:
            return True
        if isinstance(node, ast.Import):
            if any(a.name == ISLAND_MODULE for a in node.names):
                return True
    return False


def test_islandFileIsGone():
    """主格①：整座岛的文件不再存在。"""
    assert not ISLAND.exists(), f"这座岛还在树上：{ISLAND.relative_to(REPO_ROOT)}"


def test_noCodeAnywhereImportsTheIsland():
    """主格②：全仓（生产＋测试＋脚本）不许再有任何一处经导入通道取它。

    改前读数会点名 `tests/integration/test_multi_agent_manager.py`——那正是"实现与专用测试必须同批退役"
    的证据，不是这格的误报。
    """
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        if path == ISLAND:
            continue
        if _importsIsland(path):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, f"这些地方还在导入已退役的岛：{offenders}"


def test_workspaceSingleSourceStillServesTheRealEndpoint():
    """交付锁①：工作区能力**一点没少**——真单源仍在，且对外端点仍经它取路径。

    删的是第二份表示，不是能力本身。这条若红，说明本批把 `agent_workspaces` 一起带走了。
    """
    from neurova.core.agent_workspaces import get_agent_workspace_dir

    assert WORKSPACE_SINGLE_SOURCE.exists(), "agent 工作区的唯一装配点不见了"
    path = get_agent_workspace_dir("b81-probe")
    assert path.name == "b81-probe" and path.is_absolute(), f"取根口径变了：{path}"
    tree = ast.parse(AGENT_ENDPOINT.read_text(encoding="utf-8", errors="replace"))
    taken = {n.module for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("agent_workspaces")}
    assert taken, "对外端点不再经唯一装配点取工作区路径了"


def test_multiAgentSurfaceStillServesOverTheRealApp():
    """交付锁②：多 Agent 的对外面（agents 列表／协作／通信路由）照常——岛不是它们的上游。

    §6-308 的读数里，真装配那 9 路一个都没经这座岛；本批不许把它变成"删了就少一路"。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token({'sub': 'b81-user', 'role': 'admin'})}"}
    app = create_app()
    registered = app.openapi()["paths"]
    listPath = next((p for p in registered if p.endswith("/api/v1/agents")), "")
    assert listPath, "agents 列表路由从 OpenAPI 上消失了"
    with TestClient(app) as client:
        resp = client.get(listPath, headers=headers)
    assert resp.status_code == 200, f"agents 列表不再可用：{resp.status_code} {resp.text[:160]}"
    collaboration = [p for p in registered if "communication" in p or p.startswith("/api/v1/collaboration")]
    assert collaboration, "多 Agent 协作/通信面一起没了（本批不该动它们）"
