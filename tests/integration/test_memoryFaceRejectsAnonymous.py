"""记忆面不再接受无凭证请求（点单「甲＋丙」的第一半：把匿名这一半从代码根上关掉）

起点是 §6-426 复算量出的那条面，实测读数：

    无 Authorization  GET /api/v1/memory?agent_id=default      → 200，24 行正文
    无 Authorization  GET /api/v1/memory/hot?agent_id=default  → 200，24 行正文（19KB）
    无 Authorization  GET /api/v1/memory/markdown?...          → 200，12285 字
    而 `start_server.py:70` 默认 `NEUROVA_HOST=0.0.0.0`，从本机局域网地址
    `http://192.168.1.5:9527/...` 直接 200 ⇒ 同网段任一设备一次 GET 就能读走全部转写。

两个条件叠加才成立：**列表腿传 `agent_wide=True`（不比 neuser/user）** ×
**身份依赖用的是可回退那份 `get_current_user_or_default`（无凭证回落 default）**。
回落身份在这条路上等于没有身份——政策说的"匿名读只见 default 桶"（auth.py
`get_current_user_or_default` docstring，2026-10-08 记的那格边界）在实现上根本没被执行。

落点选在**路由级那道门**而不是逐条 handler：现算记忆 router 的 GET 路由 31 条，其中
29 条处理器里出现 `get_memory_manager(`（＝会取租户数据）。逐条改 29 个依赖名是一份
巨大又容易漏的改动，而且下一条新路由忘了改就静默复现本缺陷；门只有一处，覆盖面是
"这个门面"而不是"我记得改过的那几条"（教义第 1 条：修在生产该状态的上游）。

因此本文件钉四件事：
1. 无凭证打记忆面的**任何**取租户数据的读端点 → 401（不再是"这一条堵了那一条敞着"）；
2. 带真凭证的调用方读数**一字不变**（可见性对登录用户保持 agent 级共享，这不是本批改的东西）；
3. 只回静态枚举的端点（`/emotion/types`）不强行要身份——政策的边界是"租户数据要凭证"，
   不是"全站要登录"，把装饰参数硬套上去是另一件事；
4. 路由级那道门不再是"只管写"：名字与 docstring 必须与它现在做的事一致（留着
   `...ForWrites` 这个名字就是让下一个读侧缺口藏在名字里）。

装配与同目录三档判据一致：真 router + 真鉴权依赖 + 真 `MemoryManager`，只把
`get_app_state` 换成供出该 manager 的桩；身份用生产 `create_access_token()` 签的真 JWT。
"""

import inspect
import types
import typing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests.auth_headers import bearerHeaders

ALICE_HDR = bearerHeaders("alice")
PLAIN_HDR = bearerHeaders("bob")


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


@pytest.fixture
def client(manager, monkeypatch):
    agent = types.SimpleNamespace(memory_manager=manager)
    state = types.SimpleNamespace(agents={"agent_a": agent}, get_agent=lambda *a, **k: agent)
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: state)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    return TestClient(app)


def _createAsAlice(client) -> str:
    r = client.post("/api/v1/memory", json={"content": "ALICE-私密行", "auto_classify": False},
                    headers=ALICE_HDR)
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _tenantDataGetPaths() -> typing.List[str]:
    """现算：记忆 router 里"处理器会向 manager 取数据"的 GET 路径（不抄名单）。"""
    paths = []
    for route in memoryRouter.routes:
        if "GET" not in (getattr(route, "methods", None) or ()):
            continue
        if "get_memory_manager(" in inspect.getsource(route.endpoint):
            paths.append(route.path)
    return paths


class TestMemoryFaceRejectsAnonymous:
    def test_anonymousCannotListAnyMore(self, client):
        _createAsAlice(client)

        r = client.get("/api/v1/memory", params={"limit": 50, "agent_id": "agent_a"})

        assert r.status_code == 401, f"匿名读列表应 401，实得 {r.status_code}: {r.text[:160]}"
        assert "ALICE-私密行" not in r.text

    def test_theWholeTenantDataGetSurfaceIsGated(self, client):
        """逐条走一遍现算出来的取租户数据 GET 面：任一条回 200 就是"这一条堵了、那条还敞着"。"""
        memoryId = _createAsAlice(client)
        targets = []
        for path in _tenantDataGetPaths():
            url = (
                "/api/v1/memory"
                + path.replace("{memory_id}", memoryId)
                .replace("{emotion_type}", "joy")
                .replace("{user_id}", "alice")
                .replace("{entity}", "e").replace("{relation}", "r")
                .replace("{pending_id}", "p1").replace("{agent_id}", "agent_a")
            )
            targets.append((path, url))

        leaks = []
        for path, url in targets:
            r = client.get(url, params={"agent_id": "agent_a"})
            if r.status_code < 400:
                leaks.append(f"{path} → {r.status_code}")

        assert leaks == [], "以下取租户数据的记忆读端点对匿名敞开：\n" + "\n".join(leaks)

    def test_anonymousCannotExportBodyEither(self, client):
        """/markdown 与列表不是同一条腿：它曾实测匿名 200 出 12285 字本机正文。"""
        _createAsAlice(client)

        r = client.get("/api/v1/memory/markdown", params={"agent_id": "agent_a"})

        assert r.status_code == 401, f"匿名导出应 401，实得 {r.status_code}"


class TestDefaultBindIsLoopback:
    """点单丙：暴露面必须是"被写下过的决定"，不能是默认值。

    这三格钉的是配置形状，不是网络行为——真服务上的局域网不可达已在活体里量过
    （`ConnectionRefusedError`）。不钉住默认值的后果是下一次重构静默长回 `0.0.0.0`，
    而那条改动看起来"只是整理启动参数"。
    """

    REPO = Path(__file__).resolve().parents[2]

    def test_startServerDefaultsToLoopback(self):
        src = (self.REPO / "start_server.py").read_text(encoding="utf-8")

        assert 'os.environ.get("NEUROVA_HOST", "127.0.0.1")' in src, (
            "start_server.py 的默认绑定不再是回环——局域网面会随默认值回来"
        )

    def test_appLaunchPointsAgree(self):
        """`create_app` / `run_server` / `--host` 三处默认必须同口径，否则换启动点就换暴露面。"""
        import re

        src = (self.REPO / "neurova" / "api" / "app.py").read_text(encoding="utf-8")
        hosts = re.findall(r'host:?\s*(?:"|=\s{0,2}")([0-9.]+)"', src) + re.findall(
            r'--host",\s*default="([0-9.]+)"', src
        )

        assert hosts, "没现算到 app.py 里的绑定默认值——判据退化成恒真"
        offenders = [h for h in hosts if h != "127.0.0.1"]
        assert offenders == [], f"仍有启动点默认监听 {offenders}"

    def test_composePinsHostSideButKeepsContainerOpen(self):
        """宿主发布地址收成回环，容器内**必须**仍是 0.0.0.0——否则 docker 的端口代理进不去。

        这一格是反向钉：把两处一起改成 127.0.0.1 看着"更严"，实际是把容器内服务关成
        只有容器自己能连，宿主 `127.0.0.1:9527` 反而全断。两件事必须由不同键表达。
        """
        src = (self.REPO / "docker-compose.yml").read_text(encoding="utf-8")

        assert '"127.0.0.1:9527:9527"' in src, "宿主侧发布地址没收成回环，局域网面仍在"
        assert "NEUROVA_HOST=0.0.0.0" in src, (
            "容器内绑定被一起改窄了：docker 端口代理会连不上容器，健康检查与宿主映射同时失效"
        )

    """政策的另一半不动：登录用户的可见性仍是 agent 级共享，读数一字不变。"""

class TestCredentialledReadersAreUntouched:
    """政策的另一半不动：登录用户的可见性仍是 agent 级共享，读数一字不变。"""

    def test_owner_and_other_logged_in_users_still_read_lists(self, client):
        memoryId = _createAsAlice(client)

        alice = client.get("/api/v1/memory", params={"limit": 50}, headers=ALICE_HDR)
        bob = client.get("/api/v1/memory", params={"limit": 50}, headers=PLAIN_HDR)

        assert alice.status_code == 200, alice.text
        assert bob.status_code == 200, bob.text
        assert any(r["id"] == memoryId for r in bob.json()["data"]["memories"]), (
            "bob 仍应按 agent 口径看见该行（可见性是本批没动的那一半）"
        )

    def test_staticEnumerationRouteFollowsTheFaceDeliberately(self, client):
        """`/emotion/types` 只回静态枚举，但**不给它开豁免口**。

        门挂在 router 装配处，覆盖面是"这个门面"；为一条静态端点单开例外，就等于
        引入第二条规则——下一条"看着无害所以豁免"的路是这么长出来的。这条端点跟着
        要凭证没有代价可谈：前端拿它做的是标签映射，登录之后才用得到。
        本格钉的是"这个决定是刻意的"，不是"它应该 200"。
        """
        r = client.get("/api/v1/memory/emotion/types")

        assert r.status_code == 401, (
            f"门面收紧应当无例外；这条腿被单独放过了，说明豁免口又开了一道：{r.status_code}"
        )


class TestTheGateIsNamedForWhatItDoes:
    def test_routerLevelGateIsNotWriteOnlyAnymore(self):
        """门挂在 router 装配处；它的名字与 docstring 不能再宣称"只管写"。"""
        from neurova.api.endpoints.memory import base

        src = inspect.getsource(base)
        gateName = None
        for line in src.splitlines():
            if "dependencies=[Depends(" in line and "router = APIRouter" in line:
                gateName = line.split("Depends(")[1].split(")")[0]
                break

        assert gateName is not None, "找不到挂在 router 装配处的那道身份门"
        assert "ForWrites" not in gateName, (
            f"门现在管的是整个门面的读写，名字仍叫 {gateName}——"
            "下一个读侧缺口会藏在'这只拦写'的名字里"
        )
        target = getattr(auth_mod, gateName, None)
        assert target is not None, f"门 {gateName} 不在 auth 模块里（身份入口分家了）"
        doc = inspect.getdoc(target) or ""
        assert "读" in doc, f"{gateName} 的 docstring 没说明它对读类请求做什么"

    def test_identityEntriesStillResolveThroughRegisteredSinglePoints(self):
        """身份入口仍只有 auth/deps 那几份：本批新增的门不许成为第二条装 user_id 的通道。"""
        from tests.auth_headers import _identityEntryPoints

        names = {getattr(fn, "__name__", "") for fn in _identityEntryPoints()}
        assert "user_id" not in names, names
        # 新门必须复用同一份凭证→身份解析，不自解一遍
        from neurova.api import auth as _auth

        assert hasattr(_auth, "_identityFromCredentialsOr401"), (
            "凭证→身份的解析单点不在了：门若在别处再解一遍 token 就是第二条通道"
        )
