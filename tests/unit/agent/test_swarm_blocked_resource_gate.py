import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.swarm import SwarmManager, get_swarm_manager, reset_swarm_manager


class AgentStub:
    def __init__(self, model=None, release=None):
        self.config = SimpleNamespace(name="member")
        self.llm_client = SimpleNamespace(
            config=SimpleNamespace(model=model or "stub-model")
        )
        self.release = release
        self.calls = []

    async def chat(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.release is not None:
            await self.release.wait()
        return {"text": "done"}


def makeAgent(model=None, release=None):
    return AgentStub(model=model, release=release)


async def waitUntil(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


async def registerBlocked(swarm, upstream, downstream, monkeypatch):
    agents = {"upstream": upstream, "downstream": downstream}
    monkeypatch.setattr(
        swarm,
        "_resolve_agent",
        lambda aid: (agents.get(aid or "downstream"), aid or "downstream", False),
    )
    dep = await swarm.spawn("upstream", agent_id="upstream", background=True)
    blocked = await swarm.spawn(
        "downstream",
        agent_id="downstream",
        task_unit={"goal": "g", "dependencies": [dep["subagent_id"]]},
    )
    assert "subagent_id" in blocked, blocked
    return dep, blocked


@pytest.mark.asyncio
async def testBlockedPromotionRechecksBudget(swarm, monkeypatch):
    release = asyncio.Event()
    upstream = makeAgent(release=release)
    downstream = makeAgent()
    budget = {"over": False}
    monkeypatch.setattr(swarm, "_over_budget", lambda aid, model: budget["over"])
    dep, blocked = await registerBlocked(swarm, upstream, downstream, monkeypatch)

    budget["over"] = True
    release.set()
    assert await waitUntil(lambda: swarm.status(dep["subagent_id"])["status"] == "completed")
    await asyncio.sleep(0.05)

    assert len(downstream.calls) == 0
    assert swarm.status(blocked["subagent_id"])["status"] == "blocked"

    budget["over"] = False
    assert await waitUntil(lambda: swarm.status(blocked["subagent_id"])["status"] == "completed")
    assert len(downstream.calls) == 1


@pytest.mark.asyncio
async def testBlockedPromotionRechecksModelConcurrency(swarm, monkeypatch):
    releaseUpstream = asyncio.Event()
    releaseBlocker = asyncio.Event()
    releaseDownstream = asyncio.Event()
    upstream = makeAgent(model="upstream-model", release=releaseUpstream)
    downstream = makeAgent(release=releaseDownstream)
    monkeypatch.setattr(SwarmManager, "MAX_CONCURRENT_PER_MODEL", 1)
    dep, blocked = await registerBlocked(swarm, upstream, downstream, monkeypatch)

    downstream.llm_client.config.model = "busy-model"
    blocker = makeAgent(model="busy-model", release=releaseBlocker)
    agents = {"blocker": blocker, "downstream": downstream}
    monkeypatch.setattr(
        swarm, "_resolve_agent", lambda aid: (agents.get(aid), aid, False)
    )
    runningBlocker = await swarm.spawn("blocker", agent_id="blocker", background=True)
    releaseUpstream.set()
    assert await waitUntil(lambda: swarm.status(dep["subagent_id"])["status"] == "completed")
    await asyncio.sleep(0.05)

    assert len(downstream.calls) == 0
    assert swarm.status(blocked["subagent_id"])["status"] == "blocked"
    releaseBlocker.set()
    assert await waitUntil(lambda: swarm.status(runningBlocker["subagent_id"])["status"] == "completed")
    assert await waitUntil(lambda: swarm.status(blocked["subagent_id"])["status"] == "running")
    releaseDownstream.set()
    assert await waitUntil(lambda: swarm.status(blocked["subagent_id"])["status"] == "completed")
    assert len(downstream.calls) == 1


@pytest.mark.asyncio
async def testBlockedPromotionRechecksSpawnInterval(swarm, monkeypatch):
    release = asyncio.Event()
    upstream = makeAgent(release=release)
    downstream = makeAgent()
    dep, blocked = await registerBlocked(swarm, upstream, downstream, monkeypatch)

    monkeypatch.setattr(SwarmManager, "MIN_SPAWN_INTERVAL_MS", 10_000)
    release.set()
    assert await waitUntil(lambda: swarm.status(dep["subagent_id"])["status"] == "completed")
    await asyncio.sleep(0.05)

    assert len(downstream.calls) == 0
    assert swarm.status(blocked["subagent_id"])["status"] == "blocked"


@pytest.mark.asyncio
async def testBlockedPromotionRechecksModelCooldown(swarm, monkeypatch):
    release = asyncio.Event()
    upstream = makeAgent(release=release)
    downstream = makeAgent(model="cooling-model")
    dep, blocked = await registerBlocked(swarm, upstream, downstream, monkeypatch)

    monkeypatch.setattr(swarm, "_model_cooldown_remaining", lambda model: 5.0)
    release.set()
    assert await waitUntil(lambda: swarm.status(dep["subagent_id"])["status"] == "completed")
    await asyncio.sleep(0.05)

    assert len(downstream.calls) == 0
    assert swarm.status(blocked["subagent_id"])["status"] == "blocked"


@pytest.mark.asyncio
async def testBlockedPromotionReservesModelSlot(swarm, monkeypatch):
    releaseUpstream = asyncio.Event()
    releaseDownstream = asyncio.Event()
    upstream = makeAgent(release=releaseUpstream)
    downstream = makeAgent(model="managed-model", release=releaseDownstream)
    monkeypatch.setattr(SwarmManager, "MAX_CONCURRENT_PER_MODEL", 1)
    dep, blocked = await registerBlocked(swarm, upstream, downstream, monkeypatch)

    releaseUpstream.set()
    assert await waitUntil(lambda: swarm.status(dep["subagent_id"])["status"] == "completed")
    assert await waitUntil(lambda: swarm.status(blocked["subagent_id"])["status"] == "running")
    assert swarm._model_active.get("managed-model") == 1

    releaseDownstream.set()
    assert await waitUntil(lambda: swarm.status(blocked["subagent_id"])["status"] == "completed")
    assert swarm._model_active.get("managed-model", 0) == 0
