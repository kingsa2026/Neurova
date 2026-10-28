"""记忆读面的失败形态：未就绪要显式 5xx 并点名原因，不许把故障画成 200 空列表（§6-220 登记项）。

两条病，同一根因（"没人对失败表态"）：
- `memory/base.py:180 get_memory_manager` 在无应用状态 / 无默认 Agent 时抛
  `APIError(AGENT_NOT_INITIALIZED=6001)`，而 `error_handlers.py` 那张码表**没有 6001**
  ⇒ `_CODE_TO_HTTP_STATUS.get(exc.code, 500)` 把它落成 500。500 的含义是"我方代码错了"，
  真意却是"服务还没就绪"——调用方据此重试/报警的方向完全错。
- 更糟的是 `crud.py` 的 search：它捕住 6001 后**返回 200 空列表**。这是教义第 2 条明文禁止的
  "把失败改写成成功形态"——实测那一份信封长这样：
  `{"code":0,"message":"记忆系统未初始化，请先创建 Agent","data":{"count":0,"memories":[]}}`。
  界面上一片空白、日志里零故障、指标不涨，看的人以为"就是没有记忆"。

码表旧注释自己写着"未列出的错误码保持 500（与历史行为一致）"——这句就是病灶：**默认落 500
等于没人表态**。所以根修不是补一行 6001，而是让"每个已声明的错误码都必须表过态"变成会红的判据
（本档第一格），下次新增码时它自己会拦住"忘了映射"这件事；兜底那一路保留但出声。

取数走真 `create_app()`＋`TestClient`——**不进 with 上下文**就是"启动尚未完成"的真实形状，
那正是 6001 在生产里被抛出的那个态；不去 monkeypatch 私有 `_state`（那是绕过生产装配点）。
反向钉不在本档重复：已就绪时这两个端点仍 200、写侧匿名仍 401，由
`tests/unit/api/test_memoryWriteIdentityGate.py` 钉着——本档只改"失败长什么样"，
不许顺手把读面改成不要登录（2026-10-26 点单甲之后读面本就要登录，夹具按现行政策带证）。
"""
from __future__ import annotations

import pytest

from neurova.interfaces.api_standard import ErrorCodes

MEMORY_PREFIX = "/api/v1/memory"


@pytest.fixture()
def unreadyClient(monkeypatch):
    """真 app、但不跑 lifespan ⇒ 没有默认 Agent，正是 6001 的产生态。

    两件前提都不是被测对象，缺任一件红都不在这里：

    ① **清掉上一场留下的 `_app_state`**：进程里**上一个**起了 lifespan 的 app 会把它留在
       模块全局上（`create_app()` 本身不写、`lifespan` 才写）。同场跑测时它还在，本档拿到
       的就不是"未就绪"，三条行为钉会读成 200 空成功——红在夹具没断干净，不是产品把故障
       画成了成功。
    ② **带一枚真 JWT**：记忆面自 2026-10-26 点单甲起整面挂路由级
       `requireIdentityForMemoryFace`，匿名请求在到达"未就绪"那一段之前就 401 了。凭证走
       生产同一个签发口（`tests/auth_headers.bearerHeaders`），不在生产侧加兜底——
       `dependency_overrides` 压不住路由级那道门。
    """
    from fastapi.testclient import TestClient

    from neurova.api import app as app_module
    from tests.auth_headers import bearerHeaders

    monkeypatch.setattr(app_module, "_app_state", None, raising=False)
    return TestClient(app_module.create_app(), headers=bearerHeaders("u-probe"))


def testEveryDeclaredErrorCodeTakesAPosition():
    """主格：声明过的错误码，要么进映射表，要么进"按设计就是 5xx"那份显式清单。

    两份清单都从生产模块引，不在测试里另抄——那等于造第二个事实源。
    """
    from neurova.api import error_handlers

    mapped = {int(k) for k in error_handlers._CODE_TO_HTTP_STATUS}
    declared = {int(c) for c in error_handlers._SERVER_FAULT_CODES}
    silent = [int(c) for c in ErrorCodes
              if int(c) != int(ErrorCodes.SUCCESS)
              and int(c) not in mapped and int(c) not in declared]
    assert not silent, (
        "这些错误码没人声明它的 HTTP 形态，会被兜底默默落成 500：%s"
        "（要么进映射表，要么进服务器故障清单——默认值不是表态）" % silent
    )


def testNotReadyIsFiveThreeWhileOperationFailureStaysFiveHundred():
    """503 只给"未就绪"，真故障仍 500——把 7001 一起映射成 503 是本批自己踩出来的错。

    为什么钉这一头：`MEMORY_OPERATION_FAILED=7001` 在本仓两用（"记忆系统未启用"与
    "添加/获取记忆失败: <异常>"）。整体映射成 503 会把真故障报成"稍后再试"，调用方据此
    静默重试——三格 `test_internalFaultIsNotReportedAsVerdict` 当场抓住（它们断言内部故障
    必须是 500 而不是被降级成 4xx/200 结论）。未就绪那一用改抛 6003（见 `memory/base.py`）。
    """
    from neurova.api import error_handlers

    for code in (ErrorCodes.AGENT_NOT_INITIALIZED, ErrorCodes.AGENT_NOT_READY):
        assert error_handlers._CODE_TO_HTTP_STATUS.get(int(code)) == 503, (
            f"{int(code)} 是未就绪态，应为 503"
        )
    assert int(ErrorCodes.MEMORY_OPERATION_FAILED) in {
        int(c) for c in error_handlers._SERVER_FAULT_CODES}, (
        "7001 被挪去 503 了 ⇒ 真故障会报成「稍后再试」"
    )


def testStatsEndpointAnswersFiftyThreeWithReason(unreadyClient):
    """行为钉①：`GET /api/v1/memory/stats` 在未就绪时 503，且信封里点名是哪一段没就绪。

    修前实得 500。只有状态码没有原因不算闭环——调用方要能判断"该等"还是"该报警"。
    """
    resp = unreadyClient.get(f"{MEMORY_PREFIX}/stats")
    assert resp.status_code == 503, f"实得 {resp.status_code}：{resp.text[:160]}"
    body = resp.json()
    assert int(body.get("code", 0)) == int(ErrorCodes.AGENT_NOT_INITIALIZED), (
        "503 却没带回业务码（实得 %s）" % body
    )
    assert body.get("message"), "503 却没说哪一段没就绪"


def testSearchEndpointRefusesToPaintFailureAsEmptySuccess(unreadyClient):
    """行为钉②：`GET /api/v1/memory?query=…` 不许再回 200 空列表。

    这一格是本批的真靶子：200 空信封会让"服务没就绪"在界面、日志、指标三处同时消失。
    """
    resp = unreadyClient.get(f"{MEMORY_PREFIX}?query=%E4%BD%A0&limit=5")
    assert resp.status_code == 503, (
        "实得 %s，body=%s ⇒ 故障被画成空成功（教义第 2 条禁止）"
        % (resp.status_code, resp.text[:160])
    )
