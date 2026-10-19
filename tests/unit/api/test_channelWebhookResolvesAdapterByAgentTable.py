# -*- coding: utf-8 -*-
"""入站回调该交给哪个适配器：实例表主键是 `(agent_id, channel_type)`，解析却只看 default（§6-189 批 28）。

复核实状（逐处自己命中）：
- **注册是全量的，解析是半边**：`manager.register_adapter(adapter, agent_id=...)` 把实例存进
  `_agent_adapters[(agent_id, channel_type)]`，启动装配 `bootstrap_channel_adapters` 就是按持久化配置
  里**每个 agent** 逐个注册的（`channel_config.py` 那个 `store["agents"]` 循环）；而
  `get_adapter(channel_type, agent_id="default")` 不传 agent 时只命中 default 那一格。
- **出站带 agent，入站不带**：`channel_router.py` 取适配器时传 `agent_id=agent_id`，
  `manager._on_channel_event` 里那两处也带（第二个位置参数的写法）。于是形状是"回得去、进不来"——
  一条只在 agent「凯蒂」名下配置的渠道，连接与回复都正常，但平台 POST 进
  `/api/v1/channel-adapters/{channel_type}/webhook` 时**找不到适配器，整条渠道不响应**，
  而文案是 `Channel 'feishu' not found`，把人引向"没配置"这个错结论。
- **更坏的一种**：同一平台同时挂在 default 与别的 agent 下 ⇒ 回调一律落到 default 那个 bot，
  消息进了别人的会话与额度（打的正是 §6-123/§6-163 那套"发送者即身份"的上游）。

修法（一处口径）：解析入站适配器收成 manager 上唯一入口 `resolveInboundAdapter(channel_type)`，
返回 `(adapter, failureReason)`——两种失败（没配 / 多 agent 同名歧义）分开点名：default 名下有就用它
（既有部署行为一字不变）；否则该类型全表**唯一**时用那一格；多格且 default 缺席时**不静默投给任意一个**。
把 agent 维度带进回调 URL 需要前端与部署面一起改，是另一次裁定，本批不假装解决，也不留静默错投。

同根因余点由本档最后一格自己数着（不在本批动手）：`channels.py` 的状态/连接/断开三个端点、
`channel_sharing.py` 的只读状态栏、以及零调用者的死面 `manager.replace_channel`。
（**后记**：其中 `channels.py` 三个端点与 `replace_channel` 已由 §6-190 收掉，那张表随之缩到一条——
 本档那句"不在本批动手"是当时的实况，不是永久裁决。）

**§6-197 的改判（本档那格"仍走 default"已被替换）**：入站回调落到哪一只，改由**这条回调自己的凭据**
裁决（三平台的验签面用的都是实例自己的 `verification_token`/`appSecret`/`callback_token`）。于是
"default 优先"降级成"没有谓词时的兜底"，而"两只共用同一份凭据"从静默进 default 变成**拒并点名**。
本档那格按新语义拆成两格：共用 ⇒ 拒；各配各的 token ⇒ 谁的进谁那只（default 不插队）。
"""

import ast
import json
import pathlib
import re

import pytest

from tests import ast_scan
from fastapi.testclient import TestClient

REPO = pathlib.Path(__file__).resolve().parents[3]
#: 扫描根单点，且必须是**模块级**：收进函数内的局部名，面自证棘轮的取数口会把这处落点
#: 解成动态值，于是那档静默掉出它的面——补了自证也是假的。
NEUROVA = REPO / "neurova"

from neurova.api.app import create_app  # noqa: E402
from neurova.channels.base import ChannelConfig  # noqa: E402
from neurova.channels.feishu import FeishuAdapter  # noqa: E402
from neurova.channels.manager import ChannelManager, get_channel_manager  # noqa: E402

WEBHOOK = "/api/v1/channel-adapters/{}/webhook"
VERIFY_TOKEN = "fs-token-b28"
CHANNELS_SRC = (REPO / "neurova" / "api" / "endpoints" / "channels.py").read_text(encoding="utf-8")


def _adapter(appTag="app", token=VERIFY_TOKEN):
    return FeishuAdapter(ChannelConfig(
        channel_type="feishu", app_id=f"cli_{appTag}", app_secret="sec",
        verification_token=token, use_stream=False))


def _eventBody(user="ou_real_b28", token=VERIFY_TOKEN):
    return {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "token": token},
        "event": {"sender": {"sender_id": {"user_id": user, "open_id": "ou_open"}},
                  "message": {"message_id": "om_1", "chat_id": "oc_1", "chat_type": "p2p",
                              "message_type": "text",
                              "content": json.dumps({"text": "在的"}), "mentions": []}},
    }


def _resolutionCallsIn(src: str, funcName: str) -> list:
    """某函数体内对"取适配器"两副面孔的调用名（`get_adapter` 是旧面、`resolveInboundAdapter` 是单源）。"""
    target = next((n for n in ast.walk(ast.parse(src))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcName),
                  None)
    assert target is not None, f"{funcName} 不在了——扫描口径失效"
    return [node.func.attr for node in ast.walk(target)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get_adapter", "resolveInboundAdapter")]


def _bareAdapterLookups(trees) -> dict:
    """数"无 agent 维度的渠道取实例"落点。trees = [(relPath, 语法树)]。

    三条口径都是被本仓的伪命中教出来的：① 只看接收者是 `manager`/`mgr`/`self` 的
    `.get_adapter(...)`——技能市场那个 `self.registry.get_adapter(market)` 是**同名异面**，
    裸按属性名扫会把它算进来；② 带 agent 的写法有两种形（`agent_id=` 关键字、第二个位置参数），
    只认关键字会把 `manager.py` 里两处合法调用误报成欠账；③ `resolveInboundAdapter` 是本批新立的
    唯一入口，不该被算成欠账。
    """
    hits = {}
    for rel, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get_adapter":
                continue
            if not (isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("manager", "mgr", "self")):
                continue
            if len(node.args) >= 2 or any(k.arg == "agent_id" for k in node.keywords):
                continue
            hits.setdefault(rel, []).append(node.lineno)
    return hits


def _neurovaTrees() -> list:
    """`[(相对路径, 语法树)]`——枚举与解析都走 `tests/ast_scan.py` 的一次性入口。

    原来这里是 `(rel, text)` + 各消费方自己 `ast.parse`：枚举走共享入口而解析自付，
    正是门禁点名的"免检通道"形状；一次性入口 `transientTree` 不留常驻语法树，
    成本与代码总量脱钩（本文件只扫一遍，不存在第二次命中）。
    """
    out = []
    for path in ast_scan.filesUnder(NEUROVA):
        try:
            out.append((ast_scan.relativeToRepo(path), ast_scan.transientTree(path)))
        except SyntaxError:
            continue
    assert len(out) > 500, (
        f"扫描面现读 {len(out)} 档（根＝{NEUROVA}，本判据的域＝生产源码）——"
        "根被改窄时这份「只有 default」的读数根本不来自代码")
    return out


@pytest.fixture()
def harness(tmp_path):
    """真 app + 真路由；每只实例各挂一个 recorder（不起 agent、不调模型、不开外网、不花配额）。"""
    ChannelManager._instance = None
    seen = {"default": [], "kai": [], "yi_ling": []}

    def _recorder(bucket):
        async def _record(_eventType, message):
            seen[bucket].append(message)
        return _record

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()

        def _register(agentId, bucket, appTag, token=VERIFY_TOKEN):
            adapter = _adapter(appTag, token)
            mgr.register_adapter(adapter, agent_id=agentId)
            adapter._event_callback = _recorder(bucket)
            return adapter

        yield client, mgr, seen, _register
    ChannelManager._instance = None


class TestNonDefaultAdapterReachesInbound:
    def testCallbackFindsTheOnlyAdapter(self, harness):
        """只在 agent「kai」名下配了这条渠道 ⇒ 回调必须进它自己，不是 404。"""
        client, mgr, seen, register = harness
        register("kai", "kai", "kai_app")

        r = client.post(WEBHOOK.format("feishu"), json=_eventBody())

        assert r.status_code == 200, (
            f"渠道明明连着，回调却说找不到：{r.status_code} {r.text[:160]}")
        assert len(seen["kai"]) == 1 and seen["default"] == [] and seen["yi_ling"] == [], (
            f"事件落错了桶：kai={len(seen['kai'])} default={len(seen['default'])} "
            f"yi_ling={len(seen['yi_ling'])}")
        assert seen["kai"][0].sender_id == "ou_real_b28", "解析途中把消息内容弄丢了"

    def testSharedCredentialsNoLongerSlideIntoDefault(self, harness):
        """**§6-197 的行为变更**：两只共用同一份 verification token ⇒ 拒，并点名是哪几只。

        这一格是对本档原"default 优先"那条的**改判**（不是放宽）。旧断言"仍走 default"看着像兼容，
        实际是把配置错误掩盖成正常投递：两只 app 用了同一份凭据（`/conflicts/check` 在报的就是它），
        此时回调确实无法分辨，那就明确不投——静默投给 default 等于替其中一个 agent 收下别人的消息。
        """
        client, mgr, seen, register = harness
        register("default", "default", "def_app")
        register("kai", "kai", "kai_app")          # 与 default 同一份 VERIFY_TOKEN（共用凭据）

        r = client.post(WEBHOOK.format("feishu"), json=_eventBody())

        assert r.status_code in (403, 404), f"共用凭据的歧义拿到了 {r.status_code}"
        assert not any(seen.values()), f"却仍然投递了：{ {k: len(v) for k, v in seen.items()} }"
        detail = (r.json() or {}).get("detail") or ""
        assert "default" in detail and "kai" in detail, f"文案没点名是哪几只共用：{detail!r}"

    def testDistinctCredentialsRouteToTheirOwnInstance(self, harness):
        """本意这条才是对的：各 agent 各有专属凭据 ⇒ 谁的 token 进谁那只，default 不插队。"""
        client, mgr, seen, register = harness
        register("default", "default", "def_app")
        register("kai", "kai", "kai_app")
        # 投递面是 record-only 的假适配器，凭据核在真 FeishuAdapter.verify_event_token 上：
        # 把 kai 那只换成 kai 自己的 token，default 那只保持原 token。
        mgr.get_adapter("feishu", agent_id="kai").config.verification_token = "kai-own-token"

        r = client.post(WEBHOOK.format("feishu"), json=_eventBody(token="kai-own-token"))

        assert r.status_code == 200, f"kai 自己的凭据发的回调被拒：{r.status_code} {r.text[:120]}"
        assert len(seen["kai"]) == 1 and seen["default"] == [], (
            f"落错了实例：kai={len(seen['kai'])} default={len(seen['default'])}")

        r2 = client.post(WEBHOOK.format("feishu"), json=_eventBody(user="ou_def_person"))
        assert r2.status_code == 200 and len(seen["default"]) == 1 and len(seen["kai"]) == 1, (
            f"default 自己的凭据该仍进 default：{ {k: len(v) for k, v in seen.items()} }")

    def testAmbiguousMultiAdapterNeverSilentlyDelivers(self, harness):
        """两个非 default agent 各配一条同名渠道 ⇒ 不许静默投给任意一个，文案还得点名涉及哪几个。

        §6-197 之后这一支走的是"凭据都不唯一"那条分支（两只在夹具里共用 VERIFY_TOKEN），
        旧文案是"回调 URL 无法唯一确定适配器"、新文案点名"authenticated against multiple agents"——
        两者都要求'拒 + 点名'，所以本格断言不变；真按不同凭据配的话，见上面那格（各进各的）。
        """
        client, mgr, seen, register = harness
        register("kai", "kai", "kai_app")
        register("yi_ling", "yi_ling", "yl_app")

        r = client.post(WEBHOOK.format("feishu"), json=_eventBody())

        assert seen["kai"] == [] and seen["yi_ling"] == [] and seen["default"] == [], (
            f"歧义场景把消息投给了某一个：kai={len(seen['kai'])} "
            f"yi_ling={len(seen['yi_ling'])} default={len(seen['default'])}")
        assert r.status_code == 404, f"歧义应当显式失败而不是 200（实得 {r.status_code}）"
        detail = r.json().get("detail") or ""
        assert "multiple agents" in detail and "kai" in detail and "yi_ling" in detail, (
            f"文案没点名歧义与涉及的 agent，运维会以为是没配置：{detail!r}")

    def testTrulyUnconfiguredChannelStillSaysNotFound(self, harness):
        """反空转：一格都没配时不能被"歧义"盖掉——两种失败必须分得开，否则下一次没人看得出接线坏了。"""
        client, mgr, seen, register = harness

        r = client.post(WEBHOOK.format("feishu"), json=_eventBody())

        assert r.status_code == 404 and not any(seen.values())
        detail = r.json().get("detail") or ""
        assert "multiple agents" not in detail and "not found" in detail.lower(), (
            f"两种失败混成一种了：{detail!r}")


class TestTheResolutionHasOneFace:
    def testEndpointStopsCallingGetAdapterItself(self):
        """`handle_webhook` 不再自己取 default 视图——解析只在 manager 那一个入口，且只一次。"""
        attrs = _resolutionCallsIn(CHANNELS_SRC, "handle_webhook")
        assert attrs.count("get_adapter") == 0, f"入站还在自己取 default 视图（{attrs}）"
        assert attrs.count("resolveInboundAdapter") == 1, f"解析入口没被用上或用了多次（{attrs}）"

    def testResolutionDetectorHasTeeth(self):
        """自证：探测器真分得清两副面孔（只断"现在对了"的那格会随代码漂移而失真）。"""
        sample = chr(10).join([
            "async def handle_webhook(manager):",
            "    a = manager.get_adapter('feishu')",
            "    b = manager.resolveInboundAdapter('feishu')",
            "    return a, b",
        ])
        assert _resolutionCallsIn(sample, "handle_webhook") == [
            "get_adapter", "resolveInboundAdapter"], "读法失真"

    def testOutboundFaceKeepsItsAgentDimension(self):
        """别把出站那条也改掉——`channel_router` 一直是按 agent 取实例的现役正解（对照格）。"""
        src = (REPO / "neurova" / "channels" / "channel_router.py").read_text(encoding="utf-8")
        assert re.search(r"get_adapter\([^)\n]*agent_id\s*=", src), (
            "channel_router 的 agent 维度丢了：入站合流不该把出站那条改成默认视图")

    def testDebtDetectorHasTeeth(self):
        """四形对照：裸调要抓、两种合法写法都不许抓、同名异面也不抓。"""
        src = chr(10).join([
            "def f(manager):",
            "    a = manager.get_adapter('feishu')",                  # 裸调：抓
            "    b = manager.get_adapter('feishu', agent_id='kai')",  # 关键字写法：放过
            "    c = manager.get_adapter('feishu', 'kai')",           # 位置参数写法：放过
            "    d = manager.registry.get_adapter('feishu')",         # 同名异面：放过
        ])
        assert _bareAdapterLookups([("synthetic.py", ast.parse(src))]) == {
            "synthetic.py": [2]}, "探测器口径失真"

    def testRegisteredDebtSitesAreCountedByShape(self):
        """同根因余点由判据自己数——登记不等于留白：新长出一处裸调就红，落点消失了也必须销行。

        §6-190 那批把 `channels.py` 的三个管理端点与 `manager.replace_channel` 收掉后，这张表从三条
        缩到一条。**是这一格反过来抓到我的**：改完生产码它就报"落点已消失"，逼得同批删过期豁免，
        而不是留一张看着还在核实、其实早已空转的表。
        """
        known = {
            "neurova/api/endpoints/channel_sharing.py":
                "共享面板的一栏只读状态——它读的这份渠道状态本身没有 agent 维度（sharing 配置是全局的），"
                "要一并 agent 化属 sharing 整块的那次裁定，不在 §6-189/§6-190 两批里顺手改",
        }
        hits = _bareAdapterLookups(_neurovaTrees())
        extra = set(hits) - set(known)
        assert extra == set(), (
            f"新长出一处无 agent 维度的渠道取实例，先裁再合：{[(f, hits[f]) for f in sorted(extra)]}")
        vanished = set(known) - set(hits)
        assert vanished == set(), (
            f"登记表里的落点已消失，同批把那一行销掉（别留过期豁免）：{sorted(vanished)}")
