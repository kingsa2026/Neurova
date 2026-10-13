# -*- coding: utf-8 -*-
"""§6-195 活体自证：点名叫哪一只 bot，就不许由另一只把这条消息发出去；广播从此看得见全量实例。

真跑的东西：真 `create_app()` + 真 lifespan + 真 HTTP 端点（`POST /api/v1/channel-adapters/{type}/send`）
+ 真 `ChannelManager.register_adapter(..., agent_id=...)` + 真 `FeishuAdapter`/`DingTalkAdapter` 实例。
适配器的 `send_message` 与 manager 的会话回写都换成记录器 ⇒ **不开外网、不起 agent、不调模型、不花配额**；
`_dispatch_message`/入站那半侧不参与本批主张。

读数分组（每段都成对：点名必命中、点名落空必诚实失败、旧语义必不变）：
① `?agent_id=kai` 且 kai 名下有实例 ⇒ success=true，只有 kai 那只被叫到一次。
② `?agent_id=ghost`（没配的那只）⇒ success=false，且 **default 那只一次都没被叫到**
   ——这正是本批改掉的错投：改之前这条由 default 的 bot 发出去、回执还写成功。
③ 未点名的旧语义（`neurflow` 审批通知那一形）⇒ 仍走 default 视图、返回消息 ID。
④ 广播 ⇒ 非 default 名下那格真被叫到，键集含 `feishu`（裸键向后兼容）与 `kai:dingtalk`，
   且 caller 那一形 `list(results.values())[0]` 拿到的不是 None。
⑤ 反证段：把 default 那三只全摘掉、只留 kai ⇒ 未点名/点名 default 都**诚实失败并点名**，
   绝不"顺手"借用 kai 那只（否则②③两段的语义就成了空话）。
⑥ 收尾：临时实例与依赖覆盖都摘净，运行时不留状态。

边界：本支不证真平台收到这些消息（没连飞书/钉钉，出站全是记录器）；证的是本仓出站取实例的
两态语义与广播的定义域。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
SEND = "/api/v1/channel-adapters/{}/send"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    print(f"数据根（临时）：{isolatedDataRoot()}")

    import asyncio

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.channels.base import ChannelConfig
    from neurova.channels.dingtalk import DingTalkAdapter
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels import manager as managerModule

    sent: dict = {}

    def _make(cls, channelType, agentId, **extra):
        adapter = cls(ChannelConfig(channel_type=channelType, app_id=f"app_{agentId}",
                                    app_secret="sec", use_stream=False, **extra))
        adapter._connected = True

        async def _send(chat_id, content, message_type="text", **kwargs):
            sent.setdefault((agentId, channelType), []).append((chat_id, content))
            return f"msg_{agentId}_{channelType}"

        adapter.send_message = _send
        return adapter

    ChannelManager._instance = None
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        client.app.dependency_overrides[get_current_user] = lambda: {"sub": "tester-b31-live"}
        mgr = get_channel_manager()

        async def _noSessionSync(*args, **kwargs):
            return None

        mgr._sync_reply_to_session = _noSessionSync
        mgr.ingress_queue = False

        for cls, channelType, agentId in ((FeishuAdapter, "feishu", "default"),
                                          (FeishuAdapter, "feishu", "kai"),
                                          (DingTalkAdapter, "dingtalk", "kai")):
            adapter = _make(cls, channelType, agentId)
            mgr.register_adapter(adapter, agent_id=agentId)

        print("\n① 点名且名下有实例：只有那一只被叫到")
        sent.clear()
        r = client.post(SEND.format("feishu"), params={"agent_id": "kai"},
                        json={"chat_id": "oc_1", "content": "kai 的话"})
        body = r.json()
        _check(r.status_code == 200 and body.get("success") is True,
               f"`?agent_id=kai` ⇒ HTTP={r.status_code} success={body.get('success')}")
        _check(sorted(sent) == [("kai", "feishu")],
               f"被叫到的实例只有 kai/feishu（实得 {sorted(sent)}）")

        print("\n② 点名但名下没有：诚实失败，且 default 那只一次都不许动")
        sent.clear()
        errors = []
        originalErr = managerModule.logger.error

        def _capture(fmt, *a, **k):
            errors.append(str(fmt) % a if a else str(fmt))
            return originalErr(fmt, *a, **k)

        managerModule.logger.error = _capture
        try:
            r = client.post(SEND.format("feishu"), params={"agent_id": "ghost_agent"},
                            json={"chat_id": "oc_2", "content": "这条不该发出去"})
        finally:
            managerModule.logger.error = originalErr
        body = r.json()
        _check(body.get("success") is False,
               f"`?agent_id=ghost` ⇒ success={body.get('success')}（改之前这里是 true——由 default 的 bot 发出）")
        _check(sent == {}, f"一只都没被叫到（实得 {sorted(sent)}）——回落就是拿别人的身份说话")
        _check(any("ghost_agent" in e and "feishu" in e for e in errors),
               f"失败日志点名是哪个 agent 的哪条渠道（实得 {errors}）")

        print("\n③ 未点名的旧语义一字不变（neurflow 审批通知那一形）")
        sent.clear()
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_3",
                                           content="审批请回复"))
        _check(mid == "msg_default_feishu" and sorted(sent) == [("default", "feishu")],
               f"未点名仍走 default 视图：{mid!r} / {sorted(sent)}")

        print("\n④ 广播看得见全量实例，且裸键向后兼容")
        sent.clear()
        results = asyncio.run(mgr.broadcast_message(content="审批通知", message_type="text"))
        _check(("kai", "feishu") in sent and ("kai", "dingtalk") in sent,
               f"kai 名下两实例都收到广播（被叫到 {sorted(sent)}）")
        _check(set(results) == {"feishu", "kai:feishu", "kai:dingtalk"},
               f"结果键集＝default 裸键 + 其余带 agent 前缀（实得 {sorted(results)}）")
        _check(list(results.values())[0] is not None,
               f"caller 那一形 `list(results.values())[0]` 仍可取到第一条（实得 {results}）")

        print("\n⑤ 反证段：default 全摘掉之后，未点名不许借用 kai 那只")
        mgr.unregister_adapter("feishu", agent_id="default")
        sent.clear()
        errors.clear()
        managerModule.logger.error = _capture
        try:
            mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_5",
                                               content="只剩 kai 名下的那条渠道"))
        finally:
            managerModule.logger.error = originalErr
        _check(mid is None and sent == {},
               f"未点名时不『顺手』借用别的 agent 实例：{mid!r} / {sorted(sent)}")
        _check(any("default" in e for e in errors), f"日志仍点名它找的是哪一态（实得 {errors}）")

        client.app.dependency_overrides.pop(get_current_user, None)
        for channelType, agentId in (("feishu", "kai"), ("dingtalk", "kai")):
            mgr.unregister_adapter(channelType, agent_id=agentId)
        _check(not mgr.list_adapters(), f"收尾：临时实例摘净（残留 {mgr.list_adapters()}）")

    print()
    print("  边界：出站全是记录器，不证真平台送达；证的是本仓出站取实例的两态语义与广播定义域。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
