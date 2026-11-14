# -*- coding: utf-8 -*-
"""P2-10 LLMRouter 作用域隔离红绿测试（全库代码审计 2026-11-14）。

缺陷：register_provider 用裸 provider_id 作全局 dict 键，sync_llm_router
把任意 scope 的 provider 注册进同一张表——同名 provider_id 跨用户互相
顶掉（用户 A 的 "openai" 覆盖用户 B 的 "openai"）。

修复口径：注册键改复合 `f"{scope}:{provider_id}"`（scope 缺省 "admin"）；
select_model 按 `f"{scope}:"` 前缀过滤候选，候选空回落 admin 前缀
（保持"候选空回全局"语义）；_providers 读写持单例锁，并发注册/选型
不再抛 "dictionary changed size during iteration"。
"""
import threading

import pytest

from neurova.llm import llm_router
from neurova.llm.llm_router import RequestType, get_llm_router


def _model(name, caps=("vision",)):
    return {
        "name": name,
        "capabilities": list(caps),
        "priority": 1,
        "health_status": "healthy",
        "response_time": 0.0,
        "weight": 1.0,
    }


@pytest.fixture
def router(monkeypatch):
    """干净路由器：清空注册表、复位 scope 同步账、屏蔽 provider 管理器同步。"""
    r = get_llm_router()
    with r._instanceLock:
        r._providers.clear()
    old_synced = set(llm_router._synced_scopes)
    llm_router._synced_scopes = {"admin"}
    # 屏蔽真实 ProviderManager 拉取（单测只验路由器自身的隔离与并发语义）
    import neurova.llm.provider_manager as pm

    monkeypatch.setattr(pm, "get_provider_manager", lambda scope=None, config_path=None: None)
    yield r
    with r._instanceLock:
        r._providers.clear()
    llm_router._synced_scopes = old_synced


class TestLlmRouterScopeIsolation:
    def test_sameProviderIdAcrossScopes_selectsOwnScopeModel(self, router):
        """两 scope 注册同名 provider_id、不同模型 → 各自选到自己的模型。"""
        router.register_provider("openai", "AliceOpenAI", [_model("model-alice")], scope="user:alice")
        router.register_provider("openai", "BobOpenAI", [_model("model-bob")], scope="user:bob")

        got_alice = llm_router.select_model_for_request(
            RequestType.IMAGE_UNDERSTANDING, scope="user:alice")
        got_bob = llm_router.select_model_for_request(
            RequestType.IMAGE_UNDERSTANDING, scope="user:bob")

        assert got_alice is not None and got_alice.model == "model-alice", (
            "alice 域必须选到 alice 域注册的模型（不再被 bob 的同名 provider 顶掉）")
        assert got_bob is not None and got_bob.model == "model-bob", (
            "bob 域必须选到 bob 域注册的模型")
        # 返回的 provider_id 是剥掉 scope 前缀的原始 ID（调用方语义不变）
        assert got_alice.provider_id == "openai"

    def test_scopeCandidatesEmpty_fallsBackToAdmin(self, router):
        """scope 域内候选空 → 回落 admin 前缀（保持"候选空回全局"语义）。"""
        router.register_provider("openai", "GlobalOpenAI", [_model("model-admin")], scope="admin")

        got = llm_router.select_model_for_request(
            RequestType.IMAGE_UNDERSTANDING, scope="user:newbie")

        assert got is not None and got.model == "model-admin", "用户域候选空必须回落 admin 表"

    def test_selectModel_scopedPrefixOnly(self, router):
        """select_model 只看该 scope 前缀条目：admin 有货 ≠ 用户域有货。"""
        router.register_provider("openai", "GlobalOpenAI", [_model("model-admin")], scope="admin")
        got = router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="user:nobody")
        assert got is None, "域内无候选时 select_model 自身必须返回 None（回落是外层职责）"

    def test_unregisterAndList_scopeAware(self, router):
        """unregister/list 按域隔离：注销 A 域不影响 B 域同名 provider。"""
        router.register_provider("openai", "AliceOpenAI", [_model("model-alice")], scope="user:alice")
        router.register_provider("openai", "BobOpenAI", [_model("model-bob")], scope="user:bob")

        router.unregister_provider("openai", scope="user:alice")

        assert router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="user:alice") is None
        got_bob = router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="user:bob")
        assert got_bob is not None and got_bob.model == "model-bob"
        alice_ids = [p["provider_id"] for p in router.list_providers(scope="user:alice")]
        bob_ids = [p["provider_id"] for p in router.list_providers(scope="user:bob")]
        assert alice_ids == []
        assert bob_ids == ["openai"]

    def test_concurrentRegisterAndSelect_noDictResizeError(self, router):
        """并发注册/选型不抛 "dictionary changed size during iteration"。"""
        errors = []
        stop = threading.Event()

        def registerWorker(threadIdx):
            try:
                for i in range(60):
                    router.register_provider(
                        f"prov{i % 7}", f"P{i}",
                        [_model(f"m-{threadIdx}-{i}")],
                        scope=f"user:t{threadIdx % 3}",
                    )
                    router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="user:t0")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def selectWorker():
            try:
                while not stop.is_set():
                    router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="user:t1")
                    router.list_providers(scope="user:t2")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=registerWorker, args=(i,)) for i in range(6)]
        threads += [threading.Thread(target=selectWorker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads[:6]:
            t.join(timeout=30)
        stop.set()
        for t in threads[6:]:
            t.join(timeout=30)

        assert not errors, f"并发注册/选型出现异常: {errors[:3]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
