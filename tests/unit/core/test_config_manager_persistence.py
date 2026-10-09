"""
test_config_manager_persistence.py — load/save 的失败语义与**错误分级**（P0-10 口径）

被测对象自 2026-10-10 起是 `neurova.core.config.ConfigManager`（统一分层配置管理器）。
原来这一套断言打在 `neurova/core/config_manager.py`（KV 简单版）上：那份实现把
「配置文件缺失/JSON 损坏」记 warning（可降级到默认值，不是事故），把「写盘失败」记
error（用户数据丢失）。两份并存属双源，按教义第 7 条比后合并——**这一格分级是简单版
比分层版强的地方**，随本批并入 `config.py::load`；本文件即它的常驻判据。

夹具不再全局 patch 标准库：写盘失败用"父路径是一个已存在的文件"这个真触发（`mkdir`
确实会抛 `NotADirectoryError`，它是 `OSError` 的子类），不可序列化用真塞进一个 `set`。
以前那种 `patch("….json.dump")` / `patch("….Path.mkdir")` 打的是进程级标准库符号，
块内任何旁路落盘都会被牵连——判据自己成了污染源。
"""
import json
from unittest.mock import patch

import pytest

from neurova.core.config import ConfigManager


class TestLoadErrorHandling:
    def test_load_handles_corrupt_json_without_crash(self, tmp_path):
        """损坏 JSON 不应崩溃，且不写入任何配置"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid json content", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        cm.load()
        assert cm.get_all() == {}

    def test_load_handles_missing_file_gracefully(self, tmp_path):
        """缺失文件应优雅返回，不抛异常"""
        cm = ConfigManager(str(tmp_path / "nonexistent.json"))
        cm.load()
        assert cm.get_all() == {}

    def test_load_logs_warning_not_error_on_corrupt_json(self, tmp_path):
        """可恢复的读取失败记 warning；把它报成 error 会让"回落默认值"看起来像事故"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        with patch("neurova.core.config.logger") as mock_logger:
            cm.load()
            assert mock_logger.warning.called, (
                "load 侧的 JSON/IO 失败必须走 warning 级——这是 KV 简单版比分层版强的那一格，"
                "本批把它并了过来")
            assert not mock_logger.error.called, (
                "同一场失败不该既 warning 又 error：两条读数为同一个可恢复事件报警两次")

    def test_load_preserves_existing_data_on_error(self, tmp_path):
        """load 失败时应保留已存在的内存配置（失败不许把用户手上的配置抹掉）"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        cm.set("existing_key", "existing_value")
        cm.load()
        assert cm.get("existing_key") == "existing_value"


class TestSaveErrorHandling:
    def test_save_reports_error_when_parent_is_a_file(self, tmp_path):
        """父路径是个已存在的文件 ⇒ mkdir 真抛 OSError：不得崩，且必须 error 级"""
        blocker = tmp_path / "blocker.json"
        blocker.write_text("{}", encoding="utf-8")
        cm = ConfigManager(str(blocker / "nested" / "config.json"))
        cm.set("key", "value")
        with patch("neurova.core.config.logger") as mock_logger:
            cm.save()
            assert mock_logger.error.called, "写盘失败＝用户数据丢失，必须 error 级"

    def test_save_reports_error_on_unserializable_value(self, tmp_path):
        """值不可 JSON 序列化 ⇒ 真触发 TypeError：不得崩，且必须 error 级点名数据没了"""
        cm = ConfigManager(str(tmp_path / "config.json"))
        cm.set("bad_value", {"not", "serializable"})
        with patch("neurova.core.config.logger") as mock_logger:
            cm.save()
            assert mock_logger.error.called

    def test_save_creates_parent_directory(self, tmp_path):
        """save 应自动创建父目录，并写出真 JSON（不是 repr）"""
        nested_path = tmp_path / "deep" / "nested" / "config.json"
        cm = ConfigManager(str(nested_path))
        cm.set("key", "value")
        cm.save()
        assert nested_path.exists()
        assert json.loads(nested_path.read_text(encoding="utf-8"))["key"] == "value"

    def test_saved_bytes_are_readable_back_in_a_new_process_object(self, tmp_path):
        """落盘事实要在**新实例**上成立——同一实例的内存读数不算往返证据"""
        path = tmp_path / "round_trip.json"
        writer = ConfigManager(str(path))
        writer.set("k", "v")
        writer.set("n", 42)
        writer.save()

        reader = ConfigManager(str(path))
        reader.load()
        assert reader.get("k") == "v"
        assert reader.get("n") == 42
