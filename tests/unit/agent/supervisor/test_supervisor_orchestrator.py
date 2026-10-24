# -*- coding: utf-8 -*-
"""Supervisor-Worker：扇出、失败隔离、重试、幂等、RRF 聚合、MQTT 契约。"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from neurova.agent.protocols.acp_runtime import ACPRuntime
from neurova.agent.supervisor import (
    InProcessWorkerBus,
    MqttWorkerBus,
    SupervisorBusError,
    SupervisorOrchestrator,
    SupervisorTask,
)


@pytest.fixture
def runtime():
    return ACPRuntime()


@pytest.fixture
def bus(runtime):
    return InProcessWorkerBus(runtime)


def _task(taskId, workerId="", retries=1, deadline=2.0):
    return SupervisorTask(
        task_id=taskId, role="retrieve", payload={"query": "alpha"},
        worker_id=workerId, deadline=deadline, max_retries=retries,
    )


class TestOrchestration:
    @pytest.mark.asyncio
    async def testFanOutAndRrfAggregate(self, bus):
        bus.register("worker-a", lambda task: {
            "success": True, "items": [{"id": "d1", "score": 0.9}],
        })
        bus.register("worker-b", lambda task: {
            "success": True,
            "items": [{"id": "d1", "score": 0.8}, {"id": "d2", "score": 0.7}],
        })
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch(
            [_task("t1", "worker-a"), _task("t2", "worker-b")]
        )

        assert report["success"] is True
        assert [t["task_id"] for t in report["tasks"]] == ["t1", "t2"]
        assert {row["id"] for row in report["aggregate"]} == {"d1", "d2"}
        assert report["aggregate"][0]["id"] == "d1"
        assert {t["trace_id"] for t in report["tasks"]} == {report["trace_id"]}

    @pytest.mark.asyncio
    async def testFailureIsIsolated(self, bus):
        def broken(task):
            raise RuntimeError("worker down")

        bus.register("worker-ok", lambda task: {
            "success": True, "items": [{"id": "d1", "score": 1.0}],
        })
        bus.register("worker-bad", broken)
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch([
            _task("t1", "worker-ok"), _task("t2", "worker-bad"),
        ])

        assert report["success"] is False
        byId = {t["task_id"]: t for t in report["tasks"]}
        assert byId["t1"]["success"] is True
        assert byId["t2"]["success"] is False
        assert "worker down" in byId["t2"]["error"]
        assert [row["id"] for row in report["aggregate"]] == ["d1"]

    @pytest.mark.asyncio
    async def testRetryThenSuccess(self, bus):
        calls = {"n": 0}

        def flaky(task):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return {"success": True, "items": [{"id": "d1", "score": 1.0}]}

        bus.register("worker-flaky", flaky)
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch([_task("t1", "worker-flaky", retries=1)])

        assert report["success"] is True
        assert report["tasks"][0]["attempts"] == 2
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def testIdempotentReplayByTaskId(self, bus):
        calls = {"n": 0}

        def handler(task):
            calls["n"] += 1
            return {"success": True, "items": [{"id": "d1", "score": 1.0}]}

        bus.register("worker-a", handler)
        orchestrator = SupervisorOrchestrator(bus)

        first = await orchestrator.dispatch([_task("t1", "worker-a")])
        second = await orchestrator.dispatch([_task("t1", "worker-a")])

        assert calls["n"] == 1
        assert second["tasks"][0]["replayed"] is True
        assert second["aggregate"] == first["aggregate"]

    @pytest.mark.asyncio
    async def testDeadlineFailsOnlyThatTask(self, bus):
        async def slow(task):
            await asyncio.sleep(0.3)
            return {"success": True, "items": [{"id": "late", "score": 1.0}]}

        bus.register("worker-slow", slow)
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch([
            _task("t1", "worker-slow", retries=0, deadline=0.05),
        ])

        assert report["success"] is False
        assert report["tasks"][0]["error"] in ("timeout_or_unavailable", "deadline_exceeded")
        assert report["aggregate"] == []

    @pytest.mark.asyncio
    async def testNoWorkerIsHonestError(self, bus):
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch([_task("t1")])

        assert report["success"] is False
        assert report["tasks"][0]["error"] == "no_worker_assigned"

    @pytest.mark.asyncio
    async def testWorkersRotateWhenNotAssigned(self, bus):
        seen = []

        def handler(name):
            def _call(task):
                seen.append(name)
                return {"success": True, "items": []}
            return _call

        bus.register("w1", handler("w1"))
        bus.register("w2", handler("w2"))
        orchestrator = SupervisorOrchestrator(bus)

        await orchestrator.dispatch([_task("t1"), _task("t2"), _task("t3")],
                                    workers=["w1", "w2"])

        assert sorted(seen) == ["w1", "w1", "w2"]


class _FakeClient:
    def __init__(self):
        self.on_message = None
        self.published = []

    def publish(self, topic, payload, qos=1):
        self.published.append((topic, json.loads(payload)))

    def loop_stop(self):  # pragma: no cover - 仅真实客户端路径
        pass

    def disconnect(self):  # pragma: no cover
        pass


class _FakeMessage:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")


class TestMqttBus:
    @pytest.mark.asyncio
    async def testPublishAndResultContract(self):
        client = _FakeClient()
        bus = MqttWorkerBus(client=client)
        task = _task("t1", "worker-a")
        task.trace_id = "trace-1"

        pending = asyncio.create_task(bus.dispatch("worker-a", task, timeout=2.0))
        await asyncio.sleep(0)
        topic, body = client.published[0]
        assert topic == "agent/supervisor/task"
        assert body["task_id"] == "t1"
        assert body["reply_topic"] == "agent/worker/worker-a/result"
        assert body["trace_id"] == "trace-1"

        bus._onMessage(client, None, _FakeMessage({
            "task_id": "t1", "success": True,
            "items": [{"id": "d1", "score": 0.5}],
        }))
        result = await pending

        assert result.success is True
        assert result.items == [{"id": "d1", "score": 0.5}]

    @pytest.mark.asyncio
    async def testTimeoutIsReported(self):
        bus = MqttWorkerBus(client=_FakeClient())

        result = await bus.dispatch("worker-a", _task("t1", "worker-a"), timeout=0.05)

        assert result.success is False
        assert result.error == "timeout"

    @pytest.mark.asyncio
    async def testMemoryUpdateUsesOwnTopic(self):
        client = _FakeClient()
        bus = MqttWorkerBus(client=client)

        bus.publishMemoryUpdate({"session_id": "s1"})

        assert client.published[0][0] == "agent/memory/update"

    def testMissingPahoIsHonestConfigError(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "paho", None)
        monkeypatch.setitem(sys.modules, "paho.mqtt", None)
        monkeypatch.setitem(sys.modules, "paho.mqtt.client", None)

        with pytest.raises(SupervisorBusError) as exc:
            MqttWorkerBus()._ensureClient()

        assert exc.value.kind == "dependency_missing"


class TestBusFromEnv:
    def testDefaultIsInProcess(self, monkeypatch):
        from neurova.agent.supervisor import buildWorkerBus

        monkeypatch.delenv("NEUROVA_AGENT_BUS", raising=False)

        assert isinstance(buildWorkerBus(runtime=ACPRuntime()), InProcessWorkerBus)

    def testMqttModeUsesBrokerEnv(self, monkeypatch):
        from neurova.agent.supervisor import buildWorkerBus

        monkeypatch.setenv("NEUROVA_AGENT_BUS", "mqtt")
        monkeypatch.setenv("NEUROVA_MQTT_HOST", "broker.local")
        monkeypatch.setenv("NEUROVA_MQTT_PORT", "1884")

        bus = buildWorkerBus()

        assert isinstance(bus, MqttWorkerBus)
        assert bus._host == "broker.local"
        assert bus._port == 1884

    def testUnknownModeIsHonest(self, monkeypatch):
        from neurova.agent.supervisor import buildWorkerBus

        monkeypatch.setenv("NEUROVA_AGENT_BUS", "carrier-pigeon")

        with pytest.raises(SupervisorBusError) as exc:
            buildWorkerBus()

        assert exc.value.kind == "invalid_mode"


class _MemoryBus:
    def __init__(self):
        self.memory = []

    async def dispatch(self, workerId, task, timeout):
        from neurova.agent.supervisor import WorkerResult

        return WorkerResult(
            task_id=task.task_id, worker_id=workerId, success=True,
            items=[{"id": "d1", "score": 1.0}],
        )

    def publishMemoryUpdate(self, payload):
        self.memory.append(payload)


class TestMemoryUpdateBroadcast:
    @pytest.mark.asyncio
    async def testMqttCapableBusGetsSummary(self):
        bus = _MemoryBus()
        orchestrator = SupervisorOrchestrator(bus)

        report = await orchestrator.dispatch([_task("t1", "w1")])

        assert bus.memory == [{
            "trace_id": report["trace_id"],
            "success": True,
            "task_count": 1,
            "document_ids": ["d1"],
        }]


class TestDurableIdempotency:
    @pytest.mark.asyncio
    async def testResultSurvivesNewOrchestratorAndLedgerReopen(self, runtime, tmp_path):
        from neurova.agent.supervisor import SupervisorTaskLedger

        calls = {"n": 0}

        def handler(task):
            calls["n"] += 1
            return {"success": True, "items": [{"id": "d1", "score": 1.0}]}

        bus = InProcessWorkerBus(runtime)
        bus.register("worker-a", handler)
        path = str(tmp_path / "tasks.db")
        ledger = SupervisorTaskLedger(path)
        first = await SupervisorOrchestrator(bus, ledger=ledger).dispatch(
            [_task("durable-1", "worker-a")]
        )
        ledger.close()

        reopened = SupervisorTaskLedger(path)
        second = await SupervisorOrchestrator(bus, ledger=reopened).dispatch(
            [_task("durable-1", "worker-a")]
        )
        reopened.close()

        assert calls["n"] == 1
        assert second["tasks"][0]["replayed"] is True
        assert second["aggregate"] == first["aggregate"]

    @pytest.mark.asyncio
    async def testResetClearsDurableResults(self, runtime, tmp_path):
        from neurova.agent.supervisor import SupervisorTaskLedger

        bus = InProcessWorkerBus(runtime)
        bus.register("worker-a", lambda task: {"success": True, "items": []})
        ledger = SupervisorTaskLedger(str(tmp_path / "tasks.db"))
        orchestrator = SupervisorOrchestrator(bus, ledger=ledger)

        await orchestrator.dispatch([_task("t-reset", "worker-a")])
        orchestrator.resetIdempotencyCache()
        replay = await orchestrator.dispatch([_task("t-reset", "worker-a")])
        ledger.close()

        assert replay["tasks"][0]["replayed"] is False


def testMqttBusTlsConfigReachesClient():
    class _TlsClient:
        def __init__(self):
            self.tls = None
            self.insecure = False

        def tls_set(self, ca_certs=None, certfile=None, keyfile=None):
            self.tls = (ca_certs, certfile, keyfile)

        def tls_insecure_set(self, value):
            self.insecure = bool(value)

    client = _TlsClient()
    bus = MqttWorkerBus(
        client=client, tlsCa="ca.pem", tlsCert="cert.pem",
        tlsKey="key.pem", tlsInsecure=True,
    )
    bus._ensureClient()

    assert client.tls == ("ca.pem", "cert.pem", "key.pem")
    assert client.insecure is True
