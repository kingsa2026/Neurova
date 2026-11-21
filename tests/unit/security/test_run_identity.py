# -*- coding: utf-8 -*-
"""run 级范围凭据纯逻辑层测试（C4：外部成员子进程身份绑定）。

覆盖：签发/验证往返、run/tenant 绑定、篡改 payload 拒绝、过期拒绝、
错密钥拒绝、缺参 fail-closed（签发侧诚实抛错、验证侧不抛返回 None）。
"""
import base64
import json
import time

import pytest

from neurova.security.run_identity import issueRunCredential, verifyRunCredential


@pytest.fixture(autouse=True)
def _fixedJwtSecret(monkeypatch):
    """测试期固定 JWT 密钥（currentJwtSecretKey 实时读环境变量）。"""
    monkeypatch.setenv("NEUROVA_JWT_SECRET", "run-identity-test-secret-0123456789abcdef")
    yield


def testRoundTripBindsRunAndTenant():
    token = issueRunCredential("run-1", "tenant-a")
    assert verifyRunCredential(token) == {"run_id": "run-1", "tenant_id": "tenant-a"}


def testDefaultTtlIs24h():
    before = time.time()
    token = issueRunCredential("run-1", "tenant-a")
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[0]))
    exp = payload["exp"]
    assert before + 86400 - 5 <= exp <= time.time() + 86400 + 5


def testDifferentPairsBindToTheirOwnValues():
    tokenA = issueRunCredential("run-1", "tenant-a")
    tokenB = issueRunCredential("run-2", "tenant-b")
    assert verifyRunCredential(tokenA) == {"run_id": "run-1", "tenant_id": "tenant-a"}
    assert verifyRunCredential(tokenB) == {"run_id": "run-2", "tenant_id": "tenant-b"}


def testTamperedPayloadRejected():
    token = issueRunCredential("run-1", "tenant-a")
    payloadB64, sig = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(payloadB64))
    payload["run_id"] = "run-attacker"
    forged = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    assert verifyRunCredential(f"{forged}.{sig}") is None


def testExpiredCredentialRejected():
    token = issueRunCredential("run-1", "tenant-a", ttl_s=-1)
    assert verifyRunCredential(token) is None


def testWrongKeyRejected(monkeypatch):
    token = issueRunCredential("run-1", "tenant-a")
    monkeypatch.setenv("NEUROVA_JWT_SECRET", "another-secret-0123456789abcdef000000")
    assert verifyRunCredential(token) is None


def testMissingParamsFailClosedOnIssue():
    with pytest.raises(ValueError):
        issueRunCredential("", "tenant-a")
    with pytest.raises(ValueError):
        issueRunCredential("run-1", "")
    with pytest.raises(ValueError):
        issueRunCredential(None, "tenant-a")
    with pytest.raises(ValueError):
        issueRunCredential("run-1", None)


def testMalformedTokenFailClosedOnVerify():
    assert verifyRunCredential(None) is None
    assert verifyRunCredential("") is None
    assert verifyRunCredential("not-a-token") is None
    assert verifyRunCredential("a.b.c") is None
    assert verifyRunCredential(".sig") is None
    # payload 段不是合法 base64url → None（不抛）
    assert verifyRunCredential("!!!not-base64###.deadbeef") is None
    # payload 段合法 base64 但不是 JSON → None（不抛）
    badJson = base64.urlsafe_b64encode(b"not-json").decode("ascii")
    assert verifyRunCredential(f"{badJson}.deadbeef") is None
