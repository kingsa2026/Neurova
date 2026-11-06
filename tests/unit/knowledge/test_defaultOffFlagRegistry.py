# -*- coding: utf-8 -*-
"""D 组默认关开关的单源与读数面（升级计划 §13.1 D 组行 / §13.2 并入点 / §15.1「观测与开关」）。

票面欠账的实状：九项开关散在九个文件里各读各的 env，**仓内没有任何一处能一次答出
"这九项现在分别是什么态"**——前端因此只能摆一张静态表（`NeurUI/src/config/ontologyStatic.ts`），
并且那张表只有八行：D-03 缺席，而它的守卫断言写成 `rows.length == DEFAULT_OFF_ROWS.length`，
漏一行照样绿。这一族判据钉的就是：

1. 九项在册且 ids 就是票面那九项（缺 D-03 即红）；
2. 注册表**不许自己读 env**——每项的现值必须由它所在模块的那个既有谓词给出
   （第二个读取点就是第二个事实源，教义第 6 条）；
3. 默认态逐项目测＝票面声明的默认值；设 env 后能翻（证明读的是活值而不是抄来的字符串）；
4. 读数面对治理门的要求：未登录 401 / 非管理员 403 / 管理员 200，返回九行；
5. 面只报开关态与落点模块，不报 env 的实际值内容（凭据类变量与本面无关，但不给顺手探测的机会）。

红形态说明：`defaultOffFlags` 与 `knowledge_observability` 都是本次新增面，
第一轮的红是 ModuleNotFoundError/404（新增能力不存在的诚实红），不是既有行为退化；
第 2、3 格的红会落在断言上（谓词缺席或读的是抄来的串）。
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_MODULE = "neurova/knowledge/defaultOffFlags.py"

#: §13.1 D 组行点名的九项（少一项、多一项都要在这里同步改，且必须说明理由）。
TICKET_FLAG_IDS = ("D-01", "D-02", "D-03", "D-04", "D-06", "D-08", "D-11", "D-16", "D-19")


def _registry():
    from neurova.knowledge import defaultOffFlags

    return defaultOffFlags


def test_registryCoversExactlyTheNineTicketFlags():
    """① 九项在册——D-03 曾被前端静态表漏掉，这一格不让它再漏一次。"""
    registry = _registry()
    ids = tuple(row.flagId for row in registry.DEFAULT_OFF_FLAGS)
    assert ids == TICKET_FLAG_IDS, f"在册项与票面九项不一致：{ids}"


def testRegistryNeverReadsEnvironmentItself():
    """② 单点性：注册表只列名与归属，现值一律委托给本模块既有谓词。

    取 AST 而不是 grep——`"# os.environ.get"` 这种注释逃得过文本匹配，逃得过 grep，
    但表达式节点会留在树上；同样地，把 env 名作为字符串写进表里是允许的（那是登记），
    不允许的是在注册表里再解一次。
    """
    path = REPO_ROOT / REGISTRY_MODULE
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "get":
            head = node.value
            while isinstance(head, ast.Attribute):
                head = head.value
            rendered = ast.unparse(node)
            if "environ" in rendered or "getenv" in rendered:
                offenders.append(f"{node.lineno}: {rendered[:80]}")
    assert not offenders, f"注册表里出现了第二个 env 读取点（应为委托调用）：{offenders}"


def testEveryRowDelegatesToARealCallableInItsHomeModule():
    """②b 每一行的 readout 必须是归属模块里真存在的函数/方法，不是字符串承诺。"""
    registry = _registry()
    for row in registry.DEFAULT_OFF_FLAGS:
        assert callable(row.readout), f"{row.flagId} 的 readout 不可调用"
        module = inspect.getmodule(row.readout)
        assert module is not None, f"{row.flagId} 的 readout 没有宿主模块"
        assert row.homeModule.split(".py")[0].replace("/", ".").endswith(
            module.__name__.split(".")[-1]
        ), f"{row.flagId} 声明归属 {row.homeModule}，实际读数来自 {module.__name__}"


@pytest.mark.parametrize(
    "flagId,defaultToken",
    [("D-01", "off"), ("D-02", "off"), ("D-03", "off"), ("D-04", "off"),
     ("D-06", "off"), ("D-08", "off"), ("D-11", "off"), ("D-16", "off"), ("D-19", "legacy")],
)
def testFreshProcessDefaultStateMatchesTheTicket(monkeypatch, flagId, defaultToken):
    """③ 默认态逐项目测＝票面声明值（清掉 env 现取，不抄字符串）。"""
    registry = _registry()
    row = next((r for r in registry.DEFAULT_OFF_FLAGS if r.flagId == flagId), None)
    assert row is not None
    for name in (row.envKey, row.envKey.lower()):
        monkeypatch.delenv(name, raising=False)
    assert row.readout() == defaultToken, (
        f"{flagId}（{row.envKey}）默认态实测 {row.readout()!r}，票面声明 {defaultToken!r}"
    )


def testFlippingOneFlagDoesNotFlipItsNeighbours(monkeypatch):
    """③b 逐项独立：翻 D-06 不许顺手把 D-01/D-04 一起带上（§6「不打包全开」的反证）。

    这一格是"打包全开"那条决定的行为反证：如果将来有人写一个总开关，它在这里红。
    """
    registry = _registry()
    before = {row.flagId: row.readout() for row in registry.DEFAULT_OFF_FLAGS}
    monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "on")
    after = {row.flagId: row.readout() for row in registry.DEFAULT_OFF_FLAGS}

    assert after["D-06"] != before["D-06"], "D-06 设 on 后读数没变——读的不是活值"
    moved = sorted(k for k in after if after[k] != before[k])
    assert moved == ["D-06"], f"翻一项动了多项：{moved}"


def _appAsAdmin():
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    return TestClient(app), app


def _authHeadersAs(role: str):
    from neurova.api.auth import create_access_token

    token = create_access_token({"sub": "u-obs", "username": f"{role}er",
                                 "neuser_id": "u-obs", "user_id": "u-obs", "role": role})
    return {"Authorization": f"Bearer {token}"}


def testDefaultOffEndpointServesNineRowsForAdminOnly():
    """④ 读数面：未登录 401、非管理员 403、管理员 200 且九行齐。"""
    client, _app = _appAsAdmin()
    path = "/api/v1/knowledge/observability/default-off"

    assert client.get(path).status_code == 401, "匿名可读＝服务器开关态对外敞开"
    assert client.get(path, headers=_authHeadersAs("user")).status_code == 403, (
        "普通用户可读＝§15.3 承诺的『不在普通用户面暴露』不成立")

    res = client.get(path, headers=_authHeadersAs("admin"))
    assert res.status_code == 200, res.text
    rows = res.json()["data"]["items"]
    assert [r["flagId"] for r in rows] == list(TICKET_FLAG_IDS)


def testDefaultOffEndpointCarriesNoEnvValues():
    """⑤ 面只报开关态与归属：键名可给（那是登记信息），值内容一律不给。

    反证目标：把某项的 env 现值整串吐出来，等于给读到的任何敏感串开一条通道。
    """
    client, _app = _appAsAdmin()
    body = client.get("/api/v1/knowledge/observability/default-off",
                      headers=_authHeadersAs("admin")).text
    assert "NEUROVA_" in body, "键名都没报，这面就只是把前端静态表搬到服务端"
    assert not re.search(r'"(value|rawValue|envValue)"\s*:', body), f"读数面开始回传 env 值：{body[:200]}"
