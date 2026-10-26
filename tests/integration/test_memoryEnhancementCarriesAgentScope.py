"""增强族按 id 寻址要带 `agent_id`：否则它打的是**另一个 Agent 的那份库**（点单「下一批」＝§6-429 仍开①）

缺陷现场（复核实状，全部现算）：`neurova/api/endpoints/memory_enhancement.py` 六条腿
（`/{id}/forget`、`/{id}/strengthen`、`/batch`、`/export`、`/import`、`/categories`）
一律走 `_require_memory_manager(user)`，而它里面是 `get_memory_manager(None, user)`
——**None 就是 default**。于是非默认 Agent 页面上的这些动作与读数，全部打在默认 Agent 的库上。

严重性不是「按钮失灵」，是**静默改错行**：记忆 id 由 `manager.py:1624` 的
`f"mem_{self._counter:06d}"` 铸——计数器**每个 Agent 库各有一份**，所以两个 Agent 库里
出现同一个 id 是设计使然而非意外。现网实测：`data/default/memory/neurova_memories_persist.db`
24 行、`data/kai/memory/neurova_memories_persist.db` 6 行，同 id 跨库已有 1 对（`mem_000006`）。
本文件用两库各造一行，把「同 id」钉成可读前提，再问：在 kai 上按 ↑，被改的是 kai 的行还是 default 的行。

处置口径不新造：**与 §6-425/§6-426 已裁的那几条腿一字同规**——读改删腿早已改成
`get_memory_manager(agent_id, user)` + 逐条归属校验（他人作用域「视同不存在」）。
本批只是把同一条规则的剩下六条腿接上，**不放宽隔离，也不给管理员开特权面**
（要不要给增强族开 agent-wide 管理通道属产品裁决，登记仍开）。

夹具形态：router、鉴权依赖、`get_memory_manager`、`MemoryManager` 全是生产实现，
只把 `get_app_state` 换成供出两个真 manager（各自独立 db 文件）的桩；造数走生产写路
`POST /api/v1/memory?agent_id=<那个库>`，身份用 `create_access_token()` 签的真 JWT，
不用 `dependency_overrides`（路由级那道门它替不掉，§6-427 记过这个坑）。
"""

import ast
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import memory_enhancement
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests import ast_scan
from tests.auth_headers import pinJwtSecret, signedBearerHeaders

ENHANCE = "/api/v1/memory-enhancement"
ENHANCE_SOURCE = Path("neurova/api/endpoints/memory_enhancement.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """两个真库 + 生产路由；`get_agent()` 恒回落 default —— 这就是缺陷的形状。

    凭证在**用例内现签**：`tests/test_api` 里有档 `pinJwtSecret()` 把轮内密钥对齐后
    **不复原**（那是它自己写明的口径），所以模块级 import 期签的头会在全轮跑时变成
    「刚签的令牌被自己拒」。仓内同一问题的正解就在
    `tests/test_api/test_memory_route_shadowing.py`：先 `pinJwtSecret()` 对齐，再
    `signedBearerHeaders()` 现签——签名与验签必须同源。
    """
    pinJwtSecret()
    speaker = signedBearerHeaders("speaker-1", user_id="speaker-1", neuser_id="speaker-1")
    other = signedBearerHeaders("alice", user_id="alice", neuser_id="ne-alice")

    managers = {
        agent: MemoryManager(db_path=str(tmp_path / f"{agent}.db"), agent_id=agent)
        for agent in ("default", "kai")
    }
    agents = {agent: types.SimpleNamespace(memory_manager=m) for agent, m in managers.items()}
    state = types.SimpleNamespace(agents=agents, get_agent=lambda *a, **k: agents["default"])
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: state)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    app.include_router(memory_enhancement.router, prefix=ENHANCE)
    return TestClient(app, headers=speaker), managers, other


def _create(client, managers, agent, content, category="general", headers=None):
    """经生产写路在指定 Agent 库里造一行，返回它的 id。"""
    response = client.post(
        "/api/v1/memory",
        json={"content": content, "category": category, "auto_classify": False},
        params={"agent_id": agent},
        **({'headers': headers} if headers else {}),
    )
    assert response.status_code == 200, response.text
    memoryId = response.json()["data"]["memory_id"]
    managers[agent].set_request_scope(neuser_id="speaker-1", user_id="speaker-1")
    return memoryId


def _seedSameIdInBothStores(client, managers) -> str:
    """在两库各造一行；id 相同是本文件的前提（铸号每库自增），不相同就当场改判。"""
    defaultId = _create(client, managers, "default", "DEFAULT库的行")
    kaiId = _create(client, managers, "kai", "KAI库的行")
    assert defaultId == kaiId, (
        f"铸号形态与前提不符（原假设每库自增 mem_%06d ⇒ 跨库同 id）：{defaultId} vs {kaiId}；"
        "若已改成全局唯一 id，本文件「改错行」那半边要改判，「打错库」那半边照旧成立"
    )
    # 夹具自证：两库真的是两份数据（若共享一个存储，"另一库没被改"那半句就是空话）
    assert _row(managers, "default", defaultId)["content"] == "DEFAULT库的行"
    assert _row(managers, "kai", kaiId)["content"] == "KAI库的行"
    return defaultId


def _row(managers, agent: str, memoryId: str) -> dict:
    managers[agent].set_request_scope(neuser_id="speaker-1", user_id="speaker-1")
    return managers[agent].get_memory(memoryId, agent_wide=True) or {}


# ============================================================
# 行为断言：带 agent_id 的六条腿必须落在那个 Agent 的库上
# ============================================================


def test_strengthenScopedToAgentMovesOnlyThatStore(env):
    client, managers, other = env
    memoryId = _seedSameIdInBothStores(client, managers)
    before = _row(managers, "kai", memoryId).get("importance")

    response = client.post(
        f"{ENHANCE}/{memoryId}/strengthen",
        json={"importance_boost": 0.3},
        params={"agent_id": "kai"},
    )
    assert response.status_code == 200, response.text

    assert _row(managers, "kai", memoryId).get("importance") != before, "指定了 kai，kai 的行却没动"
    assert _row(managers, "default", memoryId).get("importance") == before, (
        "default 的同 id 行被顺手改了（在 kai 页面按 ↑ 动的是 default 的记忆）"
    )


def test_forgetScopedToAgentSoftDeletesOnlyThatStore(env):
    client, managers, other = env
    memoryId = _seedSameIdInBothStores(client, managers)

    response = client.post(
        f"{ENHANCE}/{memoryId}/forget",
        json={"reason": "手动遗忘"},
        params={"agent_id": "kai"},
    )
    assert response.status_code == 200, response.text

    assert _row(managers, "kai", memoryId).get("lifecycle_stage") == "forgotten"
    assert _row(managers, "default", memoryId).get("lifecycle_stage") != "forgotten", (
        "在 kai 页面按 ↓，default 的同 id 行被静默软删"
    )


def test_batchScopedToAgentLandsOnlyThatStore(env):
    client, managers, other = env
    memoryId = _seedSameIdInBothStores(client, managers)

    response = client.post(
        f"{ENHANCE}/batch",
        json={"memory_ids": [memoryId], "operation": "forget", "params": {}},
        params={"agent_id": "kai"},
    )
    assert response.status_code == 200, response.text

    assert _row(managers, "kai", memoryId).get("lifecycle_stage") == "forgotten"
    assert _row(managers, "default", memoryId).get("lifecycle_stage") != "forgotten"


def test_exportScopedToAgentDumpsOnlyThatStore(env):
    client, managers, other = env
    _create(client, managers, "default", "DEFAULT-SECRET-不该出现在kai导出里")
    _create(client, managers, "kai", "KAI-要导出的行")

    response = client.get(f"{ENHANCE}/export", params={"agent_id": "kai"})
    assert response.status_code == 200, response.text
    dumped = str(response.json()["data"]["memories"])

    assert "KAI-要导出的行" in dumped
    assert "DEFAULT-SECRET-不该出现在kai导出里" not in dumped, "在 kai 页面导出的是 default 那份库"


def test_categoriesScopedToAgentAggregatesOnlyThatStore(env):
    client, managers, other = env
    # 取值用 `AddMemoryRequest.category` 声明的真实枚举（general/conversation/knowledge/
    # experience/…）——上一轮我在这里自造了 'cat-kai-only'，被写侧归一成 general，
    # 于是这格红了两次：第一次红在"读的是 default 库"，第二次红在我自己的夹具（形态 429 同族）。
    _create(client, managers, "default", "default 的行", category="knowledge")
    _create(client, managers, "kai", "kai 的行", category="experience")

    response = client.get(f"{ENHANCE}/categories", params={"agent_id": "kai"})
    assert response.status_code == 200, response.text
    names = {row["category"] for row in response.json()}

    assert "experience" in names, f"kai 库的类目没出现在聚合里，实得 {names}"
    assert "knowledge" not in names, "分类聚合读的是 default 那份库"


def test_importScopedToAgentWritesOnlyThatStore(env):
    client, managers, other = env
    _create(client, managers, "default", "default 已有的行")

    response = client.post(
        f"{ENHANCE}/import",
        json={"memories": [{"content": "导入进kai的行", "category": "imported"}], "merge_mode": "skip"},
        params={"agent_id": "kai"},
    )
    assert response.status_code == 200, response.text

    kaiContents = [str(m.get("content")) for m in managers["kai"].get_memories(agent_wide=True, limit=1000)]
    defaultContents = [
        str(m.get("content")) for m in managers["default"].get_memories(agent_wide=True, limit=1000)
    ]
    assert any("导入进kai的行" in c for c in kaiContents), "导入没落进指定的那个库"
    assert not any("导入进kai的行" in c for c in defaultContents), "导入落到了 default 那份库"


# ============================================================
# 反向格：既有语义一处都不许被顺手改掉
# ============================================================


def test_withoutAgentIdStillFallsBackToDefault(env):
    client, managers, other = env
    memoryId = _create(client, managers, "default", "default 的行")

    response = client.post(f"{ENHANCE}/{memoryId}/strengthen", json={"importance_boost": 0.3})
    assert response.status_code == 200, response.text

    assert _row(managers, "default", memoryId), "缺省路径不再动 default —— 既有回落语义被摘了"
    assert managers["kai"].get_memories(agent_wide=True, limit=10) == [], "缺省路径把动作漏进了 kai 库"


def test_unknownAgentIdIs404NotSilentFallback(env):
    client, managers, other = env
    memoryId = _create(client, managers, "default", "default 的行")

    response = client.post(
        f"{ENHANCE}/{memoryId}/forget", json={"reason": "x"}, params={"agent_id": "nope"}
    )
    assert response.status_code == 404, (
        f"未知 Agent 应当 404，实得 {response.status_code} —— 回落 default 就是静默改错库"
    )


def test_foreignScopeRowStillTreatedAsAbsent(env):
    client, managers, other = env
    otherId = _create(
        client, managers, "default", "ALICE 的行", headers=other
    )

    response = client.post(
        f"{ENHANCE}/{otherId}/forget", json={"reason": "越权尝试"}, params={"agent_id": "default"}
    )

    assert response.status_code == 404, "他人作用域的行必须仍「视同不存在」——本批不放宽隔离"
    assert _row(managers, "default", otherId).get("lifecycle_stage") != "forgotten"


# ============================================================
# 形状格：六条腿一条都不能再漏（未来的第 7 条同样被咬）
# ============================================================


def test_everyEnhancementLegThreadsAgentId(env):
    tree = ast_scan.transientTree(ENHANCE_SOURCE)
    legs = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        verbs = [
            decorator.func.attr
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
        ]
        if verbs:
            legs.append((node.name, verbs[0], node))

    assert len(legs) == 6, f"增强族命中面变了：{[name for name, _, _ in legs]}"

    noParam, notPassed = [], []
    for name, verb, node in legs:
        args = [arg.arg for arg in node.args.args]
        if "agent_id" not in args:
            noParam.append(f"{verb} {name}")
            continue
        passesToAssembly = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_require_memory_manager"
            and (len(call.args) > 1 or any(kw.arg == "agent_id" for kw in call.keywords))
            for call in ast.walk(node)
        )
        if not passesToAssembly:
            notPassed.append(f"{verb} {name}")

    assert not noParam, f"这些腿还不收 agent_id：{noParam}"
    assert not notPassed, f"这些腿收了 agent_id 却没透给装配点：{notPassed}"
