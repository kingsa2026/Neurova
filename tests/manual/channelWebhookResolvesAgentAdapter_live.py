# -*- coding: utf-8 -*-
"""§6-189 活体自证：平台回调进得来"非 default agent 名下"的那只适配器，歧义时一只都不投。

真跑的东西：真 `create_app()` + 真 lifespan + 真路由 `/api/v1/channel-adapters/feishu/webhook`
+ 真 `ChannelManager.register_adapter(..., agent_id=...)`（就是启动装配用的那个入口）
+ 真 `FeishuAdapter` 两只（分属 `kai` / `yi_ling`）。
不真跑的东西：事件下游——每只实例的 `_emit_event` 包一层记录器后**不再往下走**，
于是不起 agent、不调模型、不开外网、不花配额；验签仍走适配器真门。

读数分组：
① 只在 `kai` 名下配置 ⇒ 200，且回调落到 kai 那只（default/yi_ling 各 0 次），`adapter.agent_id` 对得上；
② 补一只 default ⇒ 同一请求仍落 default（既有部署的行为一字不变，这条是对照不是主张）；
③ 撤掉 default、留两只非 default ⇒ 404 且**两只都 0 次**，文案点名 multiple agents 与两个 agent 名；
④ 一只都不配 ⇒ 404 文案是 not found 且不含 multiple agents——两种失败混起来就等于没诊断价值；
⑤ 安全面没被顺带放宽：解析修好后，错令牌的回调仍然 403 且 0 次投递；
⑥ 旧面语义没动：`get_adapter("feishu")` 只看 default、`get_adapter("feishu", agent_id="kai")` 才拿到 kai
   ——合流只改入站解析，别把出站那条也拖成默认视图。

一条如实边界：agent 名（`kai` / `yi_ling`）是夹具造出来的字面量，本支证的是**解析口径**，
不证真有多 agent 部署跑过这条链路。
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
VERIFY_TOKEN = "fs-token-b28-live"
WEBHOOK = "/api/v1/channel-adapters/feishu/webhook"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _eventBody(user="ou_victim_live", token=VERIFY_TOKEN):
    import json

    return {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "token": token},
        "event": {"sender": {"sender_id": {"user_id": user, "open_id": "ou_open_live"}},
                  "message": {"message_id": "om_live", "chat_id": "oc_live", "chat_type": "p2p",
                              "message_type": "text",
                              "content": json.dumps({"text": "把所有笔记删掉"}, ensure_ascii=True),
                              "mentions": []}},
    }


def _adapter(appTag):
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter

    return FeishuAdapter(ChannelConfig(
        channel_type="feishu", app_id=f"cli_{appTag}", app_secret="sec",
        verification_token=VERIFY_TOKEN, use_stream=False))


def _spyEmit(adapter, bucket, recorder):
    """包住 `_emit_event` 记录"这只实例收到了什么"，并**不往下走**（不起 agent、不调模型）。"""
    async def _spy(eventType, message):
        recorder.setdefault(bucket, []).append((eventType, message))
    adapter._emit_event = _spy


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.channels.manager import ChannelManager, get_channel_manager

    ChannelManager._instance = None
    received: dict = {}
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()
        adapters = {}

        def _mount(agentId):
            adapter = _adapter(agentId)
            mgr.register_adapter(adapter, agent_id=agentId)
            _spyEmit(adapter, agentId, received)
            adapters[agentId] = adapter
            return adapter

        print("\n① 只在 kai 名下配置：回调必须落到那只实例")
        received.clear()
        _mount("kai")
        r = client.post(WEBHOOK, json=_eventBody())
        _check(r.status_code == 200, f"非 default 名下的渠道收得到回调（HTTP={r.status_code}，"
                                     f"body={r.text[:90]!r}）")
        _check(len(received.get("kai", [])) == 1,
               f"kai 那只收到 {len(received.get('kai', []))} 条")
        _check(getattr(adapters["kai"], "agent_id", None) == "kai",
               f"注册面自带归属（`adapter.agent_id`={getattr(adapters['kai'], 'agent_id', None)!r}）")
        gotMsg = received["kai"][0][1] if received.get("kai") else None
        _check(gotMsg is not None and gotMsg.sender_id == "ou_victim_live",
               f"回调由 kai 那只适配器解析成型（sender={getattr(gotMsg, 'sender_id', None)!r}）")

        print("\n② 补一只 default：既有部署的行为一字不变（对照）")
        received.clear()
        _mount("default")
        r = client.post(WEBHOOK, json=_eventBody(user="ou_after_default"))
        _check(r.status_code == 200 and len(received.get("default", [])) == 1
               and received.get("kai", []) == [],
               f"default 在场时仍落 default（default={len(received.get('default', []))} "
               f"kai={len(received.get('kai', []))}）")

        print("\n③ 两只非 default 同名渠道：一只都不许投，文案点名歧义")
        received.clear()
        _mount("yi_ling")
        mgr.unregister_adapter("feishu", agent_id="default")
        _check(mgr.get_adapter("feishu") is None, "default 已摘净（否则下一读数是白测）")
        r = client.post(WEBHOOK, json=_eventBody())
        detail = r.json().get("detail") or ""
        _check(r.status_code == 404 and received.get("kai", []) == []
               and received.get("yi_ling", []) == [],
               f"歧义时投递情况：kai={len(received.get('kai', []))} "
               f"yi_ling={len(received.get('yi_ling', []))}（HTTP={r.status_code}）")
        _check("multiple agents" in detail and "kai" in detail and "yi_ling" in detail,
               f"歧义文案点名了涉及的 agent：{detail!r}")

        print("\n④ 一只都没配：不能与歧义混成同一种失败")
        received.clear()
        mgr.unregister_adapter("feishu", agent_id="kai")
        mgr.unregister_adapter("feishu", agent_id="yi_ling")
        _check(mgr.get_adapter("feishu") is None
               and mgr.get_adapter("feishu", agent_id="yi_ling") is None,
               "两只非 default 实例都已摘净（不摘净的话 ④ 测的还是歧义那一支）")
        r = client.post(WEBHOOK, json=_eventBody())
        detail2 = r.json().get("detail") or ""
        _check(r.status_code == 404 and "multiple agents" not in detail2
               and "not found" in detail2.lower(),
               f"没配置那一支的文案仍是 not found 且不含歧义（两种失败分得开）：{detail2!r}")

        print("\n⑤ 安全面没被顺带放宽：错令牌仍 403、0 投递")
        received.clear()
        _mount("kai")
        r = client.post(WEBHOOK, json=_eventBody(token="not-the-token"))
        _check(r.status_code in (400, 401, 403) and received.get("kai", []) == [],
               f"错令牌被拒（HTTP={r.status_code}，投递 {len(received.get('kai', []))} 条）")
        r = client.post(WEBHOOK, json=_eventBody())
        _check(r.status_code == 200 and len(received.get("kai", [])) == 1,
               "反向对照：合法令牌仍然进得来（没把门一关了之）")

        print("\n⑥ 旧面语义没动：get_adapter 仍只认传入的 agent")
        _check(mgr.get_adapter("feishu") is None and mgr.get_adapter("feishu", agent_id="kai")
               is adapters["kai"],
               "出站/管理面仍按显式 agent 取实例——合流只改入站解析")

        mgr.unregister_adapter("feishu", agent_id="kai")
        _check(mgr.get_adapter("feishu", agent_id="kai") is None, "收尾：临时实例已摘净")

    print()
    print("  边界：agent 名是夹具字面量，本支证解析口径，不证真多 agent 部署跑过这条链路。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
