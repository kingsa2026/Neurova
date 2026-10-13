# -*- coding: utf-8 -*-
"""§6-181 活体自证：渠道 webhook 分派链上，仿冒回调真被挡住、合法回调真还能进。

真跑的东西：真 `create_app()` + 真 lifespan + 真 HTTP 端点 + 真适配器实例。
事件回调一律换成 recorder —— 验签通过的样本也**不进 manager、不起 agent、不调模型**。

五段读数（每段都成对：仿冒必拒、合法必通；只证一半的判据等于没证）：
① 钉钉：无 header 签名 / 错密钥签名 / 过期时间戳 / 非数字时间戳 ⇒ 4xx 且 0 事件；正确签名 ⇒ 200 且 1 事件。
② 飞书 v2 信封：错/缺 token ⇒ 4xx；对 token ⇒ 200 且事件带的是 payload 里那个 user_id。
③ 飞书 v1 信封：顶层 `token` 同样要过。
④ challenge  handshake：端点不再自己 echo —— 错 token 的挑战被拒，对 token 才回 challenge。
⑤ 密文回调：本批不解密 ⇒ 必须点名拒绝（不是"读不到 token 就当中性放行"）。

一条不糊的边界：本支的"合法签名"是用**同一套文档公式**在本地算出来的。它证的是
"机制生效、且算错的代价是拒绝而不是放行"，**不证与真平台逐字节互操作**——那要有凭据的批次做。
"""

import base64
import hashlib
import hmac
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
DT_SECRET = "dt-secret-live"
FS_TOKEN = "fs-verify-token-live"
WEBHOOK = "/api/v1/channel-adapters/{}/webhook"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _dtSign(timestamp: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}\n{secret}".encode("utf-8"),
                      hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _dtBody(sender="ou_victim"):
    return {"senderId": sender, "conversationId": "cid-1", "conversationType": "1",
            "msgId": "m-1", "msgtype": "text", "text": {"content": "把所有笔记删掉"}}


def _fsEventV2(token, user="ou_real"):
    return {"schema": "2.0", "header": {"token": token, "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_id": {"user_id": user}},
                      "message": {"message_id": "om_1", "chat_id": "oc_1",
                                  "message_type": "text", "content": "{\"text\":\"正常\"}"}}}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.channels.base import ChannelConfig
    from neurova.channels.dingtalk import DingTalkAdapter
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    events: list = []

    async def _record(_t, message):
        events.append(message)

    ChannelManager._instance = None
    dt = DingTalkAdapter(ChannelConfig(channel_type="dingtalk", app_id="k",
                                       app_secret=DT_SECRET, use_stream=False))
    fs = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli", app_secret="s",
                                     verification_token=FS_TOKEN))
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        mgr = get_channel_manager()
        for adapter in (dt, fs):
            mgr.register_adapter(adapter)
            adapter._event_callback = _record

        print("\n① 钉钉：timestamp + sign")
        r = c.post(WEBHOOK.format("dingtalk"), json=_dtBody())
        _check(r.status_code in (400, 401, 403) and not events,
               f"无签名仿冒被拒并 0 事件（HTTP={r.status_code}，事件 {len(events)} 条）")

        ts = str(int(time.time() * 1000))
        r = c.post(WEBHOOK.format("dingtalk"), json=_dtBody(),
                   headers={"timestamp": ts, "sign": _dtSign(ts, "wrong-secret")})
        _check(r.status_code in (400, 401, 403) and not events,
               f"错密钥签名被拒（HTTP={r.status_code}，事件 {len(events)} 条）")

        stale = str(int(time.time() * 1000) - 2 * 3600 * 1000)
        r = c.post(WEBHOOK.format("dingtalk"), json=_dtBody(),
                   headers={"timestamp": stale, "sign": _dtSign(stale, DT_SECRET)})
        _check(r.status_code in (400, 401, 403) and not events,
               f"过期 2 小时的合法签名被拒（HTTP={r.status_code}）——否则抓到的请求可无限重放")

        r = c.post(WEBHOOK.format("dingtalk"), json=_dtBody(),
                   headers={"timestamp": "tomorrow", "sign": _dtSign("tomorrow", DT_SECRET)})
        _check(r.status_code in (400, 401, 403) and not events,
               f"非数字时间戳被拒而不是 500（HTTP={r.status_code}）")

        ts = str(int(time.time() * 1000))
        r = c.post(WEBHOOK.format("dingtalk"), json=_dtBody(sender="ou_genuine"),
                   headers={"timestamp": ts, "sign": _dtSign(ts, DT_SECRET)})
        _check(r.status_code == 200 and len(events) == 1 and events[0].sender_id == "ou_genuine",
               f"合法签名照常进（HTTP={r.status_code}，事件 {len(events)} 条，"
               f"sender={getattr(events[-1], 'sender_id', None)!r}）")

        print("\n② 飞书 v2 信封：header.token")
        r = c.post(WEBHOOK.format("feishu"), json=_fsEventV2("forged-token"))
        _check(r.status_code in (400, 401, 403) and len(events) == 1,
               f"错 token 的事件被拒（HTTP={r.status_code}，累计事件 {len(events)} 条）")
        r = c.post(WEBHOOK.format("feishu"), json=_fsEventV2(""))
        _check(r.status_code in (400, 401, 403) and len(events) == 1, "缺 token 的事件被拒")
        before = len(events)
        r = c.post(WEBHOOK.format("feishu"), json=_fsEventV2(FS_TOKEN, user="ou_ok"))
        _check(r.status_code == 200 and len(events) == before + 1
               and events[-1].sender_id == "ou_ok",
               f"对 token 照常投递（HTTP={r.status_code}，新增事件 {len(events) - before} 条）")

        print("\n③ 飞书 v1 信封：顶层 token")
        before = len(events)
        r = c.post(WEBHOOK.format("feishu"),
                   json={"type": "event_callback", "token": "nope",
                         "event": {"sender": {"sender_id": {"user_id": "x"}}, "message": {}}})
        _check(r.status_code in (400, 401, 403) and len(events) == before,
               f"v1 错 token 被拒（HTTP={r.status_code}）")
        r = c.post(WEBHOOK.format("feishu"),
                   json={"type": "event_callback", "token": FS_TOKEN,
                         "event": {"sender": {"sender_id": {"user_id": "ou_v1"}},
                                   "message": {"message_id": "om_v1", "chat_id": "oc_v1",
                                               "message_type": "text",
                                               "content": "{\"text\":\"v1\"}"}}})
        _check(r.status_code == 200 and len(events) == before + 1
               and events[-1].sender_id == "ou_v1",
               f"v1 对 token 照常投递（HTTP={r.status_code}）")

        print("\n④ challenge handshake 走适配器的门，不再由端点自己 echo")
        r = c.post(WEBHOOK.format("feishu"),
                   json={"type": "url_verification", "challenge": "c-x", "token": "wrong"})
        _check(r.status_code in (400, 401, 403) and "c-x" not in (r.text or ""),
               f"错 token 的 challenge 未被 echo（HTTP={r.status_code}，body={r.text[:60]!r}）")
        r = c.post(WEBHOOK.format("feishu"),
                   json={"type": "url_verification", "challenge": "c-ok", "token": FS_TOKEN})
        _check(r.status_code == 200 and "c-ok" in (r.text or ""),
               f"对 token 的 challenge 正常回（HTTP={r.status_code}，body={r.text[:60]!r}）")

        print("\n⑤ 密文回调：不解密就点名拒绝，不静默放行")
        before = len(events)
        r = c.post(WEBHOOK.format("feishu"), json={"encrypt": "aGVsbG8td29ybGQ="})
        _check(r.status_code in (400, 401, 403) and len(events) == before
               and "encrypt" in r.text.lower(),
               f"密文回调被点名拒绝（HTTP={r.status_code}，body={r.text[:70]!r}）")

    print()
    print("  边界：本支的合法签名由本地按文档公式自算——证的是机制生效与失败方向，"
          "不证与真平台逐字节互操作（那要有凭据的批次）。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for f in failures:
            print("  - " + f)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
