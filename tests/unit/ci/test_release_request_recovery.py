# -*- coding: utf-8 -*-
"""P2-26：发布请求有界、首写前读详情、失败清理与重跑对账。"""
import importlib.util
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "create_github_release_recovery", PROJECT_ROOT / "create_github_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class FakeGitHub:
    """只替代外部 HTTP；发布脚本的编排、清理与重跑逻辑全部真实执行。"""

    def __init__(self, *, commit_timeout=False, commit_status=200, fail_ref=False,
                 fail_release=False, existing=False):
        self.commit_timeout = commit_timeout
        self.commit_status = commit_status
        self.fail_ref = fail_ref
        self.fail_release = fail_release
        self.existing = existing
        self.tag = {"sha": "tag-sha", "object": {"sha": "commit-sha"}} if existing else None
        self.ref = {"object": {"sha": "tag-sha"}} if existing else None
        self.release = {"html_url": "https://example.invalid/release", "tag_name": "v1.0.0"} if existing else None
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs.get("timeout") is not None, "所有 GitHub 请求必须有界超时"
        path = url.split("/repos/kingsa2020/Neurova", 1)[-1]
        if method == "GET" and path.startswith("/commits?"):
            return FakeResponse(200, [{"sha": "commit-sha", "commit": {"message": "修复发布", "committer": {"date": "now"}}}])
        if method == "GET" and path == "/commits/commit-sha":
            if self.commit_timeout:
                raise requests.exceptions.Timeout("detail timeout")
            return FakeResponse(self.commit_status, {"commit": {"message": "修复发布"}})
        if method == "GET" and path == "/git/ref/tags/v1.0.0":
            return FakeResponse(200, self.ref) if self.ref else FakeResponse(404)
        if method == "GET" and path == "/releases/tags/v1.0.0":
            return FakeResponse(200, self.release) if self.release else FakeResponse(404)
        if method == "GET" and path == "/git/tags/tag-sha":
            return FakeResponse(200, self.tag)
        if method == "POST" and path == "/git/tags":
            self.tag = {"sha": "tag-sha", "object": {"sha": "commit-sha"}}
            return FakeResponse(201, self.tag)
        if method == "POST" and path == "/git/refs":
            if self.fail_ref:
                return FakeResponse(422)
            self.ref = {"ref": "refs/tags/v1.0.0", "object": {"sha": kwargs["json"]["sha"]}}
            return FakeResponse(201, self.ref)
        if method == "POST" and path == "/releases":
            if self.fail_release:
                return FakeResponse(500)
            self.release = {"html_url": "https://example.invalid/release", "tag_name": "v1.0.0"}
            return FakeResponse(201, self.release)
        if method == "DELETE" and path == "/git/refs/tags/v1.0.0":
            self.ref = None
            return FakeResponse(204)
        if method == "DELETE" and path == "/git/tags/tag-sha":
            self.tag = None
            return FakeResponse(204)
        raise AssertionError(f"未建模请求: {method} {path}")


def _install(monkeypatch, module, fake):
    monkeypatch.setattr(module, "get_github_token", lambda: "token")
    monkeypatch.setattr(module, "NEXT_VERSION", "v1.0.0")
    monkeypatch.setattr(module.requests, "get", lambda url, **kw: fake.request("GET", url, **kw))
    monkeypatch.setattr(module.requests, "post", lambda url, **kw: fake.request("POST", url, **kw))
    monkeypatch.setattr(module.requests, "delete", lambda url, **kw: fake.request("DELETE", url, **kw))


@pytest.mark.parametrize("failure", [{"commit_timeout": True}, {"commit_status": 500}])
def test_commit_detail_failure_precedes_every_write(monkeypatch, failure):
    module = _load_script()
    fake = FakeGitHub(**failure)
    _install(monkeypatch, module, fake)
    assert module.main() != 0
    methods = [method for method, _, _ in fake.calls]
    assert methods == ["GET", "GET"]
    assert "/commits/commit-sha" in fake.calls[-1][1]
    assert fake.tag is None and fake.ref is None and fake.release is None


def test_ref_failure_rolls_back_tag_and_rerun_reconciles(monkeypatch):
    module = _load_script()
    fake = FakeGitHub(fail_ref=True)
    _install(monkeypatch, module, fake)
    assert module.main() != 0
    assert fake.tag is None and fake.ref is None
    assert any(method == "DELETE" for method, _, _ in fake.calls)

    # 模拟服务端已收到写入但响应丢失：重跑先 GET 对账，不盲重发。
    fake.fail_ref = False
    fake.tag = {"sha": "tag-sha", "object": {"sha": "commit-sha"}}
    fake.ref = {"object": {"sha": "tag-sha"}}
    fake.calls.clear()
    assert module.main() == 0
    posts = [url for method, url, _ in fake.calls if method == "POST"]
    assert posts == [f"{module.API_ROOT if hasattr(module, 'API_ROOT') else 'https://api.github.com'}/repos/kingsa2020/Neurova/releases"]
    assert len([c for c in fake.calls if c[0] == "GET"]) == 5


def test_release_failure_rolls_back_ref_and_tag(monkeypatch):
    module = _load_script()
    fake = FakeGitHub(fail_release=True)
    _install(monkeypatch, module, fake)
    assert module.main() != 0
    assert fake.tag is None and fake.ref is None
    deleted = [url for method, url, _ in fake.calls if method == "DELETE"]
    assert len(deleted) == 2


def test_existing_release_is_reused_without_duplicate_writes(monkeypatch):
    module = _load_script()
    fake = FakeGitHub(existing=True)
    _install(monkeypatch, module, fake)
    assert module.main() == 0
    assert not [c for c in fake.calls if c[0] in ("POST", "DELETE")]
