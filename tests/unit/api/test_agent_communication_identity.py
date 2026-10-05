"""外部 Agent 通信域的身份单源与凭证合一

两阶段，各钉各的契约。

阶段一（同根因扫荡，commit `806c6f38`）：本域曾有第二份 header 解析
`_verify_api_key_or_token`，与路由级 `Depends(get_current_user)` 同求异解——
`HTTPBearer` 对 scheme 大小写不敏感（`bearer <jwt>` 能过门），而那份解析写
`startswith("Bearer ")` 认不下小写，于是**同一枚合法凭证落进两个租户**
（`auth["user_id"]` 是 api-keys / handshakes / external agents / messages 的分区键）。
实测：小写 bearer 签发的密钥在正常 Bearer 列表里看不见。修法=身份只留一处解析。
顺带更正一条旧判断："Bearer 异常被 pass 吞掉后落到 default 放行"的可达性说重了，
无凭证与无效 token 都被路由级门拦成 401——`TestAuthSurfaceIsNotWeakened` 就钉这个。

阶段二（本批，2026-10-06 拍板）：门改为 JWT 与密钥合一，密钥真相源=
`APIKeyManager`（持久化 + 已有 validate_key + DCL 单例）。此前 api-key 分支既不可达，
`_api_keys` 又只是进程内字典（重启即全体失效）。阶段一留下的那条
"X-API-Key 单独使用 → 401" 守卫，当时是对**未拍板能力**的现状描述；方向定了就按
新契约重写，而 JWT 面那几条 401 钉原样保留，用来证明这次没顺手放宽。

装配口径：不打 lifespan（本组只涉及鉴权与 api-keys），但用真 `create_app` 的路由与
真依赖，不做 dependency_overrides——否则测的就不是那道门。密钥存储把
`NEUROVA_DATA_DIR` 指到 tmp 并复位单例，用例之间不留租户脏数据。
"""

import pytest
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.api_key_manager import reset_api_key_manager
from neurova.api.app import create_app
from neurova.api.auth import create_access_token
from neurova.api.endpoints import agent_communication_api as comm

KEY_BASE = "/api/v1/agent-communication/api-keys"
TOKEN = create_access_token(
    {"sub": "ext-alice", "username": "ext-alice", "role": "user", "neuser_id": "ne-ext-alice"}
)


def _gate():
    """合一门的生产符号。本批开工前它不存在——用断言失败暴露，而不是 import error"""
    return getattr(auth_mod, "get_current_user_or_api_key", None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    reset_api_key_manager()
    yield TestClient(create_app())
    reset_api_key_manager()


def _bearer(scheme: str = "Bearer") -> dict:
    return {"Authorization": f"{scheme} {TOKEN}"}


def _mint(client, name: str, agent_id: str) -> dict:
    r = client.post(KEY_BASE, json={"name": name, "agent_id": agent_id}, headers=_bearer())
    assert r.status_code == 200, r.text
    return r.json()


class TestIdentityIsSingleSource:
    def test_casingDoesNotChangeTheTenant(self, client):
        """同一枚合法 token，`Bearer` 与 `bearer` 必须解析成同一个人"""
        assert client.post(KEY_BASE, json={"name": "k-upper"}, headers=_bearer("Bearer")).status_code == 200
        assert client.post(KEY_BASE, json={"name": "k-lower"}, headers=_bearer("bearer")).status_code == 200

        listed = client.get(KEY_BASE, headers=_bearer("Bearer")).json()["data"]["api_keys"]
        names = sorted(k["name"] for k in listed)
        assert names == ["k-lower", "k-upper"], f"小写 scheme 的密钥落到了别的租户：可见={names}"

    def test_noSecondHeaderParserInThisModule(self):
        """本域不得再有自己的 Bearer 解析：身份只能来自那道门"""
        assert not hasattr(comm, "_verify_api_key_or_token"), (
            "第二份身份解析仍在：它与路由级那道门会同求异解"
        )

    def test_everyRouteResolvesIdentityThroughTheSingleGate(self, client):
        gate = _gate()
        assert gate is not None, "合一门 `get_current_user_or_api_key` 尚不存在"

        offenders = []
        for route in comm.router.routes:
            calls = []
            stack = list(getattr(route, "dependant", None) and route.dependant.dependencies or [])
            while stack:
                dep = stack.pop()
                if getattr(dep, "call", None) is not None:
                    calls.append(dep.call)
                stack.extend(getattr(dep, "dependencies", []) or [])
            if gate not in calls:
                offenders.append(str(route.path))
        assert offenders == [], "以下端点未经那道合一门：" + ", ".join(offenders)


class TestApiKeyIsACredential:
    def test_apiKeyAloneAuthenticates(self, client):
        minted = _mint(client, "k-1", "ag-1")

        r = client.get(KEY_BASE, headers={"X-API-Key": minted["api_key"]})

        assert r.status_code == 200, f"合法密钥应能过门，实得 {r.status_code}: {r.text[:160]}"
        names = [k["name"] for k in r.json()["data"]["api_keys"]]
        assert names == ["k-1"], r.text

    def test_revokedKeyIsRejected(self, client):
        minted = _mint(client, "k-2", "ag-2")
        assert client.get(KEY_BASE, headers={"X-API-Key": minted["api_key"]}).status_code == 200

        revoke = client.post(f"{KEY_BASE}/{minted['key_id']}/revoke", headers=_bearer())
        assert revoke.status_code == 200, revoke.text

        r = client.get(KEY_BASE, headers={"X-API-Key": minted["api_key"]})
        assert r.status_code == 401, f"已撤销密钥竟仍被放行：{r.status_code} {r.text[:160]}"

    def test_keyOutlivesManagerReconstruction(self, client):
        """真相源是持久化那一份：单例重建（等价进程重启）后密钥仍能过门"""
        minted = _mint(client, "k-3", "ag-3")

        reset_api_key_manager()

        r = client.get(KEY_BASE, headers={"X-API-Key": minted["api_key"]})
        assert r.status_code == 200, f"密钥随进程内存表一起没了：{r.status_code} {r.text[:160]}"

    def test_inMemoryKeyStoreIsRetired(self, client):
        """本域不得再自持一份密钥表（三套并存 → 收成 APIKeyManager 一份）"""
        assert not hasattr(comm, "_api_keys"), "进程内密钥表仍在：与 APIKeyManager 双头存储"
        assert not hasattr(comm, "_hash_api_key"), "本域仍在自己算密钥哈希"


    def test_routingStatsCountKeysFromTheSameAuthority(self, client):
        """读侧与写侧必须同源：路由统计里的密钥数从真相源数出来。

        本批第一版迁移就漏了这一处——它仍按已退役的进程内表计数，端点直接 NameError。
        这条守卫钉的是"接通"的最后一段：换了存储面后，所有读取它的地方一起换。
        """
        _mint(client, "k-4", "ag-4")

        r = client.get("/api/v1/agent-communication/routing/stats", headers=_bearer())

        assert r.status_code == 200, r.text
        assert r.json()["data"]["api_keys"] == 1, r.text


class TestAuthSurfaceIsNotWeakened:
    """合一之后，JWT 面不得被顺手放宽"""

    def test_missing_credentials_still_401(self, client):
        assert client.post(KEY_BASE, json={"name": "k"}).status_code == 401

    def test_invalid_token_still_401(self, client):
        assert client.post(
            KEY_BASE, json={"name": "k"}, headers={"Authorization": "Bearer not-a-jwt"}
        ).status_code == 401

    def test_unknownApiKey_still_401(self, client):
        assert client.post(
            KEY_BASE, json={"name": "k"}, headers={"X-API-Key": "never_minted"}
        ).status_code == 401
