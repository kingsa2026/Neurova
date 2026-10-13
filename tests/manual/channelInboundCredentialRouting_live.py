# -*- coding: utf-8 -*-
"""§6-197 活体自证：入站回调落到哪一只实例，由这条回调自己的凭据说（不是由 default 说）。

真跑的东西：真 `create_app()` + 真 lifespan + 真 HTTP 端点 `/api/v1/channel-adapters/{type}/webhook`
+ 真 `ChannelManager.register_adapter(..., agent_id=...)` + 真 `FeishuAdapter`/`DingTalkAdapter`
/`WeComAdapter` 实例（各配各的凭据）。投递面（`_dispatch_message`）换记录器 ⇒ **不起 agent、
不调模型、不开外网、不花配额**；签名与令牌由**仓内那条官方公式本地自算**，因此本支
**不证与真平台逐字节互操作**（§6-181 同一边界）。

读数分组：
① 两只飞书各一份 verification token ⇒ kai 的 token 进 kai、default 的 token 进 default（成对，
   这才叫"每 agent 专属配置"）；
② 两只钉钉各一份 appSecret ⇒ 各自 timestamp+sign 各进各的；拿 A 的签名冒充 B ⇒ 拒且 0 投递；
③ 两只**共用同一份凭据** ⇒ 拒、点名是哪两只、0 投递（这是 §6-197 的行为变更：旧行为是静默进 default）；
④ 单只候选时不依赖谓词，但投递前那道门照旧拦错凭据（路由与投递两道门都要在）；
⑤ 飞书密文回调 ⇒ 谓词让路，真原因由 handler 点名"encrypted … not supported"，
   不许被改写成"凭据不匹配"这种错诊断；
⑥ 企微真 `WeComAdapter` 两只（各配一份 callback token）：谓词只认自己 token 签出的名；
   签名属于 kai 的那条回调，kai 那只照常投递、default 那只**不投**（fail-closed 没被抽取放宽）。
⑦ 收尾：临时实例注销、投递面复原，运行时不留状态。

一条如实边界：企微的 `handle_callback` 把事件调度到 `connect()` 捕到的主循环（`wecom.py:164`），
本支不连真平台连接，所以按同一形状**另起一只真在跑的循环**交给它——不这么做的话"没投递"
读的是探针自己的洞。⑥ 因此证的是"签名归属决定投不投"，不证与企微服务器的互操作。
"""

import asyncio
import base64
import hashlib
import hmac
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
WEBHOOK = "/api/v1/channel-adapters/{}/webhook"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _dtSign(ts: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _fsBody(token: str, user: str) -> dict:
    return {"schema": "2.0", "header": {"token": token, "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_id": {"user_id": user}},
                      "message": {"message_id": f"om_{user}", "chat_id": "oc_1",
                                  "message_type": "text", "content": "{\"text\":\"进哪只\"}"}}}


def _dtBody(user: str) -> dict:
    return {"senderId": user, "senderNick": user, "conversationId": "cid-1",
            "conversationType": "1", "msgId": f"m_{user}", "msgtype": "text",
            "text": {"content": "进哪只"}}


def _main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    print(f"数据根（临时）：{isolatedDataRoot()}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.endpoints import channels as channelsModule
    from neurova.channels.base import ChannelConfig
    from neurova.channels.dingtalk import DingTalkAdapter
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels.wecom import WeComAdapter, _wecom_callback_signature

    delivered: list = []
    ChannelManager._instance = None
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()
        mgr.ingress_queue = False
        originalDispatch = mgr._dispatch_message

        async def _record(message):
            delivered.append(message)

        mgr._dispatch_message = _record

        def _register(cls, agentId, **cfg):
            adapter = cls(ChannelConfig(**cfg))
            mgr.register_adapter(adapter, agent_id=agentId)
            return adapter

        print("\n① 飞书：各 agent 各有专属 verification token ⇒ 谁的 token 进谁那只")
        _register(FeishuAdapter, "default", channel_type="feishu", app_id="cli_def",
                  app_secret="s", verification_token="tok-def-live", use_stream=False)
        _register(FeishuAdapter, "kai", channel_type="feishu", app_id="cli_kai",
                  app_secret="s", verification_token="tok-kai-live", use_stream=False)

        delivered.clear()
        r = client.post(WEBHOOK.format("feishu"), json=_fsBody("tok-kai-live", "ou_kai_user"))
        kaiOnly = [m for m in delivered if m.metadata.get("agent_id") == "kai"]
        _check(r.status_code == 200 and len(kaiOnly) == 1 and len(delivered) == 1,
               f"kai 的 token ⇒ 只进 kai 那只（HTTP={r.status_code}，进门归属 "
               f"{[m.metadata.get('agent_id') for m in delivered]}）")

        delivered.clear()
        r = client.post(WEBHOOK.format("feishu"), json=_fsBody("tok-def-live", "ou_def_user"))
        _check(r.status_code == 200 and len(delivered) == 1
               and delivered[0].metadata.get("agent_id") == "default",
               f"default 的 token ⇒ 仍进 default（HTTP={r.status_code}，归属 "
               f"{[m.metadata.get('agent_id') for m in delivered]}）")

        print("\n② 钉钉：各 agent 各有专属 appSecret ⇒ 签名算得通的那只收")
        _register(DingTalkAdapter, "kai", channel_type="dingtalk", app_id="ding_kai",
                  app_secret="sec-kai-live", use_stream=False)
        _register(DingTalkAdapter, "yi_ling", channel_type="dingtalk", app_id="ding_yi",
                  app_secret="sec-yi-live", use_stream=False)
        ts = str(int(time.time() * 1000))
        delivered.clear()
        r = client.post(WEBHOOK.format("dingtalk"), json=_dtBody("dt_kai"),
                        headers={"timestamp": ts, "sign": _dtSign(ts, "sec-kai-live")})
        _check(r.status_code == 200 and len(delivered) == 1
               and delivered[0].metadata.get("agent_id") == "kai",
               f"kai 的 secret 签的名 ⇒ 进 kai 那只（HTTP={r.status_code}，"
               f"归属 {[m.metadata.get('agent_id') for m in delivered]}）")

        delivered.clear()
        stale = str(int(time.time() * 1000) - 2 * 3600 * 1000)
        r = client.post(WEBHOOK.format("dingtalk"), json=_dtBody("dt_forged"),
                        headers={"timestamp": stale, "sign": _dtSign(stale, "sec-yi-live")})
        _check(r.status_code in (401, 403, 404) and not delivered,
               f"过期两小时但签名对得上 yi 的回调 ⇒ HTTP={r.status_code}、投递 {len(delivered)} 条"
               f"（凭据裁决不许把'时间窗'这条放宽）")

        print("\n③ 两只共用同一份凭据 ⇒ 拒、点名、0 投递（旧行为是静默进 default）")
        mgr.get_adapter("feishu", agent_id="kai").config.verification_token = "tok-def-live"
        delivered.clear()
        r = client.post(WEBHOOK.format("feishu"), json=_fsBody("tok-def-live", "ou_ambiguous"))
        detail = (r.json() or {}).get("detail") or ""
        _check(r.status_code in (403, 404) and not delivered,
               f"共用凭据的回调 ⇒ HTTP={r.status_code}、投递 {len(delivered)} 条")
        _check("default" in detail and "kai" in detail, f"文案点名了冲突双方：{detail[:110]!r}")
        mgr.get_adapter("feishu", agent_id="kai").config.verification_token = "tok-kai-live"

        print("\n④ 单只候选：不依赖谓词，但投递前那道门照旧拦错凭据")
        mgr.unregister_adapter("feishu", agent_id="default")
        delivered.clear()
        ok = client.post(WEBHOOK.format("feishu"), json=_fsBody("tok-kai-live", "ou_only"))
        bad = client.post(WEBHOOK.format("feishu"), json=_fsBody("tok-nope", "ou_forge"))
        _check(ok.status_code == 200 and len(delivered) == 1,
               f"唯一格照常进（HTTP={ok.status_code}，投递 {len(delivered)} 条）")
        _check(bad.status_code in (401, 403) and len(delivered) == 1,
               f"错凭据仍被投递门拦下（HTTP={bad.status_code}，累计投递 {len(delivered)} 条）")

        print("\n⑤ 密文回调：谓词让路，真原因由 handler 点名")
        delivered.clear()
        r = client.post(WEBHOOK.format("feishu"), json={"encrypt": "aGVsbG8td29ybGQ="})
        detail = (r.json() or {}).get("detail") or ""
        _check(r.status_code in (401, 403) and "encrypt" in detail.lower()
               and "not supported" in detail.lower(),
               f"密文 ⇒ HTTP={r.status_code}，原因如实：{detail[:90]!r}")
        _check(not delivered, f"密文回调投递了 {len(delivered)} 条")

        print("\n⑥ 企微：真两只各一份 callback token ⇒ 谓词只认自己的名，另一只不投")
        kaiW = _register(WeComAdapter, "kai", channel_type="wecom", app_id="ww_kai",
                         app_secret="s", webhook_token="wec-token-kai")
        defW = _register(WeComAdapter, "default", channel_type="wecom", app_id="ww_def",
                         app_secret="s", webhook_token="wec-token-def")
        # 明文回调：无 `<Encrypt>` 时签名第 4 元取空串（见 `_wecom_callback_signature` 的说明）
        plain = ("<xml><ToUserName><![CDATA[ww_kai]]></ToUserName>"
                 "<FromUserName><![CDATA[u_wecom]]></FromUserName>"
                 "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[text]]></MsgType>"
                 "<Content><![CDATA[进哪只]]></Content><MsgId>88</MsgId><AgentID>100</AgentID></xml>")
        query = {"msg_signature": _wecom_callback_signature("wec-token-kai", "1756400000",
                                                            "n6", ""),
                 "timestamp": "1756400000", "nonce": "n6"}
        predicate = channelsModule.inboundCredentialPredicate("wecom", plain.encode(), query, {})
        _check(predicate is not None and predicate(kaiW) is True and predicate(defW) is False,
               "企微的签名只对签名者自己的 callback token 成立（谓词读的是实例凭据）")
        # `handle_callback` 把事件调度到 `connect()` 捕到的主循环（`wecom.py:164`）——本支不连真平台
        # 连接，就按同一形状给一只**真在跑的循环**；不然"没投递"读的是探针的洞而不是代码的洞。
        loopW = asyncio.new_event_loop()
        threading.Thread(target=loopW.run_forever, daemon=True).start()
        kaiW._main_loop = defW._main_loop = loopW

        def _waitWecom(bucket):
            for _ in range(100):
                if any(m.channel_type == "wecom" and m.metadata.get("agent_id") == bucket
                       for m in delivered):
                    return True
                time.sleep(0.02)
            return False

        url = (WEBHOOK.format("wecom") + "?msg_signature=" + query["msg_signature"]
               + "&timestamp=" + query["timestamp"] + "&nonce=" + query["nonce"])
        delivered.clear()
        r = client.post(url, content=plain.encode())
        _check(r.status_code == 200 and _waitWecom("kai"),
               f"kai 自己凭据签的明文回调 ⇒ HTTP={r.status_code}、进门归属 "
               f"{[m.metadata.get('agent_id') for m in delivered]}")

        forgedSig = _wecom_callback_signature("tok-nobody-32", query["timestamp"],
                                              query["nonce"], "")
        url2 = (WEBHOOK.format("wecom") + "?msg_signature=" + forgedSig
                + "&timestamp=" + query["timestamp"] + "&nonce=" + query["nonce"])
        delivered.clear()
        r2 = client.post(url2, content=plain.encode())
        _check(r2.status_code in (403, 404) and not delivered,
               f"谁的凭据都不是 ⇒ HTTP={r2.status_code}、投递 {len(delivered)} 条（不许落到 default）")
        loopW.call_soon_threadsafe(loopW.stop)

        print("\n⑦ 收尾")
        for channelType, agentId in (("feishu", "kai"), ("dingtalk", "kai"),
                                     ("dingtalk", "yi_ling"), ("wecom", "kai"), ("wecom", "default")):
            mgr.unregister_adapter(channelType, agent_id=agentId)
        mgr._dispatch_message = originalDispatch
        _check(not mgr.list_adapters(), f"临时实例摘净（残留 {sorted(mgr.list_adapters())}）")

    print()
    print("  边界：签名/令牌由仓内官方公式本地自算，不证与真平台逐字节互操作；"
          "不连 broker/平台、不开外网、不起 agent、不花模型配额。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
