"""RS-4 RDP 直连 provider + provider 工厂（Linux GUI 容器后端已移除，Linux/macOS 走 SSH）

验收：
- RDP：从解析器/凭据分桶取端点→会话；无授权端点 fail-closed 抛错；destroy 不触碰远端
- 能接入 DesktopSessionPool（claim/release 闭环）
- build_provider：sandbox/rdp 可构造，container 已移除（未知名抛错），env 门控默认池
"""

import pytest

from neurova.computer_use.rdp_provider import RdpDirectProvider
from neurova.computer_use.session_pool import DesktopSessionPool


class TestRdpDirectProvider:
    def test_create_from_resolver(self):
        prov = RdpDirectProvider(endpoint_resolver=lambda u: {"host": "10.0.0.5", "port": 8765, "token": "tk"})
        s = prov.create("u1")
        assert s.base_url == "http://10.0.0.5:8765"
        assert s.token == "tk"

    def test_no_endpoint_fail_closed(self):
        prov = RdpDirectProvider(endpoint_resolver=lambda u: None)
        with pytest.raises(RuntimeError):
            prov.create("u1")

    def test_destroy_is_noop(self):
        prov = RdpDirectProvider(endpoint_resolver=lambda u: {"host": "h", "port": 1, "token": "t"})
        s = prov.create("u1")
        prov.destroy(s)  # 不抛、不触碰远端

    def test_default_resolver_reads_credentials(self, monkeypatch):
        class FakeStore:
            def platform_credentials(self, user, platform):
                return {"host": "192.168.1.9", "port": "8765", "token": "sec"}

        monkeypatch.setattr("neurova.web_reach.credentials.get_credential_store", lambda *a, **k: FakeStore())
        prov = RdpDirectProvider()
        s = prov.create("u1")
        assert s.base_url == "http://192.168.1.9:8765"
        assert s.token == "sec"


class TestPoolIntegration:
    def test_rdp_provider_plugs_into_pool(self):
        prov = RdpDirectProvider(endpoint_resolver=lambda u: {"host": "h1", "port": 8765, "token": "t"})
        pool = DesktopSessionPool(prov)
        s = pool.claim("u1")
        assert "h1" in s.base_url
        pool.release(s.session_id)
        assert pool.stats()["idle"] == 1


class TestProviderFactory:
    def test_build_provider_names(self):
        from neurova.computer_use.rdp_provider import RdpDirectProvider
        from neurova.computer_use.sandbox_provider import WindowsSandboxProvider
        from neurova.computer_use.session_pool import build_provider

        assert isinstance(build_provider("rdp"), RdpDirectProvider)
        assert isinstance(build_provider("sandbox"), WindowsSandboxProvider)

    def test_container_backend_removed(self):
        from neurova.computer_use.session_pool import build_provider

        with pytest.raises(ValueError):
            build_provider("container")

    def test_build_provider_unknown_raises(self):
        from neurova.computer_use.session_pool import build_provider

        with pytest.raises(ValueError):
            build_provider("bogus")

    def test_default_pool_env_gated(self, monkeypatch, tmp_path):
        from neurova.computer_use import session_pool as sp
        from neurova.core import app_settings as s

        # 隔离设置文件（无 provider 配置）——env 未设且设置为空 → 无池
        monkeypatch.setattr(
            s, "_settings_path", lambda path=None: path or (tmp_path / "app_settings.json")
        )
        sp.reset_default_desktop_pool()
        monkeypatch.delenv("NEUROVA_DESKTOP_PROVIDER", raising=False)
        assert sp.get_default_desktop_pool() is None
        monkeypatch.setenv("NEUROVA_DESKTOP_PROVIDER", "rdp")
        pool = sp.get_default_desktop_pool()
        assert pool is not None
        sp.reset_default_desktop_pool()


class TestDefaultPoolSettingsDriven:
    """desktop_provider 设置可配（安全选项卡写入 advanced 段）：
    env 显式 > 设置值 > 空=无池（sandbox/auto 档 fail-closed 语义不变）。"""

    def _isolate(self, monkeypatch, tmp_path, provider):
        from neurova.core import app_settings as s

        monkeypatch.setattr(
            s, "_settings_path", lambda path=None: path or (tmp_path / "app_settings.json")
        )
        monkeypatch.delenv("NEUROVA_DESKTOP_PROVIDER", raising=False)
        if provider is not None:
            s.save_app_settings("advanced", {"desktop_provider": provider})
        from neurova.computer_use import session_pool as sp

        sp.reset_default_desktop_pool()
        return sp

    def test_settings_provider_builds_pool(self, monkeypatch, tmp_path):
        sp = self._isolate(monkeypatch, tmp_path, "rdp")
        pool = sp.get_default_desktop_pool()
        assert pool is not None
        from neurova.computer_use.rdp_provider import RdpDirectProvider

        assert isinstance(pool._provider, RdpDirectProvider)
        sp.reset_default_desktop_pool()

    def test_empty_provider_no_pool(self, monkeypatch, tmp_path):
        sp = self._isolate(monkeypatch, tmp_path, "")
        assert sp.get_default_desktop_pool() is None

    def test_unknown_provider_fail_closed(self, monkeypatch, tmp_path):
        sp = self._isolate(monkeypatch, tmp_path, "bogus")
        assert sp.get_default_desktop_pool() is None

    def test_env_overrides_settings(self, monkeypatch, tmp_path):
        sp = self._isolate(monkeypatch, tmp_path, "rdp")
        monkeypatch.setenv("NEUROVA_DESKTOP_PROVIDER", "sandbox")
        pool = sp.get_default_desktop_pool()
        from neurova.computer_use.sandbox_provider import WindowsSandboxProvider

        assert isinstance(pool._provider, WindowsSandboxProvider)
        sp.reset_default_desktop_pool()

    def test_provider_change_rebuilds_pool(self, monkeypatch, tmp_path):
        from neurova.core import app_settings as s

        sp = self._isolate(monkeypatch, tmp_path, "rdp")
        pool_a = sp.get_default_desktop_pool()
        assert pool_a is not None
        s.save_app_settings("advanced", {"desktop_provider": "sandbox"})
        pool_b = sp.get_default_desktop_pool()
        assert pool_b is not None and pool_b is not pool_a, "改提供方须重建池，不得沿用旧后端"
        sp.reset_default_desktop_pool()
