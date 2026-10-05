"""外部 Agent 通信域的身份单源

取证（`.tmp_probe` 已删，结论记在 audit-reports/agent-communication-identity-*.md）：
路由级已有 `APIRouter(dependencies=[Depends(get_current_user)])` 硬门，所以
- 无凭证 → 401，无效 token → 401：**不存在**"坏 token 静默落到 default"的现行入口
  （这与本报告先前那条判断不同，已更正）；
- 只带 `X-API-Key` → 401：解析器里那条 api-key 分支**根本不可达**，且全仓零消费者
  （NeurUI 那处 `x-api-key` 是 provider 出网配置，`channels/websocket.py` 是渠道自有
  鉴权头，都与本域无关）；
- 但同一枚合法 token 会得到两份答案：HTTPBearer 大小写不敏感，`bearer <jwt>` 能过门；
  而端点级解析器写的是 `authorization.startswith("Bearer ")`，认不下小写 →
  一路落到 `{"user_id": "default"}`。实测：用 `bearer` 生成的密钥被贴到 default 租户，
  再用 `Bearer` 列表就看不见它。**同一条凭证跨租户，正是本域所有隔离键的落点**
  （`auth["user_id"]` 是 api-keys / handshakes / external agents / messages 的分区键）。

修法即教义第 6 条：身份只留一处解析。端点直接取路由级那道门已经解析好的用户，
删掉第二份 header 解析（连带那条不可达的 api-key 分支与 `default` 兜底）。

装配口径：不打 lifespan（本组断言只涉及鉴权与 api-keys 表），但用真 `create_app`
路由与真依赖，不做任何 dependency_overrides——否则测的就不是那道门了。
"""

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.auth import create_access_token, get_current_user
from neurova.api.endpoints import agent_communication_api as comm

BASE = "/api/v1/agent-communication/api-keys"
TOKEN = create_access_token(
    {"sub": "ext-alice", "username": "ext-alice", "role": "user", "neuser_id": "ne-ext-alice"}
)


@pytest.fixture
def client():
    """真路由 + 真鉴权门，但不打 lifespan（本组断言只涉及鉴权与 api-keys 表）；
    api-keys 是模块级全局，进出各清一次，不给同进程后续用例留租户脏数据。"""
    saved = dict(comm._api_keys)
    comm._api_keys.clear()
    yield TestClient(create_app())
    comm._api_keys.clear()
    comm._api_keys.update(saved)


def _bearer(scheme: str) -> dict:
    return {"Authorization": f"{scheme} {TOKEN}"}


class TestIdentityIsSingleSource:
    def test_casingDoesNotChangeTheTenant(self, client):
        """同一枚合法 token，`Bearer` 与 `bearer` 必须解析成同一个人"""
        assert client.post(BASE, json={"name": "k-upper"}, headers=_bearer("Bearer")).status_code == 200
        assert client.post(BASE, json={"name": "k-lower"}, headers=_bearer("bearer")).status_code == 200

        listed = client.get(BASE, headers=_bearer("Bearer")).json()["data"]["api_keys"]
        names = sorted(k["name"] for k in listed)
        assert names == ["k-lower", "k-upper"], f"小写 scheme 的密钥落到了别的租户：可见={names}"

    def test_noSecondHeaderParserInThisModule(self):
        """本域不得再有自己的 Bearer 解析：身份只能来自 `get_current_user` 这一道门"""
        assert not hasattr(comm, "_verify_api_key_or_token"), (
            "第二份身份解析仍在：它与路由级那道门会同求异解"
        )

    def test_everyRouteUsesTheRouterGateIdentity(self):
        offenders = []
        for route in comm.router.routes:
            calls = []
            stack = list(getattr(route, "dependant", None) and route.dependant.dependencies or [])
            while stack:
                dep = stack.pop()
                if getattr(dep, "call", None) is not None:
                    calls.append(dep.call)
                stack.extend(getattr(dep, "dependencies", []) or [])
            if get_current_user not in calls:
                offenders.append(str(route.path))
        assert offenders == [], "以下端点未复用路由级身份：" + ", ".join(offenders)


class TestAuthSurfaceIsNotWeakened:
    """这几条今天就是 401，钉住它们是为了证明本批没有顺手放宽"""

    def test_missing_credentials_still_401(self, client):
        assert client.post(BASE, json={"name": "k"}).status_code == 401

    def test_invalid_token_still_401(self, client):
        assert client.post(
            BASE, json={"name": "k"}, headers={"Authorization": "Bearer not-a-jwt"}
        ).status_code == 401

    def test_api_key_alone_is_not_a_credential_today(self, client):
        """`nk_` 密钥当前**不是**可用凭证（路由级门先拦）。
        这是被登记的能力缺口（要外部 Agent 用密钥认证就得改门），不是本批偷偷放开的口子。"""
        r = client.post(BASE, json={"name": "k"}, headers={"X-API-Key": "nk_whatever"})
        assert r.status_code == 401, f"密钥单独使用竟被放行：{r.status_code} {r.text[:120]}"
