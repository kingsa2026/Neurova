# -*- coding: utf-8 -*-
"""插件远程源：注册表、取回咽喉与安装接线（§6-390 票二乙，用户 2026-10-22 拍「开，复用市场链」）。

口径（与票一/票三同一条链）：
- **白名单在取回之前**：未注册 host、非 http(s)、重定向到别的 host 一律在发出/接受字节之前拒；
- **预算在解包那一步**：上限常量只在 `plugin_sources` 一处，透传给 `safe_extract_zip`；
- **取回即暂存**：解到 `.incoming_<hex>`（digest 的易变前缀，不进摘要），核对 manifest 名字后
  才整体挪进插件根；任何一步失败都清掉暂存，不把半个包留在插件根里；
- **装时钉摘要＋落锚文件**（§6-176/§6-388）：远程包与本地包走同一条登记与钉链，不例外；
- **来源留痕**：`state.json` 的记录里带 `install_source`（可选键，不升版本，缺省空串）。
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

import pytest

from neurova.api.endpoints import plugin as pluginApi
from neurova.plugins import plugin_manager as managerModule
from neurova.plugins import plugin_sources
from neurova.plugins.plugin_errors import PluginError
from neurova.plugins.plugin_manager import PluginManager


def _zipBytes(files, slip=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        if slip:
            archive.writestr(slip[0], slip[1])
    return buf.getvalue()


def _pluginZip(name="demo", version="1.0.0", extra=None) -> bytes:
    files = {
        "manifest.json": json.dumps({"name": name, "version": version,
                                     "entry_point": "main.py", "description": "d"}),
        "main.py": "VALUE = 1\n",
    }
    files.update(extra or {})
    return _zipBytes(files)


class _FakeResponse:
    def __init__(self, payload: bytes, finalUrl: str = "", status: int = 200):
        self._payload = payload
        self._finalUrl = finalUrl
        self.status = status

    def geturl(self):
        return self._finalUrl

    def read(self, size: int = -1):
        return self._payload[:size] if size >= 0 else self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def pluginRoot(tmp_path):
    return str(tmp_path / "plugins")


@pytest.fixture()
def manager(pluginRoot):
    return PluginManager(pluginRoot)


class TestRegistry:
    def testUnregisteredHostIsRefusedBeforeAnyNetwork(self, pluginRoot, monkeypatch):
        called = []

        def blow(*args, **kwargs):
            called.append(args)
            raise AssertionError("未注册 host 竟然发出了请求")

        monkeypatch.setattr(plugin_sources.urllib.request, "urlopen", blow)

        with pytest.raises(plugin_sources.PluginSourceError) as exc:
            plugin_sources.fetchArchive(pluginRoot, "https://evil.example/x.zip")

        assert exc.value.reason == plugin_sources.REASON_SOURCE_NOT_ALLOWED
        assert called == []

    def testRegisteringASourceAllowsOnlyThatHost(self, pluginRoot):
        assert plugin_sources.registerSource(pluginRoot, "plugins.example.com",
                                             "https://plugins.example.com/api") is True

        assert plugin_sources.isAllowedSource(pluginRoot, "https://plugins.example.com/a.zip")
        assert not plugin_sources.isAllowedSource(pluginRoot, "https://other.example/a.zip")
        assert not plugin_sources.isAllowedSource(pluginRoot, "file:///etc/passwd")
        assert plugin_sources.allowedHosts(pluginRoot) == ["plugins.example.com"]

    def testMismatchedHostAndBaseUrlIsRefused(self, pluginRoot):
        with pytest.raises(plugin_sources.PluginSourceError):
            plugin_sources.registerSource(pluginRoot, "a.example", "https://b.example/")

    def testCorruptSourceTableIsQuarantinedAndLoud(self, pluginRoot, caplog):
        root = Path(pluginRoot)
        root.mkdir(parents=True)
        (root / plugin_sources.SOURCE_FILE_NAME).write_text("{broken", encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            entries = plugin_sources.loadSources(pluginRoot)

        assert entries == []
        assert not (root / plugin_sources.SOURCE_FILE_NAME).exists()
        assert any("隔离" in rec.getMessage() or "无法解析" in rec.getMessage()
                   for rec in caplog.records), [r.getMessage() for r in caplog.records]

    def testRedirectToAnotherHostIsRefused(self, pluginRoot, monkeypatch):
        plugin_sources.registerSource(pluginRoot, "plugins.example.com",
                                      "https://plugins.example.com/")
        monkeypatch.setattr(
            plugin_sources.urllib.request, "urlopen",
            lambda *a, **k: _FakeResponse(b"PK", finalUrl="https://evil.example/x.zip"))

        with pytest.raises(plugin_sources.PluginSourceError) as exc:
            plugin_sources.fetchArchive(pluginRoot, "https://plugins.example.com/x.zip")

        assert exc.value.reason == plugin_sources.REASON_SOURCE_NOT_ALLOWED, (
            "重定向后没复查 host：白名单 host 可以 302 到任意地方")

    def testOversizePayloadIsRefused(self, pluginRoot, monkeypatch):
        plugin_sources.registerSource(pluginRoot, "plugins.example.com",
                                      "https://plugins.example.com/")
        monkeypatch.setattr(plugin_sources, "MAX_PLUGIN_ZIP_BYTES", 16)
        monkeypatch.setattr(
            plugin_sources.urllib.request, "urlopen",
            lambda *a, **k: _FakeResponse(b"x" * 17,
                                          finalUrl="https://plugins.example.com/x.zip"))

        with pytest.raises(plugin_sources.PluginSourceError) as exc:
            plugin_sources.fetchArchive(pluginRoot, "https://plugins.example.com/x.zip")

        assert exc.value.reason == plugin_sources.REASON_FETCH_TOO_LARGE


class TestRemoteInstall:
    def _allow(self, pluginRoot):
        plugin_sources.registerSource(pluginRoot, "plugins.example.com",
                                      "https://plugins.example.com/")

    def testRemoteInstallStagesExtractsRegistersAndPins(self, manager, pluginRoot,
                                                         monkeypatch):
        self._allow(pluginRoot)
        payload = _pluginZip("demo")
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda root, url: {"url": url, "host": "plugins.example.com",
                                               "bytes": payload, "size": len(payload),
                                               "fetched_at": 1.0})

        record = manager.install_remote_plugin(
            "https://plugins.example.com/demo.zip", expectedName="demo")

        assert record.name == "demo"
        installed = Path(record.path)
        assert installed.is_dir() and installed.parent == Path(pluginRoot).resolve()
        assert (installed / "manifest.json").is_file()
        assert record.artifactDigest.startswith("sha256:"), "远程包没走装时钉"
        state = json.loads((Path(pluginRoot) / "state.json").read_text(encoding="utf-8"))
        assert state["plugins"]["demo"]["install_source"] == \
            "https://plugins.example.com/demo.zip", "来源没留痕"
        assert not list(Path(pluginRoot).glob(".incoming_*")), "暂存没清"

    def testNameMismatchCleansStaging(self, manager, pluginRoot, monkeypatch):
        self._allow(pluginRoot)
        payload = _pluginZip("demo")
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda root, url: {"url": url, "host": "plugins.example.com",
                                               "bytes": payload, "size": len(payload),
                                               "fetched_at": 1.0})

        with pytest.raises(PluginError) as exc:
            manager.install_remote_plugin("https://plugins.example.com/demo.zip",
                                          expectedName="other")

        assert exc.value.reason == "name_mismatch"
        assert not list(Path(pluginRoot).glob(".incoming_*"))
        assert not (Path(pluginRoot) / "demo").exists()

    def testZipSlipIsRefusedAsArchiveUnsafe(self, manager, pluginRoot, monkeypatch):
        self._allow(pluginRoot)
        payload = _zipBytes({"manifest.json": json.dumps({"name": "demo"})},
                            slip=("../escape.py", "print(1)\n"))
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda root, url: {"url": url, "host": "plugins.example.com",
                                               "bytes": payload, "size": len(payload),
                                               "fetched_at": 1.0})

        with pytest.raises(PluginError) as exc:
            manager.install_remote_plugin("https://plugins.example.com/demo.zip",
                                          expectedName="demo")

        assert exc.value.reason == plugin_sources.REASON_ARCHIVE_UNSAFE
        assert not (Path(pluginRoot).parent / "escape.py").exists()
        assert not list(Path(pluginRoot).glob(".incoming_*"))

    def testSecondInstallOfTheSameNameIsRefused(self, manager, pluginRoot, monkeypatch):
        self._allow(pluginRoot)
        payload = _pluginZip("demo")
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda root, url: {"url": url, "host": "plugins.example.com",
                                               "bytes": payload, "size": len(payload),
                                               "fetched_at": 1.0})
        manager.install_remote_plugin("https://plugins.example.com/demo.zip",
                                      expectedName="demo")

        with pytest.raises(PluginError) as exc:
            manager.install_remote_plugin("https://plugins.example.com/demo.zip",
                                          expectedName="demo")

        assert exc.value.reason == "already_installed"


class TestHttpSemantics:
    def testEveryRemoteReasonIsMappedToHttp(self):
        for reason, expected in (
            (plugin_sources.REASON_SOURCE_NOT_ALLOWED, 403),
            (plugin_sources.REASON_FETCH_FAILED, 502),
            (plugin_sources.REASON_FETCH_TOO_LARGE, 413),
            (plugin_sources.REASON_ARCHIVE_UNSAFE, 400),
        ):
            assert pluginApi._REASON_TO_STATUS.get(reason) == expected, reason

    def testAllowlistedInstallStillGoesThroughTheSameGate(self, manager, pluginRoot,
                                                          monkeypatch):
        """远程包与本地包走同一条登记链：权限声明不合法照样拒。"""
        plugin_sources.registerSource(
            pluginRoot, "plugins.example.com", "https://plugins.example.com/")
        payload = _zipBytes({
            "manifest.json": json.dumps({
                "name": "badpermdemo", "version": "1.0.0", "entry_point": "main.py",
                "permissions": {"totally_unknown_capability": True}}),
            "main.py": "VALUE = 1\n",
        })
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda root, url: {"url": url, "host": "plugins.example.com",
                                               "bytes": payload, "size": len(payload),
                                               "fetched_at": 1.0})

        with pytest.raises(PluginError) as exc:
            manager.install_remote_plugin("https://plugins.example.com/x.zip",
                                          expectedName="badpermdemo")

        assert exc.value.reason == "invalid_permissions_declaration"
        assert not (Path(pluginRoot) / "badpermdemo").exists(), (
            "被拒的包不该留在插件根里")


class TestRemoteSourcesOverHttp:
    def _app(self, tmp_path, role):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api import auth as authModule
        from neurova.api import deps as depsModule
        from neurova.api.endpoints import plugin as pluginModule
        from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager

        root = tmp_path / "plugins"
        root.mkdir(parents=True, exist_ok=True)
        reset_plugin_manager()
        manager = get_plugin_manager(str(root))
        app = FastAPI()
        app.include_router(pluginModule.router, prefix="/api/v1/plugins")
        identity = {"user_id": "u-" + role, "username": role, "role": role}
        app.dependency_overrides[authModule.get_current_user] = lambda: dict(identity)
        app.dependency_overrides[depsModule.get_current_user] = lambda: dict(identity)
        from neurova.api.deps import require_admin
        if role == "admin":
            app.dependency_overrides[require_admin()] = lambda: dict(identity)
        return TestClient(app), manager, root

    def testRegistryWriteRequiresAdmin(self, tmp_path):
        client, _, _ = self._app(tmp_path, "user")
        r = client.put("/api/v1/plugins/remote-sources/plugins.example.com",
                       json={"baseUrl": "https://plugins.example.com/"})
        assert r.status_code in (401, 403), r.text

    def testAdminCanRegisterAndList(self, tmp_path):
        client, _, _ = self._app(tmp_path, "admin")
        put = client.put("/api/v1/plugins/remote-sources/plugins.example.com",
                         json={"baseUrl": "https://plugins.example.com/"})
        assert put.status_code == 200, put.text
        listed = client.get("/api/v1/plugins/remote-sources").json()["data"]["sources"]
        assert [e["host"] for e in listed] == ["plugins.example.com"]

    def testMismatchedBaseUrlIsRejectedOverHttp(self, tmp_path):
        client, _, _ = self._app(tmp_path, "admin")
        r = client.put("/api/v1/plugins/remote-sources/a.example",
                       json={"baseUrl": "https://b.example/"})
        assert r.status_code == 403, r.text

    def testInstallOverHttpUsesTheFetchThroat(self, tmp_path, monkeypatch):
        client, manager, root = self._app(tmp_path, "admin")
        client.put("/api/v1/plugins/remote-sources/plugins.example.com",
                   json={"baseUrl": "https://plugins.example.com/"})
        payload = _pluginZip("remote-demo")
        monkeypatch.setattr(plugin_sources, "fetchArchive",
                            lambda rootDir, url: {"url": url, "host": "plugins.example.com",
                                                  "bytes": payload, "size": len(payload),
                                                  "fetched_at": 1.0})

        r = client.post("/api/v1/plugins/remote-demo/install",
                        json={"source": "https://plugins.example.com/remote-demo.zip"})

        assert r.status_code == 200, r.text
        assert (Path(root) / "remote-demo" / "manifest.json").is_file()
        assert manager.has_plugin("remote-demo")

    def testUnregisteredHostIs403OverHttp(self, tmp_path):
        client, _, _ = self._app(tmp_path, "admin")
        r = client.post("/api/v1/plugins/whatever/install",
                        json={"source": "https://not-registered.example/x.zip"})
        assert r.status_code == 403, r.text
        assert plugin_sources.REASON_SOURCE_NOT_ALLOWED in r.text
