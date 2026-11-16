"""S2 安全批：技能市场安装链路径穿越闸（审计 2026-11-16 P1-15）。

`hub_client._download_and_extract_skill` 用 skill_name 直拼
`_installed_dir / skill_name`，而 name 来自远端市场数据或 URL 推断——
`..`/分隔符即越界写。修复：校验下沉为 `hub_client.install_skill` 入口统一闸
（skill_service 的 URL 安装分支经同一入口被覆盖）。
"""

import threading

import pytest

from neurova.core.logger import get_logger
from neurova.skills.hub_client import RemoteSkill, SkillHubClient
from neurova.skills.models import SkillSource

PUBLIC_ZIP = "http://1.2.3.4/skillpack.zip"


def _skill(name):
    return RemoteSkill(
        name=name,
        source=SkillSource.GITHUB,
        url="http://1.2.3.4/repo",
        download_url=PUBLIC_ZIP,
    )


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    client = SkillHubClient(base_dir=str(tmp_path / "hub"))
    # 记录下载调用：非法名必须在下载之前被闸拦住（calls 为空）；
    # 合法名则应走到下载环节（calls 非空）。
    calls = []
    monkeypatch.setattr(
        "neurova.skills.hub_client._http_fetch",
        lambda url, *a, **k: calls.append(url) or (_ for _ in ()).throw(OSError("download blocked in test")),
    )
    client._test_fetch_calls = calls
    return client


class TestHubInstallNameGate:
    @pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", "sub/..", ".hidden"])
    def test_unsafe_names_refused_before_download(self, hub, tmp_path, bad):
        ok = hub.install_skill(_skill(bad))
        assert ok is False, f"非法名 {bad!r} 应被闸拒绝"
        assert hub._test_fetch_calls == [], (
            f"非法名 {bad!r} 未被入口闸拦住，已进入下载环节：{hub._test_fetch_calls}"
        )
        installed = list((tmp_path / "hub" / "installed").iterdir())
        assert installed == [], f"非法名 {bad!r} 仍留下了落盘物：{installed}"

    def test_valid_name_passes_gate_then_fails_on_download_only(self, hub, tmp_path):
        """合法名不被闸误伤——必须放行到下载环节（下载在测试里被 mock 掉）。"""
        ok = hub.install_skill(_skill("ok-skill"))
        assert ok is False, "下载被 mock 拒绝，安装应失败"
        assert len(hub._test_fetch_calls) == 1, (
            f"合法名被闸误伤（未走到下载）：{hub._test_fetch_calls}"
        )
        assert not (tmp_path / "hub" / "installed" / "ok-skill").exists()

    def test_service_url_install_with_traversal_id_fails(self, tmp_path, monkeypatch):
        """skill_service._install_from_url（审计点 :846）显式传入穿越 skill_id
        时必须整体失败，不得落盘、不得登记。"""
        from neurova.skills.skill_service import SkillService

        svc = SkillService.__new__(SkillService)
        svc.skills_dir = tmp_path
        svc.manifest_path = tmp_path / "manifest.json"
        svc._skills = {}
        svc._logger = get_logger("test-s2")
        svc._lock = threading.RLock()
        monkeypatch.setattr(svc, "_recordArtifactAnchor", lambda *a, **k: None)
        monkeypatch.setattr(svc, "_hasArtifactBytes", lambda p: False)

        result = svc._install_from_url(PUBLIC_ZIP, skill_id="../../evil")
        assert result.get("success") is False, f"穿越 skill_id 应安装失败：{result}"

        # 登记清单不得出现该名
        assert "../../evil" not in svc._skills
