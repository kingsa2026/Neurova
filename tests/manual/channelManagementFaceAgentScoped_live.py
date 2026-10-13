# -*- coding: utf-8 -*-
"""§6-190 活体自证：渠道管理面也能精确到 agent 了，健康视图不再只看得见 default 那一格。

真跑的东西：真 `create_app()` + 真 lifespan + 真 HTTP 端点（`/api/v1/channel-adapters` 那一族）
+ 真 `ChannelManager.register_adapter(..., agent_id=...)` + 真 `FeishuAdapter` 两只。
登录门是装配噪声不是被测行为 ⇒ 覆盖 `get_current_user`（收尾必须清，`create_app()` 缓存实例会
把覆盖泄漏给下一档测试）。适配器方法各包一层记录器 ⇒ 不碰网络、不起 agent、不调模型、不花配额。

读数分组：
① 健康视图两份（`GET ""` 与 `GET /health/all`）都含 `kai:feishu` 这一条，且 default 仍是裸键
   `feishu`（向后兼容没破）；两者键集相等 ⇒ 同一份视图，不是两处各写一遍；
② `GET /{type}`、`/connect`、`/disconnect` 带 `agent_id=kai` 时，动手的是 kai 那只、default 那只
   一次没被碰；
③ 点名一个没配的 agent ⇒ 404 且**没去碰任何一只实例**（不能被 default 顶掉——§6-189 同一条纪律）；
④ 不带 `agent_id` 时仍打 default（既有调用者行为一字不变）；
⑤ 契约文本：从该 router **自己的**路由表反读地址与方法（`app.routes` 在本仓挂载方式下只有 5/95 条
   带 `.path`，拿它当真路由表会近乎空集、令"一致"自动成立），逐条与模块 docstring 双向对上，
   顺带证明清单里从未有过的旧写法 `/channel-adapters/channels/feishu` 既不在路由表也不可达
   ——那正是本批修掉前一路被写在权威位置上的错地址。

边界：本支不证真平台上这些地址可用（外部反向代理/网关未参与），证的是本仓路由表与契约文本一致。
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
PREFIX = "/api/v1/channel-adapters"
REPO = pathlib.Path(__file__).resolve().parents[2]


def _normPath(template: str) -> str:
    """把契约文本里的绝对地址与 router 里的相对地址并到同一形状上比。"""
    tail = template[len(PREFIX):] if template.startswith(PREFIX) else template
    return (tail.rstrip("/") or "").replace("{type}", "{channel_type}")


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    print(f"数据根（临时）：{isolatedDataRoot()}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    ChannelManager._instance = None
    touched = {"status": [], "connect": [], "disconnect": []}

    def _make(agentId):
        adapter = FeishuAdapter(ChannelConfig(
            channel_type="feishu", app_id=f"cli_{agentId}", app_secret="sec",
            verification_token="tok", use_stream=False))

        async def _health():
            touched["status"].append(agentId)
            return {"channel_type": "feishu", "agent_id": agentId, "connected": True}

        async def _connect():
            touched["connect"].append(agentId)
            return True

        async def _disconnect():
            touched["disconnect"].append(agentId)
            return None

        adapter.health_check, adapter.connect, adapter.disconnect = _health, _connect, _disconnect
        return adapter

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: {"sub": "tester-b29-live"}
        mgr = get_channel_manager()
        for agentId in ("default", "kai"):
            mgr.register_adapter(_make(agentId), agent_id=agentId)

        print("\n① 健康视图：两份端点都要看得见 kai 那一格")
        listed = client.get(PREFIX).json().get("adapters") or {}
        healthAll = client.get(f"{PREFIX}/health/all").json().get("adapters") or {}
        _check("kai:feishu" in listed, f"`GET {PREFIX}` 的键集含 kai:feishu（实得 {sorted(listed)}）")
        _check("feishu" in listed, "default 仍按裸键 feishu 出现（向后兼容未破）")
        _check(set(listed) == set(healthAll),
               f"两个端点读同一份视图（差异 {sorted(set(listed) ^ set(healthAll))}）")
        _check((listed.get("kai:feishu") or {}).get("agent_id") == "kai",
               f"条带没写出归属（实得 {listed.get('kai:feishu')}）")

        print("\n② 带 agent_id 的管理请求只动那一只")
        for bucket, verb, call in (
                ("status", "GET 状态", lambda a: client.get(f"{PREFIX}/feishu", params=a)),
                ("disconnect", "POST 断开", lambda a: client.post(f"{PREFIX}/feishu/disconnect", params=a)),
                ("connect", "POST 连接", lambda a: client.post(f"{PREFIX}/feishu/connect",
                                                              params=a, json={"use_stream": False})),
        ):
            touched[bucket] = []
            r = call({"agent_id": "kai"})
            _check(r.status_code == 200 and touched[bucket] == ["kai"],
                   f"{verb} agent_id=kai ⇒ 只动了 {touched[bucket]}（HTTP={r.status_code}）")

        print("\n③ 点名没配的 agent：404，且不碰任何一只实例")
        for bucket in touched:
            touched[bucket] = []
        r = client.get(f"{PREFIX}/feishu", params={"agent_id": "ghost_agent"})
        _check(r.status_code == 404 and touched["status"] == [],
               f"不存在的 agent 拿到了 {r.status_code}，被碰的实例 {touched['status']}")

        print("\n④ 不带参数时仍走 default（既有调用者一字不变）")
        touched["status"] = []
        r = client.get(f"{PREFIX}/feishu")
        _check(r.status_code == 200 and touched["status"] == ["default"],
               f"缺省行为：被碰的是 {touched['status']}（HTTP={r.status_code}）")

        print("\n⑤ 契约文本与真路由表一致")
        # 真路由表面**不能**从 `app.routes` 读：本仓挂载走 `_IncludedRouter`，95 条里只有 5 条带
        # `.path`，于是 realPaths 近乎空集，"两边一致"与"旧地址不存在"都会自动成立——假绿。
        # 改读该 router 自己的路由表，并给读数加地板断言（空集是口径失效，不是"没有差异"）。
        from neurova.api.endpoints import channels as channelsModule

        realPairs = {(mth, route.path.rstrip("/"))
                     for route in channelsModule.router.routes
                     for mth in (getattr(route, "methods", None) or set())
                     if isinstance(getattr(route, "path", None), str)}
        _check(len(realPairs) >= 10,
               f"真路由表读到 {len(realPairs)} 条（地板 10）——取数口径没空转")
        _check(any(p == "/{channel_type}/webhook" for _mth, p in realPairs),
               f"读数里有 webhook 那条（共 {len(realPairs)} 项）")

        src = (REPO / "neurova" / "api" / "endpoints" / "channels.py").read_text(encoding="utf-8")
        declaredPairs = {(m.group(1), _normPath(m.group(2)))
                         for m in re.finditer(r"^-+\s+([A-Z]+)\s+(\S+)\s+-", src, re.M)}
        _check(len(declaredPairs) >= 10, f"清单解析出 {len(declaredPairs)} 条（地板 10）")
        realNorm = {(mth, _normPath(p)) for mth, p in realPairs}
        _check(declaredPairs == realNorm,
               f"契约与真路由逐条相等（只在契约 {sorted(declaredPairs - realNorm)}，"
               f"只在路由 {sorted(realNorm - declaredPairs)}）")
        _check(not any("/channels/{channel_type}" in p or p.endswith("/channels/feishu")
                       for _mth, p in realNorm),
               f"路由表 {len(realNorm)} 条里没有旧写法 `/channel-adapters/channels/...`")
        r = client.get(f"{PREFIX}/channels/feishu")
        _check(r.status_code in (404, 405),
               f"按修好前的 docstring 地址请求 ⇒ HTTP={r.status_code}（不可达，正是本批改掉的那个错地址）")

        client.app.dependency_overrides.pop(get_current_user, None)
        mgr.unregister_adapter("feishu", agent_id="kai")
        mgr.unregister_adapter("feishu", agent_id="default")
        _check(mgr.get_adapter("feishu") is None and mgr.list_adapters() == {},
               "收尾：临时实例与覆盖都清干净了")

    print()
    print("  边界：证的是本仓路由表、健康视图与契约文本三处一致，不证外部网关下的可用性。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
