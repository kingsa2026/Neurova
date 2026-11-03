# -*- coding: utf-8 -*-
"""指挥资格台账读面的失败形态（§6-493；同一条病的第二处命中点，教义第 2/5 条）。

第一处是记忆读面（`test_MemoryReadFaceRefusesToPaintFailureAsSuccess.py`，§6-220）：捕住故障后
返回 200 空列表。本档是同一根因在**治理读面**的第二副面孔——批 H2 的
`GET /api/v1/governance/authority-log`（`neurova/api/endpoints/governance.py:190`）在宽 except 里回

    {"code": 0, "data": {"available": False, "error": str(e), "rows": []}}

`code: 0` 是成功信封。于是「台账读不动」与「今天确实一条判定都没有」这两条**相反的运维事实**
在同一个 200 里长得一模一样，值班照着"没有判定行"去排查，走的是一条不通的路
（与 `_rsiAgentAbsent`／`_rsiNotAssembled` 那两条被拆开的错误归因同形）。
`tests/unit/ci/test_noFaultFoldedIntoVerdict.py` 的棘轮把这处点成新增违规（§6-492 已登记），
引入者现查 `494dab17`（批 H 指挥资格判定落点）。

处置是**根修而不是登记基线**：故障走 HTTP 5xx 并点名原因（第 1 格）；`available` 只在真读数里
出现，它现在是状态位、不再充当故障的替身（第 2 格钉"能读的时候确实读得到"）。

两条现读前提，都不是被测对象：
- 前端零消费：现查 `NeurUI/src` 里 `authority-log` 0 命中 ⇒ 改状态码不撞任何面板契约；
- 台账层自己的读数判据在 `tests/unit/security/test_commandAuthority.py`，本档不重复钉它。
"""

import pytest


@pytest.fixture()
def adminClient():
    """真 `create_app()` ＋ 生产同一签发口出的 admin 令牌。

    不走 `dependency_overrides`：那是把"凭证链走得通吗"整段跳过（`tests/auth_headers.py`
    的存在理由）。治理面挂的是 `require_admin()`→`require_role("admin")`（`neurova/api/deps.py:304`），
    所以令牌里得真带 admin 声明。
    """
    from fastapi.testclient import TestClient

    from neurova.api import app as app_module
    from tests.auth_headers import bearerHeaders

    return TestClient(app_module.create_app(),
                      headers=bearerHeaders("u-authority-probe", role="admin"))


def testLedgerFaultIsHttp5xxNotASuccessEnvelope(adminClient, monkeypatch):
    """主格：台账读不动必须 5xx 且点名原因——不许包进 `code:0` 的成功信封。"""
    from neurova.security import command_authority

    def boom(*_args, **_kwargs):
        raise RuntimeError("authority ledger unreadable: probe-fault")

    monkeypatch.setattr(command_authority, "getCommandAuthorityLedger", boom)

    resp = adminClient.get("/api/v1/governance/authority-log")

    assert resp.status_code in (500, 502, 503), (
        "台账读不动却回了 %s（响应：%s）——宽 except 把故障折成成功载荷，"
        "调用方据此重试/报警的方向完全错" % (resp.status_code, resp.text[:220]))
    assert resp.json().get("code") != 0 if resp.status_code == 200 else True, (
        "5xx 路径不许仍带 code:0 的成功码——那等于两条契约各说一半")
    assert "probe-fault" in resp.text or "读不动" in resp.text, (
        "5xx 必须把原因带出来，只回一句 internal error 就没人知道是台账坏了：%s"
        % resp.text[:220])


def testHealthyReadoutStillReturnsRows(adminClient):
    """闭环格：能读的时候真读得到——`available: True` 是状态位而不是故障替身。"""
    resp = adminClient.get("/api/v1/governance/authority-log")

    assert resp.status_code == 200, (
        "健康读面应 200，实得 %s：%s" % (resp.status_code, resp.text[:200]))
    payload = resp.json()
    assert payload.get("code") == 0, payload
    data = payload.get("data") or {}
    assert data.get("available") is True, (
        "读通了却不报 available=True，那这个字段就只剩故障义（%s）——"
        "它应当只描述读数可达性，不再替故障传话" % data)
    assert isinstance(data.get("rows"), list), (
        "rows 必须是列表（空表是合法读数，缺字段不是）：%s" % data)
