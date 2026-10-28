"""身份取数口必须「先对齐本轮密钥，再签一枚」——把 `pinJwtSecret` 自己 docstring 里的规矩做成会红的闸

规矩早就写在 `tests/auth_headers.pinJwtSecret()` 的正文里：
> 幂等……但**不要在导入期烘一枚令牌** —— 令牌属于"这一轮"，不属于"这个进程"。

问题是它只是**注释**。同一模块里两份取数口的存在方式把这条规矩变成自觉：

| 取数口 | 行为 | 现算消费者 |
|---|---|---|
| `signedBearerHeaders()` | 先 `pinJwtSecret()` 对齐、再签 | 3 档 / 13 处 |
| `bearerHeaders()` | **只签，不对齐** | 18 档 / 34 处 |

⇒ 任何在 import 期用后者签头的档，都会在别人对齐之后变成「刚签的令牌被自己拒」。
现算读数（工单 `docs/04-plans/记忆面测试密钥作用域工单_2026-10-27.md`）：6 档 11 处在模块级签头，
与 `tests/test_api` 合跑红 **26 条**——本批把它们清零。

⚠ 一条判读纪律（我在这批开头就栽过一次）：**401 有两种子形态，别当成一件事**。
`{"detail":"Invalid or expired token"}` ＝ 带了令牌但验不过（本族）；
`{"detail":"Not authenticated"}` ＝ **压根没带凭证**（§6-429 那道路由级门的形态）。
`tests/integration/test_memory_emotion_min_score.py` 单跑那 2 条是后者——它的 `_idsAt()`
调 `client.get(...)` 没传 `headers`，属 §6-429 收紧时的漏扫命中点，**不在本批闭合面内**，
已登记台账仍开。把两种 401 划成一族，就会既误报闭合、又掩盖真正漏掉的那条腿。

本文件钉两件事：
1. 行为——即便某档在签完之后才对齐（这就是合跑时的真实时序），那枚头仍必须过得了生产身份门；
2. 形状——`bearerHeaders()` 体内必须真的调用对齐口，且第二份取数口不许再以独立实现存在
   （教义第 6/7 条：同一功能两处并存 ⇒ 比后合、其余退役）。

处置选甲（工单里三案的影响面见该档正文）：把对齐塞进签名口本身。没有复原路可用——
泄漏守卫 `test_jwtSigningKeyLeakIsGuarded.py:48` 让人去调的
`adoptJwtSecretForTests` / `resetJwtSecretToProduction` **全仓 0 处实装**，
所以"改完复原"这条路本身是幽灵，唯一站得住的就是"签之前必然对齐"。

时序全部用既有 API 造（`pinJwtSecret(sentinel)` → 签 → `pinJwtSecret()`），
不做 `JWT_SECRET_KEY` 裸赋值——那正是上面那枚守卫抓的形态。
"""

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.auth import get_current_user
from tests.ast_scan import parseSource
from tests.auth_headers import bearerHeaders, pinJwtSecret

AUTH_HEADERS_SOURCE = Path("tests/auth_headers.py")
SENTINEL_SECRET = "sentinel_secret_a_previous_round_used_this_one_0123456789"


@pytest.fixture
def probeClient():
    """只挂生产身份门的最小 app——不 override 依赖（§6-427 的教训）。"""
    app = FastAPI()

    @app.get("/probe")
    def _probe(user: dict = Depends(get_current_user)):
        return {"user_id": user.get("user_id")}

    return TestClient(app)


# ============================================================
# 行为：签完之后才对齐，那枚头仍要能用（今天红）
# ============================================================


def test_headerSignedBeforeAlignmentStillPassesTheProductionGate(probeClient):
    pinJwtSecret(SENTINEL_SECRET)          # 模拟"上一个时点用的是别的密钥"
    headers = bearerHeaders("align-then-verify")   # 在未对齐到本轮的状态下签
    pinJwtSecret()                          # 本轮对齐发生（这正是别的档的作为）

    response = probeClient.get("/probe", headers=headers)

    assert response.status_code == 200, (
        f"签出的令牌被自己拒：{response.status_code} {response.text[:120]} —— "
        "签名侧烘的是旧密钥，验签门已被对齐到本轮值"
    )
    assert response.json()["user_id"] == "align-then-verify"


def test_freshlySignedHeaderStillWorksWithoutAnyFurtherPin(probeClient):
    """反向格（今天就该绿）：不许把"对齐"做成"每次签都换一把"——签完不再 pin 也必须验得过。"""
    headers = bearerHeaders("no-extra-pin")

    response = probeClient.get("/probe", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == "no-extra-pin"
    # 幂等：取用一次不该把本轮密钥换掉（否则每签一头就换一把，验签门永远追不上）
    assert auth_mod.currentJwtSecretKey() == pinJwtSecret()


# ============================================================
# 形状：取数口只剩一份，且它必然先对齐
# ============================================================


def test_bearerHeadersAlignsBeforeSigning():
    source = inspect.getsource(bearerHeaders)

    assert "pinJwtSecret(" in source, (
        "`bearerHeaders()` 又回到只签不对齐了——它就是那 28 条红的入口"
    )


def test_identityHeaderFactoryExistsExactlyOnce():
    """两份取数口不许并存为两个名字：对齐塞进签名口之后，第二个名字就是第二个事实源。"""
    tree = parseSource(AUTH_HEADERS_SOURCE.read_text(encoding="utf-8"))
    factoryNames = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "Headers" in node.name
    ]
    signingBodies = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and "Headers" in node.name
        and "create_access_token" in ast.dump(node)
    ]

    assert factoryNames == ["bearerHeaders"], (
        f"身份头取数口有 {len(factoryNames)} 个名字：{factoryNames}"
        "（教义第 6/7 条：同一功能两处并存 ⇒ 比后合、其余退役）"
    )
    # 正检：那唯一一份确实自己签——否则"只剩一个名字"可能只是大家都没签了
    assert signingBodies == ["bearerHeaders"], (
        f"唯一取数口应当自己签，实得 {signingBodies}"
    )
