# -*- coding: utf-8 -*-
"""「关思考的旋钮发不发得出去」这一问，必须由**知道本轮打到谁的边界**来答。

## 病根（2026-10-23 复核 `openai_loop.py:701` 抓到）

§6-397 批 H 的 E 笔把恢复轮的空转掐掉了，判据 `thinkingKnobReachesGateway()` 读的是
`client.config.compat`。生产里那个 `client` 是**路由门面** `AgentLLMClient`
（`agent_core.py:121`），它的 `.config` 来自 `agent_core.py:315` 那次 `LLMConfig(...)`
——构造时从不传 compat ⇒ 门面那份永远是 dataclass 默认值（收尾那一笔把它**显式清空**，
见 `TestFacadePresentsNoFakeDeclaration`：留着默认值就是留着"没人声明"与"声明为否"的撞脸）。
真的 provider 声明只挂在 `multi_model_client.py:296-301` 的
**内层 per-provider 客户端**上，门面拿不到。

于是对 amd 恰好同结果（`resolve_compat("amd")` 也是 False），活体与在册判据都测不出来；
但对声明 `supports_thinking_toggle=True` 的网关，判据照样答"到不了"⇒ **白丢一次真能自救
的重试**。判据自带的 fail-open（`provider_compat.py:209-210`）只护"没有 compat 对象"，
present-but-default 拦不住——默认值长得就像"已声明为否"。

修法：把这一问移到**路由边界**。`MultiModelLLMClient.requestCompatCandidates(model,
provider_id)` 按与 `_get_client_for_request` 同源的口径挑出本轮真正会打到的 provider 行，
用与发送侧同一个 `resolve_compat()` 复算声明；门面只负责把"本轮是谁"传下去。
任一候选能降思考即重试；候选挑不出来（路由答不出）⇒ fail-open，不借判据躲重试。

判据一律打在**真 `AgentLLMClient` 实例**上——旧档手工塞
`SimpleNamespace(config=SimpleNamespace(compat=…))` 的替身携带的是生产不具备的真声明，
正是这条偏差测不出来的原因（形态 403）。
"""
from __future__ import annotations

import uuid

import pytest

from neurova.agent_core import AgentLLMClient
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.provider_compat import ProviderCompat, thinkingKnobReachesGateway
from neurova.llm.provider_manager import LLMProviderManager

# 静态表收录的 host：只声明 supports_reasoning_effort（`provider_compat.py:147`）
SILENT_BASE = "https://developer.amd.com.cn/radeon/v1"
SILENT_MODEL = "GLM-Silent-Flash"
# 未收录进静态表，靠 providers.json 的 compat_dict 显式声明 toggle
TOGGLE_BASE = "https://toggle.example/v1"
TOGGLE_MODEL = "Qwen-Toggle-Flash"
# 池里谁都不认这个模型：路由要兜底给任何可用客户端 ⇒ 判据没资格断言"到不了"
ORPHAN_MODEL = "NoSuchModel-9"


def _manager(tmp_path) -> LLMProviderManager:
    """独立配置路径的 manager（不碰用户目录里的 providers.json）。"""
    return LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})


def _client(manager) -> MultiModelLLMClient:
    scope = f"probe-knob-{uuid.uuid4().hex[:8]}"
    routing = MultiModelLLMClient(scope=scope, provider_manager=manager)
    return routing, scope


@pytest.fixture
def pool(tmp_path, monkeypatch):
    """真 manager + 真 MultiModelLLMClient：池里一间静默房、一间能关思考的房。

    门面的 `_get_client()` 在调用时才 import `get_multi_model_client`，故这里按
    fixture 作用域打桩（monkeypatch 自动还原），不许用"构造完就还原"的窄窗——
    那会让门面在判据时刻回落真全局单例（读到的仍是用户目录那份 providers.json）。
    """
    manager = _manager(tmp_path)
    silent = manager.add_provider(
        name="Silent Gw", provider="openai", base_url=SILENT_BASE,
        api_key="sk-test", models=[SILENT_MODEL],
    )
    toggle = manager.add_provider(
        name="Toggle Gw", provider="openai", base_url=TOGGLE_BASE,
        api_key="sk-test", models=[TOGGLE_MODEL],
        compat_dict={"supports_thinking_toggle": True},
    )
    routing, scope = _client(manager)
    monkeypatch.setattr(
        "neurova.llm.multi_model_client.get_multi_model_client",
        lambda s=None: routing,
    )
    try:
        yield routing, silent.id, toggle.id
    finally:
        MultiModelLLMClient._instances.pop(scope, None)


def candidates(routing, **kwargs) -> list:
    """新边界的取数口（HEAD 上还没有这个方法 ⇒ 断言落在这里就是行为红）。"""
    resolve = getattr(routing, "requestCompatCandidates", None)
    assert callable(resolve), (
        "路由边界没有 requestCompatCandidates：判据只能读门面的默认 compat"
    )
    return list(resolve(**kwargs) or [])


class TestCandidatesComeFromRows:
    def testCandidatesAreResolvedWithTheSameFactSourceAsTheSender(self, pool):
        """候选必须是 `ProviderCompat` 实例——声明的解析与发送侧共用 `resolve_compat`。"""
        routing, _, _ = pool

        found = candidates(routing, model=TOGGLE_MODEL)

        assert len(found) == 1, found
        assert isinstance(found[0], ProviderCompat), found

    def testExplicitDeclarationOnTheRowIsVisible(self, pool):
        """compat_dict 显式声明要能从行里读到（静态表以外的第二入口）。"""
        routing, _, _ = pool

        found = candidates(routing, model=TOGGLE_MODEL)

        assert found[0].supports_thinking_toggle is True, found[0]

    def testStaticTableRowIsVisible(self, pool):
        routing, _, _ = pool

        found = candidates(routing, model=SILENT_MODEL)

        assert found[0].supports_thinking_toggle is False, found[0]
        assert found[0].supports_reasoning_effort is True, "静态表行应带 amd 的声明"


class TestFacadeVerdictFollowsTheCandidate:
    """判据打在真门面上：门面自己那份 compat 恒是默认值，结论必须来自候选行。"""

    def testToggleCapableCandidateMakesTheKnobReachTheGateway(self, pool):
        routing, _, _ = pool
        facade = AgentLLMClient(model=TOGGLE_MODEL)

        assert facade.config.compat is None, (
            "门面不持提供方事实（§6-403）——本判据要证明的是结论来自候选行，不是来自它"
        )
        assert thinkingKnobReachesGateway(facade, {"thinking_effort": "deep"}) is True, (
            "候选行声明了 enable_thinking 却答『发不出去』＝白丢一次真能自救的重试"
        )

    def testSilentCandidateStillAnswersNo(self, pool):
        """不扩大战果：静默网关照旧答『到不了』，恢复轮照该掐。"""
        routing, _, _ = pool
        facade = AgentLLMClient(model=SILENT_MODEL)

        assert thinkingKnobReachesGateway(facade, {"thinking_effort": "deep"}) is False

    def testPinnedProviderNarrowsTheCandidates(self, pool):
        """钉死提供方时不许把池里别的房也算进来——重试打的还是那一家。"""
        routing, silent_id, _ = pool
        facade = AgentLLMClient(model=TOGGLE_MODEL, provider_id=silent_id)

        assert thinkingKnobReachesGateway(facade, {"thinking_effort": "deep"}) is False

    def testUnresolvableRoutingFailsOpen(self, pool):
        """模型在池里无人认：路由会兜底给任何可用客户端 ⇒ 判据答不出，按『能到』处理。"""
        routing, _, _ = pool
        facade = AgentLLMClient(model=ORPHAN_MODEL)

        assert thinkingKnobReachesGateway(facade, {"thinking_effort": "deep"}) is True


class TestEmptyPoolFailsOpen:
    def testNoUsableRowDoesNotBlockTheRetry(self, tmp_path, monkeypatch):
        """池里没有可用房（无 key）：没有任何声明有资格判『到不了』⇒ fail-open。"""
        manager = _manager(tmp_path)
        manager.add_provider(
            name="Empty Gw", provider="openai", base_url=TOGGLE_BASE,
            api_key=None, models=[TOGGLE_MODEL],
            compat_dict={"supports_thinking_toggle": True},
        )
        routing, scope = _client(manager)
        monkeypatch.setattr(
            "neurova.llm.multi_model_client.get_multi_model_client",
            lambda s=None: routing,
        )
        try:
            facade = AgentLLMClient(model=TOGGLE_MODEL)

            assert thinkingKnobReachesGateway(facade, {"thinking_effort": "deep"}) is True
        finally:
            MultiModelLLMClient._instances.pop(scope, None)


class TestFacadePresentsNoFakeDeclaration:
    """门面那份 config 不许拿 dataclass 默认值冒充"这台网关已声明为否"。

    §6-403 把取数移到路由边界之后，门面里的 `compat` 已经没有读者，但它**还在**——
    而"还在的默认值"与"声明为否"在 `getattr(config, "compat")` 这种写法下一模一样。
    留着一个没人声明却长得像声明的对象，就是给下一个同类缺陷备好床位（§8 断点条款）。
    """

    def testFacadeCompatIsExplicitlyUnset(self, pool):
        routing, _, _ = pool

        facade = AgentLLMClient(model=TOGGLE_MODEL)

        assert facade.config.compat is None, (
            "门面仍自带一份 dataclass 默认 compat：新代码把『没人声明』读成『声明为否』"
        )

    def testSenderSideConfigStillCarriesRealCompat(self):
        """反向：清空只针对路由门面，发送侧内层客户端的 compat 不许被一起清掉。"""
        from neurova.llm_client import LLMConfig

        assert LLMConfig(model="x").compat.supports_tools is True


class TestLegacyClientShapeIsHonoured:
    """没有路由面的调用方（内层客户端/既有替身）：照旧读它自己那份 compat。"""

    def testClientWithResolvedCompatIsStillAnsweredFromIt(self, pool):
        from types import SimpleNamespace

        routing, _, _ = pool
        inner = SimpleNamespace(config=SimpleNamespace(
            compat=ProviderCompat(supports_thinking_toggle=True)
        ))

        assert thinkingKnobReachesGateway(inner, {"thinking_effort": "deep"}) is True
        assert candidates(routing, model=SILENT_MODEL)[0].thinkingReducible(
            {"thinking_effort": "deep"}
        ) is False
