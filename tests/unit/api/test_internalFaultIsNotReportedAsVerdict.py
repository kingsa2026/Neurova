# -*- coding: utf-8 -*-
"""内部故障不许被折成"查无此类/没有数据"的结论（台账 §6-126，用户 2026-10-10 裁定改 4 处）。

缺陷形态三处同族：宽 `except Exception` 之后
① `memory/crud.py:260` 抛 `MEMORY_NOT_FOUND` ⇒ 404 壳里装 500 的话（DB 锁被读成"这条记忆不存在"）；
② `firewall.py:471-476` 回 `code:0 + 全 0` ⇒ 故障被读成"防火墙没规则"（安全面）；
③ `memory/metacognition.py:428/456` 回 `success_response(空)` ⇒ 读面出错画成空列表/全 0 统计。
**方向搞反的读数比没有读数更坏**：排查时"空"是最可信的信号，异常被它吸收掉就再也不露头。

每处都配一格**反向对照**（真·无数据仍须 200/404），否则修法只是"把一切变 500"——
那同样是把两件事折成一件事，只是折朝另一边。

**第五处随教义第 5 条扫荡补上**（`auth.py::logout`，原判据基线里标"存疑"的那一格）：
它不是"把故障读成不存在"，而是"把撤销失败读成登出成功"——同一根因的**成功侧**形态，
且内层已有一记正确的 500 被外层 catch-all 吞掉。见
`TestLogoutDoesNotInvalidateNothingSilently`。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.error_handlers import register_error_handlers
from neurova.interfaces.api_standard import ErrorCodes
from tests.auth_headers import bearerHeaders

USER = {"user_id": "1", "username": "tester", "role": "user"}


def _mount(router, prefix: str):
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    register_error_handlers(app)
    app.dependency_overrides[get_current_user_or_default] = lambda: dict(USER)
    # 装配噪声先排掉：firewall 的路由级依赖是 `get_current_user`，
    # 不覆盖就整族 401——红会咬在"没鉴权"上而不是"把故障读成结论"上。
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    # 记忆面另有一道**路由级**凭证门（`APIRouter(dependencies=[Depends(requireIdentityForMemoryFace)])`，
    # 2026-10-26 点单甲把读写一起收进来）。它判的是"请求有没有凭证"，不看被 override 的
    # 处理器级身份函数，所以替身压不住它——必须像用户那样带一枚真 JWT，否则整族 401 的
    # 读数会被读成"故障被折成结论"。这是新增的装配前置条件，不是被测行为的变化。
    return TestClient(app, raise_server_exceptions=False, headers=bearerHeaders(USER["user_id"]))


class _BoomLedger:
    def list_records(self, **_kw):
        raise RuntimeError("元认知台账被锁住")

    def record_stats(self, _agent_id):
        raise RuntimeError("元认知台账被锁住")


class _EmptyLedger:
    def list_records(self, **_kw):
        return {"items": [], "total": 0}

    def record_stats(self, _agent_id):
        return {"total_entries": 0, "by_type": {}}


class TestMemoryDetailKeepsFaultAndMissApart:
    def test_internalFaultIsNotReportedAsMissing(self, monkeypatch):
        from neurova.api.endpoints.memory import base, crud

        def _boom(_agent_id=None, _user=None):
            class _M:
                def get_memory(self, memory_id, agent_wide=False):
                    raise RuntimeError("底座库不可用")

            return _M()

        monkeypatch.setattr(crud, "get_memory_manager", _boom)
        resp = _mount(base.router, "/api/v1/memory").get("/api/v1/memory/mem-1")

        assert resp.status_code == 500, (
            "读面出错被折成了别的结论——状态码：%d，body：%r" % (resp.status_code, resp.text))
        assert str(ErrorCodes.MEMORY_OPERATION_FAILED.value) in resp.text, (
            "500 也要点名是哪一类故障，别只留一句泛化消息：%r" % resp.text)

    def test_genuineMissIsStillFourOhFour(self, monkeypatch):
        """反向对照：真查无此条必须还是 404/7002，不能被这次改动一并推到 500。"""
        from neurova.api.endpoints.memory import base, crud

        def _none(_agent_id=None, _user=None):
            class _M:
                def get_memory(self, memory_id, agent_wide=False):
                    return None

            return _M()

        monkeypatch.setattr(crud, "get_memory_manager", _none)
        resp = _mount(base.router, "/api/v1/memory").get("/api/v1/memory/nope")

        assert resp.status_code == 404, resp.text
        assert str(ErrorCodes.NOT_FOUND.value) in resp.text, (
            "真查无此条仍须走 404 那一族码（本仓 `APIError.not_found` 用 %s），"
            "不能被这次改动一并推到 500：%s" % (ErrorCodes.NOT_FOUND.value, resp.text))


class TestFirewallStatsIsNotSilentlyZero:
    def test_serviceFaultIsNotReportedAsNoRules(self, monkeypatch):
        from neurova.api.endpoints import firewall

        def _boom():
            raise RuntimeError("防火墙服务初始化失败")

        monkeypatch.setattr(firewall, "get_firewall", _boom)
        resp = _mount(firewall.router, "/api/v1/firewall").get("/api/v1/firewall/stats")

        assert resp.status_code == 500, (
            '故障被报成 "code:0 + 全 0"，安全面会把"读不到"当成"没规则"：%d %s'
            % (resp.status_code, resp.text))
        assert resp.json().get("message") != "success", (
            "500 的同时还发成功信封——两件事各说一半，比原来更难查：%r" % resp.text)


class TestLogoutDoesNotInvalidateNothingSilently:
    """`auth.py::logout` 的同族形态，且多一层：**外层 catch-all 把内层那记 500 也吞了**。

    S-12 的修正在函数体内 `raise HTTPException(500)`，注释写着"不得谎报登出成功"；
    而它外面还套着 `except Exception: return {code:0,'Logged out successfully'}`
    —— HTTPException 本身是 Exception 的子类，那记 500 **永远到不了客户端**。
    ⇒ 这是一处"已声明意图却被同函数另一段静默作废"的死修正，安全面。
    """

    def _client(self):
        from fastapi import FastAPI

        from neurova.api.endpoints import auth

        app = FastAPI()
        app.include_router(auth.router, prefix="/v1/auth")
        register_error_handlers(app)
        return TestClient(app, raise_server_exceptions=False)

    def test_blacklistFaultIsNotReportedAsLoggedOut(self, monkeypatch):
        from neurova.api import auth as global_auth

        def _boom(_token):
            raise RuntimeError("全局黑名单库不可写")

        monkeypatch.setattr(global_auth, "blacklist_token", _boom, raising=True)
        resp = self._client().post(
            "/v1/auth/logout", headers={"Authorization": "Bearer opaque-token-abc"})

        assert resp.status_code == 500, (
            '撤销失败被折成 "200 Logged out successfully"，客户端据此清本地凭据、'
            '而服务端 token 仍然有效：%d %s' % (resp.status_code, resp.text))

    def test_logout_succeeds_when_invalidation_works(self, monkeypatch):
        """反向对照：正常登出仍然是 200，本次改动不许把成功路径一并变成故障。"""
        from neurova.api import auth as global_auth

        seen = []
        monkeypatch.setattr(global_auth, "blacklist_token",
                            lambda token: seen.append(token), raising=True)
        resp = self._client().post(
            "/v1/auth/logout", headers={"Authorization": "Bearer opaque-token-xyz"})

        assert resp.status_code == 200, resp.text
        assert seen == ["opaque-token-xyz"], "200 的同时注册单点没被调用——假绿：%r" % (seen,)

    def test_logout_without_credential_is_still_two_hundred(self):
        """反向对照第二格：没带凭据时没有可撤销物，幂等成功应当保留（不是每条 200 都是谎报）。"""
        resp = self._client().post("/v1/auth/logout")

        assert resp.status_code == 200, resp.text


class TestMetacognitionReadoutDistinguishesFaultFromEmpty:
    def test_recordsFaultIsNotAnEmptyList(self, monkeypatch):
        from neurova.api.endpoints.memory import base, metacognition

        monkeypatch.setattr(metacognition, "get_meta_ledger", lambda *_a, **_kw: _BoomLedger())
        resp = _mount(base.router, "/api/v1/memory").get("/api/v1/memory/a1/metacognition")

        assert resp.status_code == 500, (
            '读面出错被画成"这个 agent 没有元认知记录"（前端只会显示空列表）：%d %s'
            % (resp.status_code, resp.text))

    def test_recordsFaultIsNotAllZeroStats(self, monkeypatch):
        from neurova.api.endpoints.memory import base, metacognition

        monkeypatch.setattr(metacognition, "get_meta_ledger", lambda *_a, **_kw: _BoomLedger())
        resp = _mount(base.router, "/api/v1/memory").get("/api/v1/memory/a1/metacognition/stats")

        assert resp.status_code == 500, resp.text

    def test_genuineEmptyIsStillTwoHundred(self, monkeypatch):
        """反向对照：真空数据仍然是 200 + 空，本次改动不许把"没有"也变成故障。"""
        from neurova.api.endpoints.memory import base, metacognition

        monkeypatch.setattr(metacognition, "get_meta_ledger", lambda *_a, **_kw: _EmptyLedger())
        client = _mount(base.router, "/api/v1/memory")

        records = client.get("/api/v1/memory/a1/metacognition")
        stats = client.get("/api/v1/memory/a1/metacognition/stats")

        assert records.status_code == 200, records.text
        assert records.json()["data"]["items"] == []
        assert stats.status_code == 200, stats.text
        assert stats.json()["data"]["total"] == 0
