"""
远端市场源（阿里云 skills.aliyun.com / 讯飞 skill.xfyun.cn）接入测试（2026-08-31）

契约:
1. 源适配器把远端条目映射为 catalog entry（source 标记 + skill_id 命名空间防碰撞）;
2. sync_source: 远端列表 upsert 进 MarketStore（新增/版本更新/保留 admin 改动）;
3. 讯飞 slug "ns--slug" 解包（详情/下载走 /skills/{ns}/{slug} 路径）;
4. install download: zip 安全解压（zip-slip 拒绝）+ 落盘 skills_dir/source 前缀目录;
5. 上游失败降级: sync 返回错误计数不抛异常; HTTP 请求全部走注入的 opener（不打真网）。
"""

import io
import json
import os
import zipfile

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.skills import market_sources as ms
from neurova.skills.market_store import MarketStore


def _store(tmp_path):
    return MarketStore(catalog_path=tmp_path / "catalog.json")


# ── 映射契约 ──


class TestAliyunMapping:
    def test_map_entry_fields(self):
        raw = {
            "skillName": "alibabacloud-agentbay-aio-skills",
            "displayName": "AgentBay AIO 技能",
            "description": "运行/执行/评估代码",
            "categoryCode": "aiml",
            "categoryName": "人工智能与机器学习",
            "version": "0.0.1",
            "githubPath": "https://github.com/aliyun/alibabacloud-aiops-skills/tree/master/skills/aiml/agentbay/x",
            "installCount": 115,
            "updatedAt": "2026-06-05T15:42:48",
        }
        entry = ms.AliyunSkillsSource().map_entry(raw)
        assert entry["skill_id"] == "aliyun--alibabacloud-agentbay-aio-skills"
        assert entry["source"] == "aliyun"
        assert entry["name"] == "AgentBay AIO 技能"
        assert entry["category"] == "aiml"
        assert entry["version"] == "0.0.1"
        assert entry["downloads"] == 115
        assert "skills.aliyun.com" in entry["download_url"]
        assert "alibabacloud-agentbay-aio-skills" in entry["download_url"]

    def test_map_entry_defaults(self):
        entry = ms.AliyunSkillsSource().map_entry({"skillName": "x"})
        assert entry["skill_id"] == "aliyun--x"
        assert entry["version"] == "1.0.0"
        assert entry["category"] == "others"


class TestXfyunMapping:
    def test_map_entry_ns_split(self):
        raw = {
            "slug": "github--pdf",
            "displayName": "pdf",
            "summary": "PDF toolkit",
            "stats": {"downloads": 163, "stars": 2},
            "latestVersion": {"version": "20260716.080237"},
            "updatedAt": 1784188957732,
        }
        entry = ms.XfyunSkillsSource().map_entry(raw)
        assert entry["skill_id"] == "xfyun--github--pdf"
        assert entry["source"] == "xfyun"
        assert entry["name"] == "pdf"
        assert entry["author"] == "github"
        assert entry["version"] == "20260716.080237"
        assert entry["downloads"] == 163

    def test_download_url_keeps_ns_path(self):
        entry = ms.XfyunSkillsSource().map_entry({"slug": "clawhub--pdf"})
        assert entry["download_url"].endswith("/api/v1/skills/clawhub/pdf/download")

    def test_bare_slug_uses_compat_download_url(self):
        """裸 slug（无 ns 前缀）走 ClawHub 兼容下载端点（/skills/_/ 不可用）"""
        entry = ms.XfyunSkillsSource().map_entry({"slug": "teaching-aid-generator"})
        assert entry["download_url"].endswith("/api/v1/download/teaching-aid-generator")
        assert "/skills/" not in entry["download_url"]

    def test_list_params(self):
        src = ms.XfyunSkillsSource()
        assert src.list_url(0, 50).endswith("/api/v1/skills?page=0&size=50")


# ── 同步契约 ──


class _FakeStore:
    """只模拟 MarketStore 的 upsert 相关行为"""

    def __init__(self):
        self.items = {}
        self.updated = []

    def get(self, skill_id):
        return self.items.get(skill_id)

    def create(self, entry):
        self.items[entry["skill_id"]] = dict(entry)
        return dict(entry)

    def update(self, skill_id, patch):
        if skill_id not in self.items:
            return None
        self.items[skill_id].update({k: v for k, v in patch.items() if k != "skill_id"})
        self.updated.append(skill_id)
        return {"entry": self.items[skill_id], "version_changed": True}

    def remove(self, skill_id):
        return self.items.pop(skill_id, None) is not None

    def list_all(self):
        return [dict(i) for i in self.items.values()]


class TestSync:
    def test_sync_creates_and_updates(self, monkeypatch):
        raw_new = {"skillName": "s-new", "displayName": "New", "version": "1.0.0"}
        raw_v2 = {"skillName": "s-old", "displayName": "Old", "version": "2.0.0"}
        monkeypatch.setattr(
            ms.AliyunSkillsSource, "fetch_entries", lambda self: [raw_new, raw_v2]
        )
        store = _FakeStore()
        store.items["aliyun--s-old"] = {
            "skill_id": "aliyun--s-old", "source": "aliyun", "version": "1.0.0",
        }
        # 远端已消失的条目（同步后应被清理）
        store.items["aliyun--s-gone"] = {
            "skill_id": "aliyun--s-gone", "source": "aliyun", "version": "0.1.0",
        }
        result = ms.sync_source("aliyun", store)
        assert result["created"] == 1
        assert result["updated"] == 1
        assert result["removed"] == 1  # 远端消失的 source 条目被清理
        assert "aliyun--s-new" in store.items
        assert store.items["aliyun--s-old"]["version"] == "2.0.0"
        assert "aliyun--s-gone" not in store.items

    def test_sync_keeps_admin_fields(self, monkeypatch):
        """admin 本地改过的字段（rating 等）不被远端覆盖 — rating 不在同步白名单"""
        raw = {"skillName": "s1", "displayName": "S1", "version": "1.0.0"}
        monkeypatch.setattr(ms.AliyunSkillsSource, "fetch_entries", lambda self: [raw])
        store = _FakeStore()
        store.items["aliyun--s1"] = {
            "skill_id": "aliyun--s1", "source": "aliyun", "version": "0.9.0", "rating": 4.9,
        }
        ms.sync_source("aliyun", store)
        assert store.items["aliyun--s1"]["rating"] == 4.9
        assert store.items["aliyun--s1"]["version"] == "1.0.0"

    def test_sync_unknown_source_raises(self):
        with pytest.raises(ValueError):
            ms.sync_source("no-such-source", _FakeStore())

    def test_sync_upstream_failure_degrades(self, monkeypatch):
        def boom(self):
            raise OSError("network down")

        monkeypatch.setattr(ms.AliyunSkillsSource, "fetch_entries", boom)
        result = ms.sync_source("aliyun", _FakeStore())
        assert result["created"] == 0 and result["errors"] >= 1

    def test_get_source(self):
        assert isinstance(ms.get_source("aliyun"), ms.AliyunSkillsSource)
        assert isinstance(ms.get_source("xfyun"), ms.XfyunSkillsSource)
        with pytest.raises(ValueError):
            ms.get_source("nope")

    def test_list_sources(self):
        keys = {s.key for s in ms.list_sources()}
        assert {"aliyun", "xfyun"} <= keys


# ── 安装下载契约 ──


class TestInstallDownload:
    def _zip_bytes(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SKILL.md", "---\nname: t\ndescription: t\n---\nbody")
            z.writestr("references/a.md", "ref")
        return buf.getvalue()

    def test_download_and_extract(self, tmp_path, monkeypatch):
        payload = self._zip_bytes()
        monkeypatch.setattr(ms, "_http_get", lambda url: payload)
        dest = tmp_path / "skills" / "aliyun--demo"
        ok = ms.download_and_extract("aliyun--demo", "https://skills.aliyun.com/api/public/skills/demo/download", dest)
        assert ok is True
        assert (dest / "SKILL.md").read_text(encoding="utf-8").startswith("---")
        assert (dest / "references" / "a.md").exists()

    def test_download_and_extract_rejects_foreign_host(self, tmp_path):
        ok = ms.download_and_extract("x", "https://evil.example.com/skill.zip", tmp_path / "out")
        assert ok is False

    def test_extract_rejects_zip_slip(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "bad")
        dest = tmp_path / "out"
        ok = ms.extract_remote_skill_zip("x", buf.getvalue(), dest)
        assert ok is False
        assert not (tmp_path / "evil.txt").exists()

    def test_extract_rejects_oversize(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("big.bin", b"0" * (ms.MAX_SKILL_ZIP_BYTES + 1))
        dest = tmp_path / "out"
        assert ms.extract_remote_skill_zip("x", buf.getvalue(), dest) is False

    def test_extract_rejects_non_zip(self, tmp_path):
        assert ms.extract_remote_skill_zip("x", b"not a zip", tmp_path / "out") is False


# ── importer 集成：远端目录落 catalog ──


class TestImporterIntegration:
    def test_import_skill_uses_download_url(self, tmp_path, monkeypatch):
        """有 download_url 的条目安装时真实下载解压到 skills_dir"""
        from neurova.skills.market_importer import MarketImporter

        calls = []

        def fake_download(skill_id, url, dest):
            calls.append((skill_id, url, str(dest)))
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "SKILL.md").write_text("---\nname: t\n---\n", encoding="utf-8")
            return True

        monkeypatch.setattr(ms, "download_and_extract", fake_download)
        imp = MarketImporter(skills_dir=tmp_path / "skills")
        entry = {
            "skill_id": "aliyun--demo", "name": "Demo", "version": "1.0.0",
            "description": "d", "author": "a", "download_url": "https://skills.aliyun.com/api/public/skills/demo/download",
            "category": "utility", "tags": [], "rating": 0.0, "downloads": 0, "updated_at": 0,
        }
        monkeypatch.setattr(
            "neurova.skills.market_store.get_market_store",
            lambda: _FakeStoreWith([entry]),
        )
        task = imp.import_skill("aliyun--demo")
        assert task.status.value == "completed"
        assert calls and calls[0][0] == "aliyun--demo"
        assert "skills.aliyun.com" in calls[0][1]
        assert (tmp_path / "skills" / "aliyun--demo" / "SKILL.md").exists()

    def test_import_skill_no_url_falls_back_to_stub(self, tmp_path, monkeypatch):
        from neurova.skills.market_importer import MarketImporter

        monkeypatch.setattr(
            "neurova.skills.market_store.get_market_store",
            lambda: _FakeStoreWith([{"skill_id": "web-search", "name": "Web Search", "version": "1.2.0"}]),
        )
        imp = MarketImporter(skills_dir=tmp_path / "skills")
        task = imp.import_skill("web-search")
        assert task.status.value == "completed"
        assert (tmp_path / "skills" / "web-search" / "skill.json").exists()

    def test_import_skill_download_failure_marks_failed(self, tmp_path, monkeypatch):
        from neurova.skills.market_importer import MarketImporter

        monkeypatch.setattr(ms, "download_and_extract", lambda *a, **k: False)
        entry = {
            "skill_id": "aliyun--broken", "name": "Broken", "version": "1.0.0",
            "download_url": "https://skills.aliyun.com/api/public/skills/broken/download",
        }
        monkeypatch.setattr(
            "neurova.skills.market_store.get_market_store",
            lambda: _FakeStoreWith([entry]),
        )
        imp = MarketImporter(skills_dir=tmp_path / "skills")
        task = imp.import_skill("aliyun--broken")
        assert task.status.value == "failed"
        assert task.error_message


class _FakeStoreWith:
    def __init__(self, items):
        self._items = list(items)

    def list_all(self):
        return list(self._items)

    def get(self, skill_id):
        for i in self._items:
            if i.get("skill_id") == skill_id:
                return dict(i)
        return None
