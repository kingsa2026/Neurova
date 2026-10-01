# -*- coding: utf-8 -*-
"""compat 声明位必须**可达**：配置里的显式声明要真能走到 resolve_compat 的最高层。

## 为什么值得常驻

`provider_compat.resolve_compat` 的优先级写在 docstring 里：
"ProviderConfig 显式声明（compat_dict）> provider id 静态表 > …"。
消费侧也一直按这个契约读（`multi_model_client.py:304` 传
`compat_dict=getattr(provider, "compat_dict", None)`）——但 **`ProviderConfig`
根本没有这个字段**（逐字段核过 `provider_manager.py:364`），用户配置里 0 行有它。
于是最高层恒为 `None`：

- 撞上一台新的"低容忍网关"（不认 `tools`、把采样值钉成单点、流式不吐 usage…），
  运维在配置里写什么都会被 `from_dict` 的"Ignoring unknown/legacy fields"丢掉；
- 唯一出路是**改代码加静态表行再发版**——声明面名义上是配置，实际上是源码。

这条链坏得安静的地方在于：读侧写的是 `getattr(..., None)`，字段缺失时**不报错**，
只把声明当成"用户没声明"。本文件把"声明位可达"钉成判据，逐段量：
持久化往返 → 写侧入口 → 读侧真拿得到 → 错键不许静默。

未知键的处置是同一根因的另一半：`ProviderCompat.merged` 用
`{f for f in __dataclass_fields__ if f in overrides}` 静默过滤，写错一个字母
（`supports_toolss`）等于没声明，且**无人知道**。所以判据要求：写侧拒绝并点名，
手改配置的路径也要在日志里点名——不许用静默吞掉代替校验。
"""
from __future__ import annotations

import logging

import pytest

from neurova.llm.provider_compat import ProviderCompat, resolve_compat
from neurova.llm.provider_manager import ProviderConfig


def _provider(**overrides) -> ProviderConfig:
    kwargs = dict(
        id="strict-gw",
        name="Strict Gateway",
        provider="openai",
        base_url="https://strict.example/v1",
        api_key="sk-test",
    )
    kwargs.update(overrides)
    return ProviderConfig(**kwargs)


def _manager(tmp_path):
    """独立配置路径的 manager（不碰用户目录里的 providers.json）。"""
    from neurova.llm.provider_manager import LLMProviderManager

    return LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})


@pytest.fixture(autouse=True)
def _noScopeInstancesLeftBehind():
    """本文件的判据会建 `MultiModelLLMClient(scope=...)` 实例——它们注册在类级
    `_instances` 上，不清就会带着临时 manager 漏给同进程后续测试。
    """
    from neurova.llm.multi_model_client import MultiModelLLMClient

    before = set(MultiModelLLMClient._instances)
    yield
    for scope in set(MultiModelLLMClient._instances) - before:
        MultiModelLLMClient._instances.pop(scope, None)


class TestDeclarationIsPersistable:
    def test_compatDictSurvivesPersistenceRoundTrip(self):
        """声明必须能进 providers.json 再读回来——今天 `to_dict()` 里根本没这个键。"""
        provider = _provider(compat_dict={"supports_tools": False})

        data = provider.to_dict()

        assert "compat_dict" in data, "to_dict 没带 compat_dict，配置里写不住声明"
        assert data["compat_dict"] == {"supports_tools": False}

        reloaded = ProviderConfig.from_dict(data)
        assert reloaded.compat_dict == {"supports_tools": False}

    def test_absentDeclarationStaysEmptyNotCrash(self):
        """存量配置没有这个键：默认空声明，不许把整份加载炸进异常分支。"""
        data = _provider().to_dict()
        data.pop("compat_dict", None)

        reloaded = ProviderConfig.from_dict(data)

        assert reloaded.compat_dict == {}


class TestWriteBoundary:
    def test_updateProviderStoresCompatDeclaration(self, tmp_path):
        """写侧入口要存在：`update_provider(compat_dict=...)` 能改并落盘。"""
        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Strict Gateway",
            provider="openai",
            base_url="https://strict.example/v1",
            api_key="sk-test",
        )

        assert manager.update_provider(
            added.id, compat_dict={"supports_tools": False}
        )

        assert manager.get_provider(added.id).compat_dict == {"supports_tools": False}

    def test_unknownCompatKeyIsRejectedAndNamed(self, tmp_path):
        """写错的键名必须被拒绝并点名，不许静默当成"没声明"。"""
        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Strict Gateway",
            provider="openai",
            base_url="https://strict.example/v1",
            api_key="sk-test",
        )

        with pytest.raises(ValueError) as raised:
            manager.update_provider(added.id, compat_dict={"supports_toolss": True})

        assert "supports_toolss" in str(raised.value)
        assert "supports_tools" in str(raised.value), "报错要给出可用键名，否则人改不动"
        assert manager.get_provider(added.id).compat_dict == {}, "拒绝 must not half-write"


class TestDeclarationReachesTheConsumer:
    def test_consumerSeesTheDeclaredOverride(self):
        """读侧就是 `getattr(provider, "compat_dict", None)`：这条必须真拿到声明。

        判据打在**未收录进静态表**的 provider 上——收录了的行本来就能生效，
        拿它测会把"字段缺失"这件事掩成"静态表起作用了"。
        """
        provider = _provider(compat_dict={"supports_tools": False})

        readByConsumer = getattr(provider, "compat_dict", None)

        assert readByConsumer == {"supports_tools": False}, (
            "消费方读到 None：最高层声明恒不可达，声明面其实只有源码"
        )
        compat = resolve_compat(
            provider_id=provider.id,
            base_url=provider.base_url,
            compat_dict=readByConsumer,
            protocol=provider.provider,
        )
        assert compat.supports_tools is False

    def testExplicitDeclarationBeatsTheProviderRow(self):
        """显式声明要能翻掉静态表行（sensetime 关流式 usage），字段级合并互不抹。"""
        provider = _provider(
            id="sensetime",
            base_url="https://token.sensenova.cn/v1",
            compat_dict={"include_stream_usage": True},
        )

        compat = resolve_compat(
            provider_id=provider.id,
            base_url=provider.base_url,
            compat_dict=getattr(provider, "compat_dict", None),
        )

        assert compat.include_stream_usage is True


class TestHandEditedConfigIsNotSilent:
    def test_mergedNamesUnknownKeys(self, caplog):
        """手改 providers.json 绕过写侧：未知键至少要在日志里点名。"""
        with caplog.at_level(logging.WARNING):
            ProviderCompat().merged({"supports_toolss": True, "include_stream_usage": False})

        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "supports_toolss" in joined, "静默过滤写错的键名 = 声明被吞"
        assert "include_stream_usage" in joined or "unknown" in joined.lower()


class TestApiReachable:
    """声明位必须从 API 可达：模型有字段 **且** 端点真把它转给 manager。

    只测"`UpdateProviderRequest` 有Compat字段"是不够的——字段存在而端点不转发，
    运维照样只能手编 JSON（这正是 P1-13 那条 `usage_collection` 断链的形状）。
    """

    def _call(self, manager, provider_id, body):
        import asyncio
        from types import SimpleNamespace

        import neurova.api.endpoints.provider as ep

        request = SimpleNamespace(state=SimpleNamespace(request_id="t"))
        original = ep._get_provider_manager
        ep._get_provider_manager = lambda current_user=None: manager
        try:
            return asyncio.run(ep.update_provider(request, provider_id, body, current_user=None))
        finally:
            ep._get_provider_manager = original

    def test_updateRequestModelCarriesCompat(self):
        from neurova.api.endpoints.provider import UpdateProviderRequest

        body = UpdateProviderRequest(compat={"supports_tools": False})

        assert body.compat == {"supports_tools": False}
        assert UpdateProviderRequest().compat is None, "None=不改动，不许把空声明当成清空"

    def test_endpointForwardsCompatToManager(self, tmp_path):
        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Strict Gateway",
            provider="openai",
            base_url="https://strict.example/v1",
            api_key="sk-test",
        )
        from neurova.api.endpoints.provider import UpdateProviderRequest

        self._call(manager, added.id, UpdateProviderRequest(compat={"supports_tools": False}))

        assert manager.get_provider(added.id).compat_dict == {"supports_tools": False}

    def test_badKeyComesBackAsFourHundred(self, tmp_path):
        """拼错键名是调用方错误：400 + 原文点名，不许被兜底成 500。"""
        from fastapi import HTTPException

        from neurova.api.endpoints.provider import UpdateProviderRequest

        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Strict Gateway",
            provider="openai",
            base_url="https://strict.example/v1",
            api_key="sk-test",
        )

        with pytest.raises(HTTPException) as raised:
            self._call(
                manager, added.id, UpdateProviderRequest(compat={"supports_toolss": True})
            )

        assert raised.value.status_code == 400
        assert "supports_toolss" in str(raised.value.detail)

    #: 端点**不**转发这些请求字段，逐条给理由（台账式，不是白名单放行）。
    #: 空着不写等于放行静默漏键，所以必须写明为什么不转。
    FORWARDING_EXEMPT = {
        "config": "指令容器（`add_model` 特判消费），不是 manager 参数",
        "name": "manager.update_provider 无 name 参数——provider 重命名面未接，登记待拍",
    }

    def test_everyOtherRequestFieldIsForwarded(self):
        """根因锁：端点是**逐键手写** update_kwargs 的，新加请求字段必然漏。

        `usage_collection` 就是这么漏掉一半的（P1-13 声称"manager + API 两处透传"，
        实际端点从没把它放进 update_kwargs）。这条判据不许再出现"模型有字段、
        端点不转发"：新增字段要么转发，要么进 `FORWARDING_EXEMPT` 写明理由。
        """
        import inspect

        from neurova.api.endpoints.provider import UpdateProviderRequest, update_provider

        source = inspect.getsource(update_provider.__wrapped__
                                   if hasattr(update_provider, "__wrapped__") else update_provider)
        fieldNames = sorted(
            getattr(UpdateProviderRequest, "model_fields", None)
            or UpdateProviderRequest.__fields__
        )
        unforwarded = [
            name for name in fieldNames
            if name not in self.FORWARDING_EXEMPT and f"body.{name}" not in source
        ]

        assert unforwarded == [], (
            f"请求字段 {unforwarded} 有模型定义但端点不转发，也不在豁免台账里"
        )

    def test_declarationTakesEffectWithoutRestart(self, tmp_path):
        """声明要当场生效：进程里已建好的 provider 客户端必须跟着换（实测过才写）。

        改前读数（探针，落工单集 §41）：声明 `supports_tools=False` 经 API 写进配置后，
        `MultiModelLLMClient` 缓存里的 `ModelClient.config.compat` 仍是 True，
        手工调 `refresh_provider()` 才翻成 False——"声明位"若只到磁盘，
        运维改完还得重启进程，等于没接完。同一处失效顺带覆盖 api_key/base_url
        （L-05 只失效了 manager 侧 provider 实例，没失效运行态客户端）。
        """
        from neurova.api.endpoints.provider import UpdateProviderRequest
        from neurova.llm.multi_model_client import MultiModelLLMClient

        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Strict Gateway",
            provider="openai",
            base_url="https://strict.example/v1",
            api_key="sk-test",
            models=["m1"],
            default_model="m1",
        )
        mmc = MultiModelLLMClient(provider_manager=manager, scope="t18-live")
        assert mmc.get_client(added.id, "m1") is not None, "客户端没建起来，这条测不到东西"

        self._call(manager, added.id, UpdateProviderRequest(compat={"supports_tools": False}))

        live = mmc.get_client(added.id, "m1")
        assert live.client.config.compat.supports_tools is False, (
            "声明只落了磁盘、运行态客户端没换 —— 改完必须重启才生效"
        )

    def test_deletedProviderLosesItsLiveClients(self, tmp_path):
        """同根因的第二命中点：删掉 provider 后，运行态客户端不许还能被路由。

        实测（探针）：DELETE 之后 `get_provider()` 已回 None，但
        `mmc.get_client(id, "m1")` 照样返回活客户端——`refresh_provider` 在
        "provider 查不到"时只 warn 就 return，**没清缓存**，等于删了个寂寞。
        """
        import asyncio
        import types

        import neurova.api.endpoints.provider as ep

        from neurova.llm.multi_model_client import MultiModelLLMClient

        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Gone Gateway",
            provider="openai",
            base_url="https://gone.example/v1",
            api_key="sk-test",
            models=["m1"],
            default_model="m1",
        )
        mmc = MultiModelLLMClient(provider_manager=manager, scope="t18-delete")
        assert mmc.get_client(added.id, "m1") is not None

        request = types.SimpleNamespace(state=types.SimpleNamespace(request_id="t"))
        original = ep._get_provider_manager
        ep._get_provider_manager = lambda current_user=None: manager
        try:
            asyncio.run(ep.delete_provider(request, added.id, current_user=None))
        finally:
            ep._get_provider_manager = original

        assert manager.get_provider(added.id) is None
        assert mmc.get_client(added.id, "m1") is None, (
            "配置已删、运行态客户端还在：这一轮之后仍能往被删的 provider 发请求"
        )

    def test_exemptReasonsAreNotEmptyStatements(self):
        """豁免必须带理由——空字符串/占位就是静默放行。"""
        for name, reason in self.FORWARDING_EXEMPT.items():
            assert len(reason) > 10, f"{name} 的豁免理由没写清"

    def test_usageCollectionFlagIsActuallyForwarded(self, tmp_path):
        """同根因的第二命中点：`usage_collection` 早在 P1-13 声称"API 可达"，
        但端点从未把它放进 `update_kwargs` —— 请求模型有字段 ≠ 转发生效。
        """
        manager = _manager(tmp_path)
        added = manager.add_provider(
            name="Billing Gateway",
            provider="openai",
            base_url="https://billing.example/v1",
            api_key="sk-test",
        )
        from neurova.api.endpoints.provider import UpdateProviderRequest

        self._call(manager, added.id, UpdateProviderRequest(usage_collection=True))

        assert manager.get_provider(added.id).usage_collection is True
