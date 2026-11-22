# -*- coding: utf-8 -*-
"""W4 红灯：neuacp 进程池池键属主段补全（登记行 ownerId 完整）。

计划：docs/04-plans/2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md §4 W4。

红→绿判据：
- 装配期（attachProcessPool）带 swarm 成员 id → 池键追加属主尾段
  （既有六段顺序/分隔不变，只追加第七段）、spawn 登记行 ownerId=成员 id；
- 旧键（六元组，无属主段）解析兼容不炸、登记行 ownerId 仍为空（诚实缺省）；
- §6.4 租户段语义不变：租户段仍居首位、缺省回落 default、跨租户不共享进程；
- 无属主装配（缺省 ownerId=""）不炸，保持旧键形态；
- 属主段真实参与池键：同租户同工具不同属主不共享进程（复用互不串池）。

跑法：`.venv/Scripts/python.exe -m pytest tests/unit/agent/test_neuacp_pool_key_owner.py -q`
"""
from __future__ import annotations

import pytest

from neurova.core import connection_pool as connection_pool_mod
from neurova.remote_exec import registry as registry_mod
from neurova.remote_exec.registry import KIND_NEUACP, getRemoteEndpointRegistry


@pytest.fixture()
def isolatedDataRoot(tmp_path, monkeypatch):
    """临时数据根 + 注册表单例/连接池复位（对齐 tests/unit/remote_exec 口径）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None
    yield tmp_path
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None


class FakeProcess:
    """进程替身：is_alive 属性 + terminate()（与 NeuacpClient 形状一致）。"""

    def __init__(self, alive: bool = True):
        self._alive = alive
        self.terminated = False

    @property
    def is_alive(self) -> bool:
        return self._alive and not self.terminated

    def terminate(self) -> None:
        self.terminated = True


def makePool(**overrides):
    from neurova.agent.neuacp.process_pool import NeuacpProcessPool

    fields = {"maxProcs": 4, "idleSeconds": 600.0}
    fields.update(overrides)
    return NeuacpProcessPool(**fields)


def makeExecutor(command=None):
    from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor

    return NeuacpStdioExecutor(list(command or ["opencode", "acp"]),
                               protocol_version="1")


# ── ① 装配期带成员 id：池键含属主段、登记行 ownerId=成员 id ────────────────


class TestOwnerSegmentAtAttach:
    def test_poolKeyAppendsOwnerTailSegment(self):
        """ownerId 非空 → 七元组：既有六段原样在前，属主段追加在尾。"""
        from neurova.agent.neuacp.process_pool import poolKey

        key = poolKey("tenant-w4", "opencode", ["opencode", "acp"], "/w/a",
                      ownerId="member-w4-1")
        assert key == ("tenant-w4", "opencode", ("opencode", "acp"), "/w/a",
                       "stdio", "", "member-w4-1"), \
            "池键必须保持既有六段顺序不变、属主段只追加在尾"

    def test_attachWithMemberIdPutsOwnerIntoPoolKey(self):
        """attachProcessPool 装配期传成员 id → 执行体持有的池键带属主段。"""
        from neurova.agent.neuacp.process_pool import poolKey, poolKeyOwner

        pool = makePool()
        executor = makeExecutor()
        baseKey = poolKey("tenant-w4", "opencode", ["opencode", "acp"], "/w/a")
        executor.attachProcessPool(pool, baseKey, ownerId="member-w4-1")
        assert poolKeyOwner(executor._pool_key) == "member-w4-1"
        # 既有六段不被改写
        assert executor._pool_key[:6] == baseKey
        pool.shutdown()

    def test_spawnWithOwnerKeyRegistersOwnerIdInRegistry(self, isolatedDataRoot):
        """spawn 成功 → 登记行 ownerId=池键属主段（swarm 成员 id）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        key = poolKey("tenant-w4", "gemini-cli", ["gemini", "--acp"], "/w/n",
                      ownerId="member-w4-1")
        entry = pool.acquire(key, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert len(endpoints) == 1, "spawn 成功后应登记恰好一个 neuacp 端点"
            ep = endpoints[0]
            assert ep.ownerId == "member-w4-1", "登记行 ownerId 必须取池键属主段"
            assert ep.tenantId == "tenant-w4"
            assert ep.name == "gemini-cli"
            assert ep.connectionRef == "stdio:gemini"
        finally:
            pool.release(key, entry)
            pool.shutdown()

    def test_executorAttachThenAcquireRegistersOwner(self, isolatedDataRoot):
        """装配期带成员 id → 执行体经池取件 → 登记行 ownerId=成员 id（全链）。"""
        pool = makePool()
        executor = makeExecutor(["gemini", "--acp"])
        from neurova.agent.neuacp.process_pool import poolKey

        baseKey = poolKey("tenant-w4", "gemini-cli", ["gemini", "--acp"], "")
        executor.attachProcessPool(pool, baseKey, ownerId="member-w4-2")
        executor._newStartedClient = lambda: FakeProcess()  # 替身：不拉真进程
        executor._ensureClient()
        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
        assert len(endpoints) == 1
        assert endpoints[0].ownerId == "member-w4-2"
        assert endpoints[0].tenantId == "tenant-w4"
        pool.shutdown()

    def test_differentOwnersSameToolRegisterSeparateEndpoints(self, isolatedDataRoot):
        """同租户同工具、不同属主 → 注册表两行（自然键含 ownerId）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        keyA = poolKey("tenant-w4", "opencode", ["opencode", "acp"], "/w/a",
                       ownerId="member-a")
        keyB = poolKey("tenant-w4", "opencode", ["opencode", "acp"], "/w/a",
                       ownerId="member-b")
        entryA = pool.acquire(keyA, lambda: FakeProcess())
        entryB = pool.acquire(keyB, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert {ep.ownerId for ep in endpoints} == {"member-a", "member-b"}
            assert all(ep.tenantId == "tenant-w4" for ep in endpoints)
        finally:
            pool.release(keyA, entryA)
            pool.release(keyB, entryB)
            pool.shutdown()


# ── ② 旧键（无属主段）解析兼容不炸、登记 ownerId 空 ────────────────────────


class TestLegacyKeyCompatibility:
    def test_legacySixSegmentKeyUnchanged(self):
        """不带 ownerId 的 poolKey 仍返回既有六元组（存量断言/调用方不破）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        key = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a")
        assert key == ("t1", "opencode", ("opencode", "acp"), "/w/a", "stdio", "")

    def test_poolKeyOwnerOfLegacyKeyIsEmpty(self):
        from neurova.agent.neuacp.process_pool import poolKey, poolKeyOwner

        assert poolKeyOwner(poolKey("t1", "x", ["x"], "/w")) == ""
        assert poolKeyOwner(poolKey("t1", "x", ["x"], "/w", ownerId="m1")) == "m1"

    def test_normalizeKeyAcceptsBothShapes(self):
        """池内解析兼容六元组/七元组：旧键不炸、新键保留属主段。"""
        from neurova.agent.neuacp.process_pool import _normalizeKey

        legacy = _normalizeKey(("t1", "x", ("c",), "/w", "stdio", ""))
        assert legacy == ("t1", "x", ("c",), "/w", "stdio", "")
        assert len(legacy) == 6
        owned = _normalizeKey(("t1", "x", ("c",), "/w", "stdio", "", "member-x"))
        assert owned == ("t1", "x", ("c",), "/w", "stdio", "", "member-x")
        assert len(owned) == 7

    def test_spawnWithLegacyKeyRegistersEmptyOwner(self, isolatedDataRoot):
        """旧键 spawn → 登记行 ownerId 仍为空（诚实缺省，不臆造属主）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        key = poolKey("tenant-n", "opencode", ["opencode", "acp"], "/w/n")
        entry = pool.acquire(key, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert len(endpoints) == 1
            assert endpoints[0].ownerId == ""
        finally:
            pool.release(key, entry)
            pool.shutdown()

    def test_attachTwoArgFormStillWorks(self, isolatedDataRoot):
        """attachProcessPool 旧两参形态兼容：不传 ownerId 不炸、按旧键取件。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        executor = makeExecutor()
        baseKey = poolKey("tenant-w4", "opencode", ["opencode", "acp"], "")
        executor.attachProcessPool(pool, baseKey)  # 旧形态：不传 ownerId
        assert len(executor._pool_key) == 6
        executor._newStartedClient = lambda: FakeProcess()
        executor._ensureClient()
        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
        assert len(endpoints) == 1
        assert endpoints[0].ownerId == ""
        pool.shutdown()


# ── ③ 租户段语义不变（§6.4：租户段仍是第一权威段） ────────────────────────


class TestTenantSegmentSemanticsUnchanged:
    def test_tenantStaysFirstSegmentWithOwnerPresent(self):
        from neurova.agent.neuacp.process_pool import poolKey

        key = poolKey("t1", "x", ["x"], "/w", transport="ssh", remote="host-9",
                      ownerId="m1")
        assert key[0] == "t1", "租户段必须仍居首位"
        assert key[4:6] == ("ssh", "host-9")
        assert key[6] == "m1"

    def test_emptyTenantStillFallsBackToDefault(self):
        from neurova.agent.neuacp.process_pool import poolKey

        assert poolKey("", "x", ["x"], "", ownerId="m1")[0] == "default"

    def test_tenantIsolationHoldsWithSameOwner(self, isolatedDataRoot):
        """同属主、不同租户 → 池不共享进程（§6.4 红线不因属主段松动）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        made = []
        keyT1 = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a",
                        ownerId="member-x")
        keyT2 = poolKey("t2", "opencode", ["opencode", "acp"], "/w/a",
                        ownerId="member-x")
        a = pool.acquire(keyT1, lambda: made.append("a") or FakeProcess())
        pool.release(keyT1, a)
        b = pool.acquire(keyT2, lambda: made.append("b") or FakeProcess())
        assert made == ["a", "b"], "跨租户不得复用进程（即便属主相同）"
        pool.release(keyT2, b)
        pool.shutdown()

    def test_tenantIsolationCarriesIntoRegistryWithOwner(self, isolatedDataRoot):
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        keyT1 = poolKey("tenant-1", "opencode", ["opencode", "acp"], "/w/1",
                        ownerId="member-x")
        keyT2 = poolKey("tenant-2", "opencode", ["opencode", "acp"], "/w/2",
                        ownerId="member-x")
        e1 = pool.acquire(keyT1, lambda: FakeProcess())
        e2 = pool.acquire(keyT2, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert {ep.tenantId for ep in endpoints} == {"tenant-1", "tenant-2"}
            assert all(ep.ownerId == "member-x" for ep in endpoints)
        finally:
            pool.release(keyT1, e1)
            pool.release(keyT2, e2)
            pool.shutdown()


# ── ④ 无属主装配（缺省）不炸 ───────────────────────────────────────────────


class TestNoOwnerAssembly:
    def test_poolKeyWithEmptyOwnerKeepsLegacyShape(self):
        from neurova.agent.neuacp.process_pool import poolKey, poolKeyWithOwner

        baseKey = poolKey("t1", "x", ["x"], "/w")
        assert poolKeyWithOwner(baseKey, "") == baseKey
        assert len(poolKeyWithOwner(baseKey, "")) == 6
        assert poolKey("t1", "x", ["x"], "/w", ownerId="") == baseKey

    def test_poolKeyWithOwnerOverwritesSegment(self):
        from neurova.agent.neuacp.process_pool import (
            poolKey,
            poolKeyOwner,
            poolKeyWithOwner,
        )

        baseKey = poolKey("t1", "x", ["x"], "/w")
        owned = poolKeyWithOwner(baseKey, "member-1")
        assert len(owned) == 7 and poolKeyOwner(owned) == "member-1"
        # 重复装配以本次传入为准（装配期属主单次裁定）
        reowned = poolKeyWithOwner(owned, "member-2")
        assert poolKeyOwner(reowned) == "member-2"
        assert reowned[:6] == baseKey

    def test_defaultAttachWithoutOwnerDoesNotCrash(self, isolatedDataRoot):
        """缺省装配（无属主）全链不炸，登记行 ownerId 空。"""
        pool = makePool()
        executor = makeExecutor()
        from neurova.agent.neuacp.process_pool import poolKey

        executor.attachProcessPool(pool, poolKey("tenant-w4", "opencode",
                                                 ["opencode", "acp"], ""))
        executor._newStartedClient = lambda: FakeProcess()
        executor._ensureClient()
        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
        assert len(endpoints) == 1 and endpoints[0].ownerId == ""
        pool.shutdown()


# ── ⑤ 属主段真实参与池键：同租户不同属主不共享进程 ────────────────────────


class TestOwnerSegmentKeysThePool:
    def test_sameTenantDifferentOwnersDoNotShareProcess(self):
        """属主段进键的实质：同租户同工具、不同成员不串池复用。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        made = []
        keyA = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a",
                       ownerId="member-a")
        keyB = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a",
                       ownerId="member-b")
        a = pool.acquire(keyA, lambda: made.append("a") or FakeProcess())
        pool.release(keyA, a)
        b = pool.acquire(keyB, lambda: made.append("b") or FakeProcess())
        assert made == ["a", "b"], "不同属主不得复用同一进程"
        assert b.process is not a.process
        pool.release(keyB, b)
        pool.shutdown()

    def test_sameOwnerReusesIdleProcess(self):
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        made = []
        key = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a",
                      ownerId="member-a")
        first = pool.acquire(key, lambda: made.append(1) or FakeProcess())
        pool.release(key, first)
        second = pool.acquire(key, lambda: made.append(2) or FakeProcess())
        assert made == [1], "同键（含同属主）应复用空闲进程"
        assert second.process is first.process
        pool.release(key, second)
        pool.shutdown()

    def test_statsExposesOwnerSegment(self, isolatedDataRoot):
        """池状态盘点面透出属主段（登记/审计同源口径）。"""
        from neurova.agent.neuacp.process_pool import poolKey

        pool = makePool()
        key = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a",
                      ownerId="member-a")
        entry = pool.acquire(key, lambda: FakeProcess())
        pool.release(key, entry)
        processes = pool.stats()["processes"]
        assert len(processes) == 1
        assert processes[0]["owner"] == "member-a"
        assert processes[0]["tenant"] == "t1"
        pool.shutdown()
