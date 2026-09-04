"""LLM providers.json 损坏防护 — 2026-09-05 配置丢失事故防回归

事故:并发写截断/半截 JSON → `_load_config` 异常分支用内置种子
**无备份直接覆盖**真实配置文件 → 用户全部服务商配置丢失
(`_make_backup` 存在但零调用,死代码)。

根因修复验收:
1. `_save_config` 必须原子写(临时文件 + os.replace),
   任何时点读者都读不到半截 JSON —— 根治并发写截断触发源;
2. `_load_config` 异常时必须先把坏文件转存 `.corrupt-<ts>.bak`
   再重建,磁盘上必须能找回原始字节 —— 永不无备份覆盖;
3. 重建后的种子文件不得早于 corrupt 备份(备份先落盘)。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from neurova.llm.provider_manager import LLMProviderManager

REAL_CONFIG = {
    "providers": [
        {
            "id": "real-provider",
            "name": "真实服务商",
            "provider": "openai",
            "base_url": "https://api.real.com/v1",
            "models": ["real-model-1", "real-model-2"],
            "enabled": True,
        }
    ],
    "default_provider_id": "real-provider",
    "updated_at": "2026-09-01T00:00:00",
}


def _write_config(path: Path, payload) -> None:
    """payload 为 str 时原样写入(用于构造半截 JSON)。"""
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_manager(tmp_path: Path) -> LLMProviderManager:
    return LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})


class TestSaveConfigAtomicWrite:
    """根因 1:并发写截断 —— _save_config 必须原子替换。"""

    def test_save_is_atomic_no_partial_file(self, tmp_path):
        """保存后目录里不得残留 .tmp 中间文件(读者永远只见完整 JSON)。"""
        cfg = tmp_path / "providers.json"
        mgr = _make_manager(tmp_path)
        mgr.add_provider(name="P1", provider="openai", base_url="https://x/v1")
        mgr._save_config()

        # JSON 完整可解析
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert any(p["id"] == "p1" for p in data["providers"])

        # 无临时文件残留
        leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == [], f"发现原子写中间文件残留: {leftovers}"

    def test_failed_save_preserves_original(self, tmp_path, monkeypatch):
        """写盘中途崩溃(进程被杀/disk full)时,原配置文件必须完好。

        事故触发源:当前 open("w") 先截断再写,中断即半截 JSON,
        下次 _load_config 异常 → 种子覆盖 → 配置全丢。
        """
        cfg = tmp_path / "providers.json"
        mgr = _make_manager(tmp_path)
        mgr.add_provider(name="Good", provider="openai", base_url="https://x/v1")
        mgr._save_config()
        good_bytes = cfg.read_bytes()

        def _boom(*a, **kw):
            raise OSError("simulated crash mid-write")

        monkeypatch.setattr("neurova.llm.provider_manager.json.dump", _boom)
        with pytest.raises(OSError):
            mgr.add_provider(name="New", provider="openai", base_url="https://x/v1")

        assert cfg.read_bytes() == good_bytes, (
            "写盘失败破坏了原配置文件(非原子写,先截断后写)"
        )


class TestLoadCorruptConfigBackup:
    """根因 2:异常分支无备份覆盖 —— 坏文件必须先转存再重建。"""

    @pytest.mark.parametrize(
        "broken_payload",
        [
            '{"providers": [{"id": "rea',  # 并发写截断(事故现场)
            json.dumps({"providers": {"deepseek": {}}}),  # 旧版 dict 格式
            "not-json-at-all",
        ],
        ids=["truncated-json", "legacy-dict-format", "garbage"],
    )
    def test_corrupt_config_backed_up_not_destroyed(self, tmp_path, broken_payload):
        """半截 JSON/旧格式/垃圾内容加载失败时,原字节必须可找回。"""
        cfg = tmp_path / "providers.json"
        _write_config(cfg, broken_payload)
        original_bytes = cfg.read_bytes()

        _make_manager(tmp_path)  # 触发 _load_config 异常分支

        # 磁盘上必须存在 corrupt 备份,且字节与原始坏文件一致
        backups = list(tmp_path.glob("providers.json.corrupt-*.bak"))
        assert backups, "异常分支未转存 corrupt 备份,真实配置被直接覆盖"
        assert len(backups) == 1
        assert backups[0].read_bytes() == original_bytes, (
            "corrupt 备份内容与原始坏文件不一致"
        )

    def test_recovered_config_preserves_original_providers(self, tmp_path):
        """合法 JSON + 坏条目混合时,好条目不得被种子清洗掉。

        (from_dict 对单个坏条目容错,load 不应因此丢弃其余真实配置。)
        """
        cfg = tmp_path / "providers.json"
        payload = {
            "providers": [
                REAL_CONFIG["providers"][0],
                {"id": "broken", "name": None},  # 构造可容错的坏条目
            ],
            "default_provider_id": "real-provider",
        }
        _write_config(cfg, payload)

        mgr = _make_manager(tmp_path)
        assert "real-provider" in mgr._providers, "好条目被异常分支清洗"

    def test_normal_save_load_roundtrip(self, tmp_path):
        """正常路径不受影响:保存→重载,配置一致。"""
        mgr = _make_manager(tmp_path)
        mgr.add_provider(
            name="DS",
            provider="openai",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat"],
        )
        reloaded = _make_manager(tmp_path)
        assert any(p.name == "DS" for p in reloaded.list_providers())


class TestLegacyFieldTolerance:
    """根因 3:from_dict 对未知/已废弃字段零容错 —— 一个 metadata 键
    曾让整份配置加载炸进异常分支(2026-09-05 事故原始触发点)。
    验收:未知字段忽略告警,合法服务商全部加载。"""

    def test_legacy_unknown_fields_do_not_break_load(self, tmp_path):
        cfg = tmp_path / "providers.json"
        _write_config(cfg, {
            "providers": [
                {
                    "id": "legacy",
                    "name": "旧版字段服务商",
                    "provider": "openai",
                    "base_url": "https://x/v1",
                    "models": ["m1"],
                    # 旧版本字段(现 ProviderConfig 已移除)
                    "metadata": {"foo": "bar"},
                    "weight": 1.0,
                    "health_check_interval": 300,
                    "consecutive_failures": 0,
                }
            ],
            "default_provider_id": "legacy",
        })
        mgr = _make_manager(tmp_path)
        assert "legacy" in mgr._providers
        assert mgr._providers["legacy"].models == ["m1"]
        assert mgr._default_provider_id == "legacy"

    def test_full_legacy_file_loads_all_providers(self, tmp_path):
        """与真实恢复数据同构:多条带旧字段的服务商全部加载。"""
        cfg = tmp_path / "providers.json"
        provs = []
        for i in range(3):
            provs.append({
                "id": f"p{i}", "name": f"P{i}", "provider": "openai",
                "base_url": "https://x/v1", "models": [f"m{i}"],
                "metadata": {}, "health_check_interval": 300,
                "health_status": "unknown", "total_requests": 0,
            })
        _write_config(cfg, {"providers": provs, "default_provider_id": "p0"})
        mgr = _make_manager(tmp_path)
        assert set(mgr._providers) >= {"p0", "p1", "p2"}
