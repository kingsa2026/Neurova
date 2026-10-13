# -*- coding: utf-8 -*-
"""Twilio 语音渠道的三条接缝：收进唯一工厂路，并退掉那条平行死装配（§6-180 批 23）。

复核实状（每条都自己命中过，行号是本会话现读）：

- **平行装配**：`neurova/api/app.py:1014-1033`（在 `_on_startup()` 里，def 在 `:839`）自己 new 一个
  `ChannelConfig` 并 `register_adapter` 进 ChannelManager，读的是 `app_state.config` 里四个键
  `voice_enabled`（`:1021`）/ `twilio_account_sid`（`:1022`）/ `twilio_auth_token`（`:1023`）/
  `twilio_from_number`（`:1025`）。而这四个键**全仓零写入点**：`app_state.config` 唯一的赋值是
  `app.py:1394 _app_state.config = config or {}`，三个真入口 `start_server.py:130`、
  `app.py:1523`、`app.py:1548` 全是 `create_app()` 不带 config ⇒ 生产里恒 `enabled=False`、凭据恒空，
  启动还照注册一个用不了的适配器。其余 13 个渠道走的都是 `channel_config.py:948 _create_adapter`
  + 持久化配置那一条路——**同一件事两份做法**，按教义第 6 条收口到工厂那一份；按 §2，
  只读不写的配置本身就是断点。
- **工厂缺支**：`_create_adapter` 分支表（`:953 feishu / :963 dingtalk / :971 wecom / :991 xiaoyi /
  :1002 discord / :1009 telegram / :1016 qq / :1027 qqbot / :1037 wechat / :1070 sip / :1081 mqtt /
  :1093 qclaw`）**没有 voice**，落到 `:1103 else` → `:1116` 只 warn "config saved only" 返 None ⇒
  存了 voice 配置也建不出适配器。（已核：保存路没有渠道类型白名单校验，补一支即通。）
- **webhook 分派缺支**：`api/endpoints/channels.py:191-198` 只有 feishu/dingtalk/wecom 三支，
  其余 `:198` 抛 400 ⇒ `voice.py:121 handle_webhook` 全仓零生产调用者。**本批刻意不接这一支**，
  理由见下面"安全边界"。
- **enabled 门复算后不是缺陷**：`manager.py:565-567` 只对 `config.enabled` 为真者调 `_connect_adapter`，
  而注册与连接是分离的——`register_adapter` 不看 enabled，`get_adapter`(`:146-154`) 也不看连接态，
  `_connect_adapter:599-603` 把失败降为 warn 且不摘除实例。所以"voice 连不上"不会挡住任何入站路，
  台账把它记成第四处接缝是**比错了对象**。

安全边界（为什么本批不接 webhook 那一支，登记待裁而不是顺手接）：同一张分派链里
`_handle_feishu_webhook:230-243` 与 `_handle_dingtalk_webhook:269-282` **不做任何验签**，
直接把请求体拼成 `ChannelMessage` 后 `await adapter._emit_event(MESSAGE_RECEIVED, ...)` 投进回合，
而 `sender_id` 取自请求体（飞书 `:232`、钉钉 `:259`）——那是"未鉴权的入站面可冒充任意渠道用户驱动
agent 回合"。给 voice 再开一支就是往这个既有洞上再加一个平台面（Twilio 的 `From` 同样是请求体字段，
`voice.py:137`）。wecom 那一支有 `msg_signature` 校验（委托 `adapter.handle_callback`）是例外。
⇒ 正确顺序是先把这条分派链的验签口径一次性立起来（另批，涉及各平台签名协议形状，本仓无凭据可实验），
再谈给 voice 开支。

出站如实边界（不谎报已修）：`twilio` 既不在依赖清单也未安装（现量 `find_spec('twilio') is None`），
`VoiceAdapter.connect()` 走 `voice.py:53-55` 的 ImportError 分支或 `:44-46` 的空凭据分支返回 False，
`send_message:82-84` 未连接时返回 None——本批只把"可配置、可建出适配器"这一段接通，出站仍要
声明依赖 + 凭据 + 验签三件一起做。
"""

import ast
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
NEUROVA = REPO / "neurova"
TWILIO_CONFIG_KEYS = ("voice_enabled", "twilio_account_sid", "twilio_auth_token", "twilio_from_number")

from neurova.channels.base import ChannelConfig  # noqa: E402


def _voiceConfig() -> ChannelConfig:
    return ChannelConfig(
        channel_type="voice",
        enabled=True,
        app_id="AC22222222222222222222222222222222",
        app_secret="authTok-abc",
        extra={"from_number": "+15550100"},
    )


class TestTheFactoryBuildsIt:
    """工厂是渠道适配器的唯一出生地；voice 以前不在名单上。"""

    def testVoiceBranchReturnsTheAdapterWithRealFields(self):
        from neurova.api.endpoints.channel_config import _create_adapter
        from neurova.channels.voice import VoiceAdapter

        adapter = _create_adapter("voice", _voiceConfig())

        assert isinstance(adapter, VoiceAdapter), (
            f"工厂建不出 voice 适配器（实得 {adapter!r}）——存了配置也只落 'config saved only'")
        # 按真字段核，不按 isinstance 核：凭据落错字段的表现是"连上了但打不出电话"
        assert adapter.config.app_id == "AC22222222222222222222222222222222"
        assert adapter.config.app_secret == "authTok-abc"
        assert adapter.config.extra.get("from_number") == "+15550100"
        assert adapter.config.enabled is True

    def testUnknownTypeStillFallsBackToConfigOnly(self):
        """反向对照：不能为了过本批把 else 改成"什么都建"。"""
        from neurova.api.endpoints.channel_config import _create_adapter

        cfg = _voiceConfig()
        cfg.channel_type = "no_such_channel_type_zz"
        assert _create_adapter("no_such_channel_type_zz", cfg) is None, (
            "未知类型不该被兜底建出来——那会把拼错的渠道名静默变成实例")


class TestTheParallelAssemblyIsRetired:
    """平行路要真消失，不是文字上删了注释。"""

    def testStartupDoesNotRegisterAVoiceAdapter(self, monkeypatch):
        """读数取"启动做了什么"，不取"全局单例里有什么"。

        ChannelManager 是进程级单例、`create_app()` 又返回缓存实例（`app.py` 内），
        直接读 `get_adapter("voice")` 会被同进程里先前跑过的渠道测试留下的注册污染——
        那种读数既可能假红也可能假绿，问的不是本批这条性质。
        """
        from neurova.api import app as appModule
        from neurova.channels.manager import ChannelManager
        from neurova.channels.voice import VoiceAdapter
        from neurova.api.app import create_app

        registered: list = []
        realRegister = ChannelManager.register_adapter
        realStartup = appModule._on_startup

        def _registerSpy(self, adapter, *args, **kwargs):
            registered.append(getattr(adapter.config, "channel_type", None))
            return realRegister(self, adapter, *args, **kwargs)

        startupRan: list = []

        async def _startupSpy(state):
            startupRan.append(state)
            return await realStartup(state)

        monkeypatch.setattr(ChannelManager, "register_adapter", _registerSpy)
        monkeypatch.setattr(appModule, "_on_startup", _startupSpy)

        from fastapi.testclient import TestClient

        with TestClient(create_app(), raise_server_exceptions=False) as _c:
            pass

        assert startupRan, "启动那段根本没跑——那这条读数什么都没证"
        assert "voice" not in registered, (
            f"启动路上又平行注册了 voice（本轮注册：{registered}）——"
            "它读的那四个键全仓无写入点，生产里只会得到一个 enabled=False、凭据空的死适配器")

        # 反空转（排除型断言在功能缺失时会自动成立）：同一个 spy 必须抓得到 voice 类型的注册，
        # 否则上面那句"不在"可能只是 spy 没接上。收完读数立刻摘掉，不给后面的测试留残留注册
        # （ChannelManager 是进程级单例，留下就是给别人造随机红）。
        from neurova.channels.manager import get_channel_manager

        manager = get_channel_manager()
        try:
            manager.register_adapter(VoiceAdapter(_voiceConfig()))
            assert "voice" in registered, f"spy 没收到显式注册的 voice（{registered}）——判据是空的"
        finally:
            manager.unregister_adapter("voice")

    def testRetiredKeysHaveNoReadersLeftInProduction(self):
        """只读不写的配置是断点；退役后要一格钉住"别留半句读它"。"""
        offenders = self._keySitesInTree()
        assert offenders == [], (
            f"这四个键还有人读（写入点从来不存在）：{offenders}")

    @staticmethod
    def _keySites(src: str) -> list:
        """只数**键位**用法：`x.get("voice_enabled")`、`x["voice_enabled"]`、字典字面量的键位。
        取值位置（`{"type": "voice_enabled"}` 这类）不算——按字符串包含扫会假红。"""
        tree = ast.parse(src)
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and node.slice.value in TWILIO_CONFIG_KEYS:
                hits.append(node.lineno)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in {"get", "pop", "setdefault"}:
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value in TWILIO_CONFIG_KEYS:
                    hits.append(node.lineno)
            elif isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value in TWILIO_CONFIG_KEYS:
                        hits.append(node.lineno)
        return hits

    def _keySitesInTree(self) -> list:
        bad = []
        for path in sorted(NEUROVA.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            sites = self._keySites(path.read_text(encoding="utf-8", errors="replace"))
            if sites:
                bad.append(f"{path.relative_to(REPO).as_posix()}:{sites}")
        return bad

    def testDetectorHasTeeth(self):
        """自证：三种键位都要被抓；取值形不得被抓。"""
        sample = (
            'a = cfg.get("voice_enabled")\n'           # 1 读：.get 键实参
            'b = {}\n'                                 # 2 与本键无关，占一行让行号不是连号
            'b["twilio_auth_token"] = 1\n'             # 3 写：下标键
            'c = {"twilio_from_number": ""}\n'         # 4 写：字典字面量的键位
            'd = {"type": "voice_enabled"}\n'          # 5 取值位置——不算命中
        )
        assert self._keySites(sample) == [1, 3, 4], "键位/取值没分干净"


class TestOutboundStaysHonestlyUnwired:
    """本批没修出站。这几格钉住"失败必须是看得见的失败"，防下一个人把没验签没依赖写成成功。"""

    def testConnectWithoutCredentialsFailsSoft(self):
        from neurova.channels.voice import VoiceAdapter

        cfg = _voiceConfig()
        cfg.app_id = ""
        cfg.app_secret = ""
        adapter = VoiceAdapter(cfg)

        result = subprocess.run(
            [sys.executable, "-c", "import importlib.util,sys;"
             "sys.exit(0 if importlib.util.find_spec('twilio') else 1)"],
            capture_output=True, timeout=60)
        twilioInstalled = result.returncode == 0

        import asyncio

        connected = asyncio.run(adapter.connect())
        if not twilioInstalled:
            assert connected is False, "twilio 未安装却报连上了＝谎报"
        else:  # pragma: no cover - 本机未装 twilio，这条支路为装了的机器保留
            assert connected is False, "空凭据却连上了＝没把凭据门当回事"
        assert adapter._client is None and adapter._connected is False

    def testSendWithoutConnectionReturnsNoneNotAFakeSid(self):
        import asyncio

        from neurova.channels.voice import VoiceAdapter

        adapter = VoiceAdapter(_voiceConfig())
        sid = asyncio.run(adapter.send_message("+15550100", "hello", message_type="call"))

        assert sid is None, f"未连接却交回了 call_id（{sid!r}）——上游会把它当真通话记账"
