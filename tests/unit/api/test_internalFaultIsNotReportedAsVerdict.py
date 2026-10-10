# -*- coding: utf-8 -*-
"""内部故障不许被折成"查无此类/没有数据"的结论（台账 §6-126，用户 2026-10-10 裁定改 4 处）。

缺陷形态三处同族：宽 `except Exception` 之后
① `memory/crud.py:260` 抛 `MEMORY_NOT_FOUND` ⇒ 404 壳里装 500 的话（DB 锁被读成"这条记忆不存在"）；
② `firewall.py:471-476` 回 `code:0 + 全 0` ⇒ 故障被读成"防火墙没规则"（安全面）；
③ `memory/metacognition.py:428/456` 回 `success_response(空)` ⇒ 读面出错画成空列表/全 0 统计。
**方向搞反的读数比没有读数更坏**：排查时"空"是最可信的信号，异常被它吸收掉就再也不露头。

每处都配一格**反向对照**（真·无数据仍须 200/404），否则修法只是"把一切变 500"——
那同样是把两件事折成一件事，只是折朝另一边。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.error_handlers import register_error_handlers
from neurova.interfaces.api_standard import ErrorCodes

USER = {"user_id": "1", "username": "tester", "role": "user"}


def _mount(router, prefix: str):
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    register_error_handlers(app)
    app.dependency_overrides[get_current_user_or_default] = lambda: dict(USER)
    # 装配噪声先排掉：firewall 的路由级依赖是 `get_current_user`，
    # 不覆盖就整族 401——红会咬在"没鉴权"上而不是"把故障读成结论"上。
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    return TestClient(app, raise_server_exceptions=False)


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
