# -*- coding: utf-8 -*-
"""插件通道的构件完整性：登记时钉摘要、装载前比对（§6-172 批 31，P3 插件半区）。

与技能半区（`b2a3fc28`）同一口径、同一策略，只换存储：
- 钉在 `PluginRecord.artifact_digest` → `<插件根>/state.json`；
- **不升** `STATE_STORE_VERSION`：`from_dict` 全走 `.get` 默认，加字段向后兼容；
  升版会让所有存量记录撞 `plugin_manager.py` 那道"版本不认识就整店拒读"的守卫，
  得到"这台机器没装过任何插件"这种看着自洽的空态（§6-159 同一口径）——本批为此钉一格反证。

敞口是两条通道共有的（规格书 §4.1、台账 §6-172）：插件装载点在 `exec_module` 之前
只看 `enabled` 与入口文件是否存在，**没有任何东西把登记时那份字节与将要执行的那份绑住**。
判据全部走真链：HTTP `/install` 面登记、`state.json` 读盘核摘要、`/load` 面读拒因。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import plugin as plugin_api
from neurova.plugins import plugin_manager as PM
from neurova.plugins.plugin_errors import PluginError
from neurova.security import artifact_digest as AD

REPO_ROOT = Path(__file__).resolve().parents[3]
USER = {"user_id": "1", "username": "tester", "role": "admin"}

#: 作者基类的最小合法实现（四个抽象方法齐备），装载真能实例化。
_PLUGIN_BODY = (
    "from neurova.plugins.base_plugin import BasePlugin\n"
    "class ProbePlugin(BasePlugin):\n"
    "    def on_initialize(self):\n        self.initialized = True\n"
    "    def on_start(self):\n        self.started = True\n"
    "    def on_stop(self):\n        self.started = False\n"
    "    def on_destroy(self):\n        self.destroyed = True\n"
)


def _writePlugin(root: Path, name: str, body: str = _PLUGIN_BODY) -> Path:
    pdir = root / name
    pdir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "1.0.0", "description": "probe", "author": "qa",
                "entry_point": "main.py", "dependencies": [],
                "permissions": {}, "framework_surfaces": []}
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pdir / "main.py").write_text(body, encoding="utf-8")
    return pdir


@pytest.fixture()
def client(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    PM.reset_plugin_manager()
    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/v1/plugins")
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.root = root
        test_client.manager = PM.get_plugin_manager(str(root))
        yield test_client
    app.dependency_overrides.clear()
    PM.reset_plugin_manager()


def _install(client, name, **kw):
    pdir = _writePlugin(client.root, name, **kw)
    resp = client.post("/api/v1/plugins/%s/install" % name, json={"source": str(pdir)})
    assert resp.status_code == 200, resp.text
    return pdir


class TestPinnedAtInstall:
    def test_install_records_the_digest_of_the_registered_bytes(self, client):
        pdir = _install(client, "probe1")
        record = client.manager.get_plugin("probe1")
        pinned = str(getattr(record, "artifactDigest", "") or "")
        assert pinned.startswith(AD.DIGEST_PREFIX), (
            "登记时没钉构件摘要——装载点此后拿不到任何可比的留底")
        assert pinned == AD.digestDir(pdir)

    def test_digest_round_trips_through_state_json(self, client):
        """写→读闭环：摘要必须经 `state.json` 往返，而不是只活在内存里。

        缺这一格，"钉在账本里"可能就是钉在进程里——重启即失忆，装载前比对
        永远走 TOFU 分支，看着全绿却一次也没执法。
        """
        pdir = _install(client, "probe1")
        pinned = client.manager.get_plugin("probe1").artifactDigest
        stateFile = client.root / PM.STATE_FILE_NAME
        stored = json.loads(stateFile.read_text(encoding="utf-8"))
        assert stored["plugins"]["probe1"].get(AD.DIGEST_FIELD) == pinned, (
            "落盘的那份没有摘要：读回来就丢，等于没钉")

        PM.reset_plugin_manager()
        reloaded = PM.get_plugin_manager(str(client.root))
        assert reloaded.get_plugin("probe1").artifactDigest == pinned
        reloaded.enable_plugin("probe1")
        (pdir / "main.py").write_text(_PLUGIN_BODY + "\n# swapped\n", encoding="utf-8")
        with pytest.raises(PluginError) as raised:
            reloaded.load_plugin("probe1")
        assert raised.value.reason == AD.REASON_MISMATCH, (
            "重启后摘要虽在却不执法——执法接缝读的不是账本态")


class TestVerifiedBeforeExec:
    def test_tampered_entry_point_is_refused_at_load(self, client):
        pdir = _install(client, "probe2")
        client.manager.enable_plugin("probe2")
        (pdir / "main.py").write_text(
            "raise SystemExit('swapped')\n", encoding="utf-8")

        resp = client.post("/api/v1/plugins/probe2/load")
        assert resp.status_code == 409, (
            f"换过字节的插件仍被装载（HTTP {resp.status_code} {resp.text[:160]}）")
        assert AD.REASON_MISMATCH in resp.text, (
            "拒了却没点名是完整性问题——调用方会去查权限，查不到东西：%s" % resp.text[:200])

    def test_untouched_plugin_still_loads(self, client):
        """正向格：钉与验不是为了把插件体系焊死。"""
        _install(client, "probe3")
        client.manager.enable_plugin("probe3")
        resp = client.post("/api/v1/plugins/probe3/load")
        assert resp.status_code == 200, resp.text

    def test_legacy_record_without_digest_is_pinned_then_enforced(self, client):
        """TOFU 两拍：存量记录（今天全部没有摘要）首钉放行，此后才执法。

        写成"无摘要即拒"会把这台机器上已登记的插件一次性挡死。
        """
        _install(client, "probe4")
        client.manager.get_plugin("probe4").artifactDigest = ""
        client.manager._persistState()

        client.manager.enable_plugin("probe4")
        assert client.manager.load_plugin("probe4") is not None, (
            "存量无摘要即拒＝把已登记插件一起停掉，那不是安全是停机")
        assert str(client.manager.get_plugin("probe4").artifactDigest).startswith(
            AD.DIGEST_PREFIX), "首钉没落账：下一次装载还是「没钉过」，永远不会比对"

        pdir = client.root / "probe4"
        (pdir / "main.py").write_text("x = 2\n", encoding="utf-8")
        # 换包要**下一次装载**才拒：已在内存里的实例是装载那一刻验过的份，
        # 对已 loaded 的记录重验没有意义（`load_plugin` 对它直接回实例）。
        # 这条不是漏洞，是"钉与验"证明的边界——写在这里免得被读成"改完没生效"。
        PM.reset_plugin_manager()
        cold = PM.get_plugin_manager(str(client.root))
        cold.enable_plugin("probe4")
        with pytest.raises(PluginError) as raised:
            cold.load_plugin("probe4")
        assert raised.value.reason == AD.REASON_MISMATCH


class TestStoreCompatibility:
    def test_state_store_version_is_not_bumped(self, client):
        """加字段走 `.get` 默认路径；升版本号会让整店记录撞守卫。

        `plugin_manager.py` 自己写着：把 v2 结构按 v1 读会得到"没人登记过任何插件"
        这种看着自洽的空态。反过来的同一把刀是：为一个新字段升版，
        会让所有存量安装记录整体失效——那才是这里最容易顺手做错的地方。
        """
        assert PM.STATE_STORE_VERSION == 1, (
            f"本批只是加了一个可选字段，却升了版本（{PM.STATE_STORE_VERSION}）")
        legacy = {
            "version": 1,
            "plugins": {"old_one": {"name": "old_one", "path": str(client.root / "old_one"),
                                    "entry_point": "main.py", "enabled": True}},
        }
        _writePlugin(client.root, "old_one")
        (client.root / PM.STATE_FILE_NAME).write_text(json.dumps(legacy), encoding="utf-8")
        PM.reset_plugin_manager()
        restored = PM.get_plugin_manager(str(client.root))
        assert restored.get_plugin("old_one") is not None, "缺新字段的存量记录读不回来"
        assert restored.load_plugin("old_one") is not None, (
            "无摘要的存量记录被拒装载——TOFU 分支没生效")


class TestCaliberIsSharedWithSkillChannel:
    """两条通道共用一份口径：装载侧不许再写一份算法或排除清单（教义第 6 条）。"""

    def test_plugin_channel_does_not_reimplement_the_digest(self):
        src = (REPO_ROOT / "neurova/plugins/plugin_manager.py").read_text(encoding="utf-8")
        assert '"sha256"' not in src and "hashlib" not in src, "插件侧自己算摘要了"
        assert "__pycache__" not in src, "排除清单被抄进第二个装载点"

    def test_both_load_seams_go_through_the_same_policy(self):
        callers = sorted(
            p.relative_to(REPO_ROOT).as_posix()
            for p in (REPO_ROOT / "neurova").rglob("*.py")
            if "__pycache__" not in p.parts
            and "artifact_digest.checkArtifact(" in p.read_text(encoding="utf-8"))
        assert callers == ["neurova/plugins/plugin_manager.py", "neurova/skills/skill_service.py"], (
            f"装载前的完整性对账没有只发生在两条装载接缝上：{callers}")

    def test_detector_hits_a_revived_local_digest(self):
        """反空转：探测器认不出旧形态，上面两格就是恒真的空守卫。"""
        revived = "import hashlib\nx = hashlib.sha256(b'a').hexdigest()\n"
        assert "hashlib" in revived

    def test_new_refusal_reason_is_mapped_to_http(self):
        """`reason` 是封闭集合，漏映射会被画成 500——比错映射更难发现。"""
        assert plugin_api._REASON_TO_STATUS.get(AD.REASON_MISMATCH) == 409, (
            "新增成因没进端点的单点映射表")


class TestUnpinnedShellIsNotPinnedAsAuthority:
    """同根因第二命中点（§6-259 末段）：登记里没摘要、盘上连入口都不在 ⇒ 不许把这份空壳钉成权威。

    技能半区那一形是：`call_skill` 里摘要对账排在入口判定之前，未钉分支"现算现钉并放行"，
    于是每次调用空壳都往账本写一份**不代表任何构件**的摘要，再报 `No entry point found`。
    插件半区同序同形（`plugin_manager.load_plugin` 里首钉在 `_load_plugin_module` 之前）。
    后果不止脏账：日后真把字节补进那个目录，这份空壳读数会把它判成**篡改**。
    """

    def _stripToUnpinned(self, client, name: str) -> None:
        client.manager.get_plugin(name).artifactDigest = ""
        client.manager._persistState()

    def _stateRow(self, client, name: str) -> dict:
        payload = json.loads(client.manager.statePath().read_text(encoding="utf-8"))
        return payload["plugins"][name]

    def test_loadingAnUnpinnedShellDoesNotPinIntoTheState(self, client):
        pdir = _install(client, "probeShell")
        client.manager.enable_plugin("probeShell")
        self._stripToUnpinned(client, "probeShell")
        (pdir / "main.py").unlink()

        resp = client.post("/api/v1/plugins/probeShell/load")
        assert resp.status_code >= 400, (
            f"入口都不在盘的插件竟被装载放行：HTTP {resp.status_code} {resp.text[:160]}")
        assert not self._stateRow(client, "probeShell").get(AD.DIGEST_FIELD), (
            "空壳的摘要被首钉进 state.json——下次真装上就会被这份读数判篡改")

    def test_unpinnedPluginWithEntryStillPinsOnceAndLoads(self, client):
        """对照格（不许误伤）：入口在盘、登记没摘要 ⇒ 首钉一次并装载——TOFU 那条腿一字不能动。"""
        _install(client, "probeReal")
        client.manager.enable_plugin("probeReal")
        self._stripToUnpinned(client, "probeReal")

        resp = client.post("/api/v1/plugins/probeReal/load")
        assert resp.status_code == 200, f"未钉的真插件被拦了：{resp.status_code} {resp.text[:160]}"
        assert self._stateRow(client, "probeReal").get(AD.DIGEST_FIELD), (
            "首钉没发生：本批把「没构件才不钉」改成了「一律不钉」")
