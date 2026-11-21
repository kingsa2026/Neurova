# -*- coding: utf-8 -*-
"""C4 接线：run 级身份凭据从 swarm 装配 → 执行体 → client → child_env 全链。

- NeuacpStdioExecutor/NeuacpPluginExecutor 构造时接 run_tenant_id，
  start(ctx) 用 ctx.metadata["subagent_id"]+租户绑出凭据上下文并推给 client；
- NeuacpClient._childEnvironment 把上下文交给 buildChildEnvironment 注入
  NEUROVA_RUN_CREDENTIAL（真签发链验签通过）；
- 无上下文时 env 不含该键（向后兼容）。
"""
import asyncio
import sys
from pathlib import Path

from neurova.agent.neuacp.acp_client import NeuacpClient
from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.plugin_executor import NeuacpPluginExecutor

_FAKE = Path(__file__).resolve().parent / "fake_acp_agent.py"


def test_client_child_env_injects_run_credential():
    client = NeuacpClient(
        [sys.executable, str(_FAKE)],
        run_credential_context={"run_id": "run-r1", "tenant_id": "tenant-r1"},
    )
    env = client._childEnvironment()
    assert env.get("NEUROVA_RUN_CREDENTIAL")
    from neurova.security.run_identity import verifyRunCredential

    verified = verifyRunCredential(env["NEUROVA_RUN_CREDENTIAL"])
    assert verified == {"run_id": "run-r1", "tenant_id": "tenant-r1"}


def test_client_without_context_keeps_env_clean():
    client = NeuacpClient([sys.executable, str(_FAKE)])
    env = client._childEnvironment()
    assert "NEUROVA_RUN_CREDENTIAL" not in env


def test_client_setter_updates_context():
    client = NeuacpClient([sys.executable, str(_FAKE)])
    client.setRunCredentialContext({"run_id": "run-r2", "tenant_id": "tenant-r2"})
    env = client._childEnvironment()
    from neurova.security.run_identity import verifyRunCredential

    assert verifyRunCredential(env["NEUROVA_RUN_CREDENTIAL"])["run_id"] == "run-r2"


def test_stdio_executor_start_binds_credential_context():
    executor = NeuacpStdioExecutor(
        [sys.executable, str(_FAKE)], run_tenant_id="tenant-x")
    ctx = NeuacpSessionContext(
        member_session_id="ms-1", task_text="任务",
        metadata={"subagent_id": "run-9"})
    try:
        asyncio.run(executor.start(ctx))
        assert executor._client._run_credential_context == {
            "run_id": "run-9", "tenant_id": "tenant-x"}
    finally:
        client = executor._client
        if client is not None:
            client.terminate()


def test_plugin_executor_start_stores_credential_context():
    executor = NeuacpPluginExecutor(
        [sys.executable, str(_FAKE)], run_tenant_id="tenant-y")
    ctx = NeuacpSessionContext(
        member_session_id="ms-2", task_text="任务",
        metadata={"subagent_id": "run-8"})
    asyncio.run(executor.start(ctx))
    assert executor._run_credential_context == {
        "run_id": "run-8", "tenant_id": "tenant-y"}
