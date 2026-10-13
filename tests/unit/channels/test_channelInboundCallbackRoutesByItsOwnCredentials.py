# -*- coding: utf-8 -*-
"""入站回调落到哪一只实例，由这条回调自己的凭据说（§6-197 批 32）。

设计本意是**每个 agent 各有自己专属的渠道配置**：实例表主键 `(agent_id, channel_type)`、保存路径
按 agent 取实例、启动装配逐 agent 注册（§6-189/§6-190 已把这几段对齐）。剩的缺口只在入站落点：
平台回调 URL 只带 `channel_type`，而 §6-189 的裁决是"default 优先 ⇒ 唯一 ⇒ 歧义拒"。

**这条其实不必等 URL 改造**——三平台的验签面用的都是**实例自己的凭据**（现量）：

- 飞书 `verify_event_token()` 比的是该适配器 `config.verification_token`（`feishu.py:618`）；
- 钉钉 `verify_callback_headers()` 的 HMAC key 是该实例的 `config.app_secret`（`dingtalk.py:477`）；
- 企业微信 `msg_signature = SHA1(sort(token, ts, nonce, Encrypt))` 用的是该实例的
  `_callback_token`（`wecom.py:104`），且回调体里 `ToUserName` 就是 corpid。

⇒ 回调体自带"这条是给哪只 bot 的"的证据，只是解析层以前没去问。本批把问出来变成裁决依据：
**≥2 只候选时逐只试验签，恰好一只通过 ⇒ 用它**（default 不再插队）；0 只 ⇒ 拒并点名"没有一只验下"；
≥2 只 ⇒ 拒并点名"这几只共用同一份凭据"（那正是 `/conflicts/check` 在报的配置冲突，不是路由问题）。
单只候选、或该类型没有验签面 ⇒ 语义与 §6-189 一字不变（`authenticator=None` 那条路原样保留，
所以 §6-189 那档判据不需要改判）。

**行为变更一条，写在票面上**：两只实例故意共用同一份凭据时，此前静默进 default，现在**拒并点名**。
配置错误该被看见，不该被"default 优先"掩盖成正常投递。

判据三组：
① 真端点 + 真两只 `FeishuAdapter`（各一份 verification_token）：kai 的 token ⇒ 只进 kai 那只、
   default 的 token ⇒ 仍进 default（对照）、共用凭据 ⇒ 拒且点名两个 agent、谁的都不匹配 ⇒ 拒、
   单只候选时不依赖谓词且**投递前那道验签门照旧拦错 token**（路由与投递两道门都在）。
② 解析层契约：谓词必须**每只都问**（不许先给 default 特权）、谓词自己抛异常算不匹配而不是把分派带进 500、
   单参调用（§6-189 的原形状）三条语义逐字不变。
③ 端点的凭据取法与 handler 同源（不在两处各写一遍）：飞书令牌位置、钉钉 header、企微 query 三元组，
   外加"无验签面的类型 ⇒ 不给谓词"。

边界：不开外网、不连真平台、不起 agent、不花模型配额——投递面（`_dispatch_message`）换记录器，
适配器的 `_emit_event` 包一层"记账后照常放行"的壳；签名样本由仓内公式本地自算，
**不证与真平台逐字节互操作**（§6-181 同一边界）。
"""

import ast
import base64
import hashlib
import hmac
import json
import pathlib
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
CHANNELS_PY = REPO / "neurova" / "api" / "endpoints" / "channels.py"
CHANNELS_SRC = CHANNELS_PY.read_text(encoding="utf-8")
WECOM_SRC = (REPO / "neurova" / "channels" / "wecom.py").read_text(encoding="utf-8")
WEBHOOK = "/api/v1/channel-adapters/{}/webhook"


def _feishuEvent(token: str, user: str) -> bytes:
    return json.dumps({
        "schema": "2.0", "header": {"token": token, "event_type": "im.message.receive_v1"},
        "event": {"sender": {"sender_id": {"user_id": user}},
                  "message": {"message_id": f"om_{user}", "chat_id": "oc_1",
                              "message_type": "text", "content": "{\"text\":\"进哪只\"}"}}},
    ).encode()


def _dtSign(ts: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _callsInChannelTypes(src: str, needle: str) -> list:
    """本文件里读某字段/调某名字的落点行号（防"同一取法写两遍"）。"""
    hits = []
    for i, line in enumerate(src.splitlines(), 1):
        if needle in line and not line.strip().startswith("#"):
            hits.append(i)
    return hits


@pytest.fixture()
def twoFeishuBots():
    """真 app + 真 lifespan + 真端点 + 真两只飞书实例；投递面换记录器，投递前那道门原样。"""
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    from neurova.api.app import create_app
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    isolatedDataRoot()
    ChannelManager._instance = None
    delivered = []
    emitted = {}

    def _make(agentId, token):
        adapter = FeishuAdapter(ChannelConfig(
            channel_type="feishu", app_id=f"cli_{agentId}", app_secret="sec",
            verification_token=token, use_stream=False))
        original = adapter._emit_event

        async def _spy(eventType, message):
            emitted.setdefault(agentId, []).append(message)
            return await original(eventType, message)

        adapter._emit_event = _spy
        return adapter

    app = create_app()
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()
        mgr.ingress_queue = False
        originalDispatch = mgr._dispatch_message

        async def _recordDispatch(message):
            delivered.append(message)

        mgr._dispatch_message = _recordDispatch
        mgr.register_adapter(_make("default", "tok-default-32"), agent_id="default")
        mgr.register_adapter(_make("kai", "tok-kai-32"), agent_id="kai")
        try:
            yield client, mgr, emitted, delivered
        finally:
            mgr._dispatch_message = originalDispatch
            for agentId in ("kai", "default"):
                mgr.unregister_adapter("feishu", agent_id=agentId)
    ChannelManager._instance = None


class TestCredentialsChooseWhichInstanceGetsTheCallback:
    def testKaiTokenLandsOnKaiOnly(self, twoFeishuBots):
        client, _mgr, emitted, delivered = twoFeishuBots
        r = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-kai-32", "ou_kai_person"))

        assert r.status_code == 200, f"kai 自己的凭据发的回调被拒了：HTTP={r.status_code} {r.text[:90]}"
        assert sorted(emitted) == ["kai"], f"被投递的实例是 {sorted(emitted)}（default 那只不该收到）"
        assert len(emitted.get("kai", [])) == 1 and len(delivered) == 1
        assert delivered[0].sender_id == "ou_kai_person", f"发送者：{delivered[0].sender_id!r}"
        assert delivered[0].metadata.get("agent_id") == "kai", (
            f"进门的 agent 归属不是 kai：{delivered[0].metadata}")

    def testDefaultTokenStillLandsOnDefault(self, twoFeishuBots):
        """对照：既有部署（default 名下那只 app）行为一字不变——收紧歧义不许把这条也改坏。"""
        client, _mgr, emitted, delivered = twoFeishuBots
        r = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-default-32", "ou_normal"))

        assert r.status_code == 200, f"HTTP={r.status_code} {r.text[:90]}"
        assert sorted(emitted) == ["default"] and delivered[0].metadata.get("agent_id") == "default", \
            f"实得 {sorted(emitted)} / {[m.metadata.get('agent_id') for m in delivered]}"

    def testSharedCredentialsAreRefusedAndNamed(self, twoFeishuBots):
        """两只故意共用同一份 token ⇒ 这不是路由问题，是配置冲突：拒并点名，不再静默进 default。"""
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.manager import get_channel_manager

        client, mgr, emitted, _delivered = twoFeishuBots
        mgr.unregister_adapter("feishu", agent_id="kai")
        twin = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_yi", app_secret="sec",
                                           verification_token="tok-default-32", use_stream=False))
        original = twin._emit_event

        async def _spy(eventType, message):
            emitted.setdefault("yi", []).append(message)
            return await original(eventType, message)

        twin._emit_event = _spy
        mgr.register_adapter(twin, agent_id="yi")
        emitted.clear()

        r = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-default-32", "ou_x"))

        assert r.status_code in (403, 404, 409), f"共用凭据的歧义拿到了 {r.status_code}"
        assert not emitted, f"却仍然投出去了（{ {k: len(v) for k, v in emitted.items()} }）"
        detail = (r.json() or {}).get("detail") or ""
        assert "default" in detail and "yi" in detail, f"文案没点名是哪两只冲突：{detail!r}"

    def testNoInstanceMatchesIsRefused(self, twoFeishuBots):
        client, _mgr, emitted, _delivered = twoFeishuBots
        r = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-attacker-forged", "ou_victim"))

        assert r.status_code in (401, 403, 404), f"陌生凭据拿到了 {r.status_code}"
        assert not emitted, f"陌生凭据却投出去了（{ {k: len(v) for k, v in emitted.items()} }）"
        detail = (r.json() or {}).get("detail") or ""
        assert "none" in detail.lower() or "没有一只" in detail, f"文案没说是'没人验下'：{detail!r}"

    def testSingleCandidatePathDoesNotNeedThePredicate(self, twoFeishuBots):
        """一只候选时按 §6-189 原样命中；但**投递前那道门照旧拦错 token**——两道门都得在。"""
        from neurova.channels.manager import get_channel_manager

        client, mgr, emitted, _delivered = twoFeishuBots
        mgr.unregister_adapter("feishu", agent_id="default")
        emitted.clear()

        ok = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-kai-32", "ou_only"))
        bad = client.post(WEBHOOK.format("feishu"), content=_feishuEvent("tok-nope", "ou_forge"))

        assert ok.status_code == 200 and len(emitted.get("kai", [])) == 1, \
            f"单只候选时唯一格裁决失效：HTTP={ok.status_code} 事件={ {k: len(v) for k, v in emitted.items()} }"
        assert bad.status_code in (401, 403), f"错 token 越过了投递门：{bad.status_code}"
        assert len(emitted.get("kai", [])) == 1, "错 token 那条也被投了"


class TestResolverContractWithThePredicate:
    def _mgrWith(self, agentsTokens):
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.manager import ChannelManager, get_channel_manager

        ChannelManager._instance = None
        mgr = get_channel_manager()
        for agentId, token in agentsTokens:
            mgr.register_adapter(FeishuAdapter(ChannelConfig(
                channel_type="feishu", app_id=f"cli_{agentId}", app_secret="s",
                verification_token=token, use_stream=False)), agent_id=agentId)
        return mgr

    def testEveryCandidateIsAskedBeforeDefaultWins(self):
        """default 不许插队：≥2 候选时必须逐只问过凭据（问的次数＝候选数）。"""
        mgr = self._mgrWith([("default", "tok-a"), ("kai", "tok-b")])
        asked = []

        def _auth(adapter):
            asked.append(adapter.config.app_id)
            return adapter.config.verification_token == "tok-b"

        adapter, reason = mgr.resolveInboundAdapter("feishu", authenticator=_auth)

        assert sorted(asked) == ["cli_default", "cli_kai"], f"被问过的是 {asked}（default 插队或漏问）"
        assert adapter is not None and adapter.config.app_id == "cli_kai", f"选中的是 {adapter!r} / {reason}"

    def testPredicateRaisingCountsAsNoMatchNotAsCrash(self):
        """一只适配器的读法抛了（畸形回调是外部边界）⇒ 算不匹配并点名，不许把整条分派带进 500。"""
        mgr = self._mgrWith([("kai", "tok-b"), ("yi", "tok-c")])
        boom = True

        def _auth(adapter):
            nonlocal boom
            if boom:
                boom = False
                raise TypeError("malformed callback body")
            return adapter.config.verification_token == "tok-c"

        adapter, reason = mgr.resolveInboundAdapter("feishu", authenticator=_auth)
        assert adapter is not None and adapter.config.verification_token == "tok-c", f"{adapter!r} / {reason}"

        boom = True
        none, reason2 = mgr.resolveInboundAdapter(
            "feishu", authenticator=lambda _a: (_ for _ in ()).throw(ValueError("nope")))
        assert none is None and "nope" not in reason2 and reason2, f"全抛时的读数：{none!r} / {reason2!r}"

    def testSingleArgumentCallKeepsThe6_189Semantics(self):
        """单参（§6-189 原形状）三条语义逐字不变——新形不许偷偷改掉旧语义。"""
        mgr = self._mgrWith([("default", "tok-a"), ("kai", "tok-b")])
        adapter, reason = mgr.resolveInboundAdapter("feishu")
        assert adapter is not None and adapter.config.app_id == "cli_default", f"default 优先丢了：{reason}"

        mgr.unregister_adapter("feishu", agent_id="default")
        only, reason2 = mgr.resolveInboundAdapter("feishu")
        assert only is not None and only.config.app_id == "cli_kai", f"唯一格裁决变了：{reason2}"
        mgr.register_adapter(self._adapter("yi", "tok-c"), agent_id="yi")
        none, reason3 = mgr.resolveInboundAdapter("feishu")
        assert none is None and "multiple agents" in reason3, f"歧义文案不再点名：{reason3!r}"
        assert mgr.resolveInboundAdapter("mqtt")[0] is None
        assert "not found" in mgr.resolveInboundAdapter("mqtt")[1]

    def _adapter(self, agentId, token):
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter

        return FeishuAdapter(ChannelConfig(channel_type="feishu", app_id=f"cli_{agentId}",
                                           app_secret="s", verification_token=token,
                                           use_stream=False))


class TestEndpointKnowsHowToAskEachPlatform:
    """凭据的**取法**只在端点一处、**比不比**只在适配器一处（教义第 6）；没有验签面的类型就不给谓词。"""

    def _factory(self):
        from neurova.api.endpoints import channels as channelsModule

        return channelsModule.inboundCredentialPredicate

    def testFeishuTokenShapeIsTakenOnce(self):
        make = self._factory()
        body = _feishuEvent("tok-v2-in-header", "u1")
        predicate = make("feishu", body, {}, {})
        assert predicate is not None, "飞书该有谓词（它有自己的 verification_token）"
        v2 = self._fakeFeishu("tok-v2-in-header")
        v1 = self._fakeFeishu("tok-v1-top-level")
        assert predicate(v2) is True and predicate(self._fakeFeishu("other")) is False

        v1body = json.dumps({"type": "event_callback", "token": "tok-v1-top-level",
                             "event": {}}).encode()
        p1 = make("feishu", v1body, {}, {})
        assert p1(v1) is True and p1(v2) is False, "两代信封的令牌位置取错了一只"
        # 同一取法不许在端点里写第二遍（谓词与 handler 共用一个函数）
        hits = _callsInChannelTypes(CHANNELS_SRC, '"header"')
        assert len(hits) == 1, f"读 header 的落点有 {len(hits)} 处（{hits}）——两代信封的取法要收在一处"

    def testDingtalkPredicateUsesItsOwnAppSecret(self):
        make = self._factory()
        ts = str(int(time.time() * 1000))
        headers = {"timestamp": ts, "sign": _dtSign(ts, "secret-kai")}
        predicate = make("dingtalk", b"{}", {}, headers)
        assert predicate is not None
        assert predicate(self._fakeDingtalk("secret-kai")) is True
        assert predicate(self._fakeDingtalk("secret-other")) is False, "换了 key 却还验过＝谓词没在比凭据"

    def testWecomPredicateUsesTheCallbackTokenTriple(self):
        """真 `WeComAdapter` + 仓内那条官方公式自己算签名（不开外网、不连平台）。"""
        from neurova.channels.base import ChannelConfig
        from neurova.channels.wecom import WeComAdapter, _wecom_callback_signature

        make = self._factory()
        query = {"msg_signature": "", "timestamp": "1756400000", "nonce": "n1"}
        encrypt = "ENC-ONLY-KAI"
        body = f"<xml><Encrypt>{encrypt}</Encrypt></xml>".encode()

        def _adapter(token):
            return WeComAdapter(ChannelConfig(channel_type="wecom", app_id="ww_" + token,
                                             app_secret="s", webhook_token=token))

        kai = _adapter("kai-token")
        other = _adapter("other-token")
        query["msg_signature"] = _wecom_callback_signature("kai-token", query["timestamp"],
                                                         query["nonce"], encrypt)
        predicate = make("wecom", body, query, {})
        assert predicate is not None, "企微该有谓词（它有自己的 callback token）"
        assert predicate(kai) is True, "自己凭据签出来的名却没验过＝谓词没在比实例的 token"
        assert predicate(other) is False, "换了 token 却还验过＝谓词根本没读实例自己的凭据"
        noSig = make("wecom", body, {"timestamp": "1756400000", "nonce": "n1"}, {})
        assert noSig is None, "连 msg_signature 都没有时谓词只能'不知道'，不许冒充'不匹配'"

    def testTypesWithoutACredentialFaceGetNoPredicate(self):
        """没有验签面的类型**不许**被塞一个恒真/恒假的谓词——那比不路由更坏。"""
        make = self._factory()
        assert make("qq", b"{}", {}, {}) is None
        assert make("mqtt", b"{}", {}, {}) is None
        assert make("feishu", b"not-json-at-all", {}, {}) is None, "读不懂的体不该由谓词乱猜"
        assert make("feishu", json.dumps({"encrypt": "x"}).encode(), {}, {}) is None, \
            "密文回调里没有可读令牌 ⇒ 谓词只能不知道，不许当成'不匹配'去掩盖真原因"

    def _fakeFeishu(self, token):
        class _F:
            config = type("C", (), {"app_id": "cli_fake"})()

            def verify_event_token(_self, tok):
                if tok != token:
                    raise ValueError("Feishu callback rejected: token mismatch")
        return _F()

    def _fakeDingtalk(self, secret):
        class _D:
            config = type("C", (), {"app_secret": secret})()

            def verify_callback_headers(_self, ts, sign):
                expect = _dtSign(ts, secret)
                if not sign or not hmac.compare_digest(expect, sign):
                    raise ValueError("DingTalk callback rejected: sign mismatch")
        return _D()

class TestWecomVerifyFaceIsOneImplementation:
    """企微的签名核对从此只有一处：`verifyCallbackSignature`（投递与路由共用它）。"""

    def testSignatureCheckExtractedAndReused(self):
        assert hasattr(__import__("neurova.channels.wecom", fromlist=["WeComAdapter"]).WeComAdapter,
                       "verifyCallbackSignature"), "企微没有独立的验签面 ⇒ 谓词只能靠复制公式"
        hits = _callsInWecom()
        assert len(hits) >= 2, f"签名公式的调用点只有 {hits}——抽取没做到（还是各写各的）"
        tree = ast.parse(WECOM_SRC)
        bodies = {n.name: n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for func in ("verifyCallbackSignature", "verify_url", "handle_callback"):
            assert func in bodies, f"少了 {func}"
        called = {f for f in ("verifyCallbackSignature", "verify_url", "handle_callback")
                  if f != "verifyCallbackSignature" and any(
                      isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "verifyCallbackSignature"
                      for c in ast.walk(bodies[f]))}
        assert {"verify_url", "handle_callback"} <= called, f"没共用到新面：{sorted(called)}"

    def testFormulaHasOneDefinition(self):
        defs = _callsInWecom(onlyDefinition=True)
        assert len(defs) == 1, f"签名公式定义了 {len(defs)} 次：{defs}"


def _callsInWecom(onlyDefinition: bool = False) -> list:
    needle = "def _wecom_callback_signature" if onlyDefinition else "_wecom_callback_signature("
    return [i for i, line in enumerate(WECOM_SRC.splitlines(), 1)
            if needle in line and not line.strip().startswith("#")]
