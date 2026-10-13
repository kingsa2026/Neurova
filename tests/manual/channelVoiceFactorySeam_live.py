# -*- coding: utf-8 -*-
"""§6-180 活体自证：voice 渠道从"平行死装配"收进唯一工厂路之后，真启动装配得到的东西。

链路上真跑的东西：真 `create_app()` + 真 lifespan（含 `bootstrap_channel_adapters` 那次装配）
+ 真 HTTP 端点。持久化配置用**生产那三个存取函数**写（`_load_store` / `_agent_map` / `_save_store`，
即 `POST /channel-configs` 端点自己在 `channel_config.py:665-676` 用的那三个），不在脚本里另拼一份路径。

五段读数：
① 启动只注册一次，且那份适配器带的是**我存进去的凭据**——这条同时否掉两种假状：
   平行装配还在（它会再注册一次，且凭据恒空）、工厂没建出来（注册数为 0）；
② 真 webhook 端点对 voice 仍回 400 且点名 unsupported —— 把"本批刻意没接那一支"钉成读数，
   而不是让下一批读代码时以为已经通了；
③ 出站诚实：未连接时 `send_message` 回 None，不回假 call_id；
④ `connect()` 在 twilio 未安装时空降 False 且不发任何外部请求（可选依赖 fail-soft 那条款的实例）；
⑤ [OBSERVE] 只取证不判成败：同一张分派链里 feishu/dingtalk 两支不做验签——本批不动它，
   但把它记成待裁项的证据要拿实。**这段故意不让消息进回合**：事件回调换成 recorder，
   所以不会起 agent、不会调模型、不花服务商额度。

边界：全程 127.0.0.1 进程内 TestClient，不开外网；数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。
"""

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
AGENT = "default"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _observe(label: str, detail: str) -> None:
    print(f"  [OBSERVE] {label}: {detail}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    # ① 用生产的存取函数落一条 voice 配置（端点自己就这三个函数）
    from neurova.api.endpoints import channel_config as cc

    store = cc._load_store()
    entry = {
        "channel_type": "voice",
        "enabled": True,
        "app_id": "AC_live_account_sid",
        "app_secret": "live_auth_token",
        "extra": {"from_number": "+15550100"},
    }
    cc._agent_map(store, AGENT)["voice"] = entry
    cc._save_store(store)
    print("\n① 启动装配：只注册一次，且带的是持久化配置里那份凭据")

    registered: list = []
    from neurova.channels.manager import ChannelManager, get_channel_manager

    realRegister = ChannelManager.register_adapter

    def _spy(self, adapter, *args, **kwargs):
        ctype = getattr(adapter.config, "channel_type", None)
        aid = kwargs.get("agent_id") or (args[0] if args else "default")
        registered.append((aid, ctype, adapter.config.app_id, adapter))
        return realRegister(self, adapter, *args, **kwargs)

    ChannelManager.register_adapter = _spy
    try:
        from fastapi.testclient import TestClient

        from neurova.api.app import create_app

        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            # 校准一条必然存在的路由，确认"地址对不对"不是靠猜：渠道路由挂在
            # `/api/v1/channel-adapters`（`endpoints/__init__.py:241` + `:345` 的 /api/v1 层），
            # 我第一版按 `/api/v1/channels/...` 猜路径，读到的是路由表级 404，看着像"没接"。
            _calibrate = client.get("/api/v1/status")
            _check(_calibrate.status_code == 200, f"路由表校准 /api/v1/status → {_calibrate.status_code}")

            # 启动装配是后台任务（`app.py:783 _schedule_channel_bootstrap` → create_task），
            # 所以按谓词等它落账，而不是猜一个 sleep；顺带发几次请求把那个循环推着走。
            deadline = time.time() + 60
            while time.time() < deadline and not any(r[1] == "voice" for r in registered):
                client.get("/api/v1/status")
                time.sleep(0.2)
            voiceRegs = [r for r in registered if r[1] == "voice"]
            _check(len(voiceRegs) == 1,
                   f"voice 注册次数 == 1（实得 {len(voiceRegs)}；>1 说明平行装配还在）")
            if voiceRegs:
                aid, _ct, app_id, adapter = voiceRegs[0]
                _check(app_id == "AC_live_account_sid",
                       f"注册的是工厂从持久化配置建出的那份（app_id={app_id!r}）——"
                       "平行装配那条读的是无人写入的键，凭据恒空")
                _check(aid == AGENT, f"按 (agent,渠道) 复合键注册（agent={aid!r}）")
                _check(adapter.config.extra.get("from_number") == "+15550100",
                       "出振号从配置落到适配器字段")

            # ② 真端点：voice 的 webhook 分派本批刻意没接，必须是看得见的 400
            r = client.post("/api/v1/channel-adapters/voice/webhook",
                            data={"CallSid": "CA_live_1", "From": "+15550100",
                                  "SpeechResult": "明天天气怎么样", "CallStatus": "completed"})
            _check(r.status_code == 400,
                   f"POST /channels/voice/webhook 仍回 400（实得 {r.status_code}）——"
                   "本批没接那一支，读数要说出来而不是沉默")
            _check("Unsupported webhook" in (r.text or ""),
                   f"400 的 detail 点名是分派链不支持而不是别的错：{r.text[:90]!r}")

            # ④ connect 在 twilio 缺失时 fail-soft 且不开外网
            adapter = get_channel_manager().get_adapter("voice", agent_id=AGENT)
            connected = asyncio.run(adapter.connect()) if adapter else None
            _check(adapter is not None and connected is False,
                   f"未装 twilio 时 connect() 诚实降为 False（实得 {connected!r}）")

            # ③ 出站诚实：未连接不得回假 sid
            sid = asyncio.run(adapter.send_message("+15550100", "hello", message_type="call"))
            _check(sid is None, f"未连接时 send_message 回 None（实得 {sid!r}）")

            # ⑤ [OBSERVE] feishu/dingtalk 两支的验签实状（不让消息进回合）
            _observeFeishuUnverified(client)
    finally:
        ChannelManager.register_adapter = realRegister

    print()
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for f in failures:
            print("  - " + f)
        return 1
    print("活体全过")
    return 0


def _observeFeishuUnverified(client) -> None:
    """取证：伪造一条无验签的飞书 webhook，看它会不会被拼成 ChannelMessage。

    事件回调换成 recorder —— 不进 manager、不起 agent、不调模型。
    """
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import get_channel_manager

    seen: list = []
    manager = get_channel_manager()
    probe = FeishuAdapter(ChannelConfig(
        channel_type="feishu", app_id="cli_probe", app_secret="sec_probe"))

    async def _recorder(eventType, message):
        seen.append((eventType, message))

    prevCallback = getattr(probe, "_event_callback", None)
    prevGetAdapter = type(manager).get_adapter
    try:
        probe._event_callback = _recorder
        # 只让端点拿到这台探针适配器（不动真注册表，避免给后面的读数留残留）
        type(manager).get_adapter = lambda self, channel_type, agent_id="default": (
            probe if channel_type == "feishu" else prevGetAdapter(self, channel_type, agent_id))
        r = client.post("/api/v1/channel-adapters/feishu/webhook", json={
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"user_id": "ou_FORGED_by_attacker"}},
                "message": {"message_id": "om_probe", "chat_id": "oc_probe",
                            "message_type": "text", "content": "{\"text\":\"冒充\"}"},
            },
        })
        _observe("飞书 webhook 无验签路径",
                 f"HTTP={r.status_code}，收到事件 {len(seen)} 条，"
                 + (f"sender_id={seen[0][1].sender_id!r} 直接取自请求体字段" if seen else "没有任何入站事件"))
        if seen:
            _observe("该路径的 message_type/content 是否也来自请求体",
                     f"message_type={seen[0][1].message_type!r} content={seen[0][1].content!r}")
    finally:
        probe._event_callback = prevCallback
        type(manager).get_adapter = prevGetAdapter


if __name__ == "__main__":
    sys.exit(main())
