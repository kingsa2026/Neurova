# -*- coding: utf-8 -*-
"""child_env 注入 run 级凭据测试（C4：外部成员子进程身份绑定）。

覆盖：提供 run_credential_context → env 注入 NEUROVA_RUN_CREDENTIAL 且
验签通过（run/tenant 正确）；None → 不含该键（向后兼容，行为不变）；
上下文缺参 → 诚实抛错（fail-closed，不静默发放无绑定进程）。
"""
import pytest

from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.security.run_identity import verifyRunCredential


@pytest.fixture(autouse=True)
def _fixedJwtSecret(monkeypatch):
    monkeypatch.setenv("NEUROVA_JWT_SECRET", "child-env-identity-test-0123456789abcdef")
    yield


def testCredentialContextInjectsVerifiableToken():
    env = buildChildEnvironment(
        {},
        run_credential_context={"run_id": "run-7", "tenant_id": "tenant-b"},
    )
    token = env.get("NEUROVA_RUN_CREDENTIAL")
    assert isinstance(token, str) and token
    assert verifyRunCredential(token) == {"run_id": "run-7", "tenant_id": "tenant-b"}


def testNoneContextKeepsEnvUnchanged():
    env = buildChildEnvironment({"MY_EXTRA": "1"})
    assert "NEUROVA_RUN_CREDENTIAL" not in env
    assert env["MY_EXTRA"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def testDefaultCallStillInjectsEncodingOnly():
    env = buildChildEnvironment()
    assert "NEUROVA_RUN_CREDENTIAL" not in env


def testIncompleteContextFailsClosed():
    with pytest.raises(ValueError):
        buildChildEnvironment({}, run_credential_context={"run_id": ""})
    with pytest.raises(ValueError):
        buildChildEnvironment({}, run_credential_context={"tenant_id": "tenant-b"})
