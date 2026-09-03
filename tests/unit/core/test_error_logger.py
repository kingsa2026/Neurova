"""
测试：error_logger — 统一错误日志模块
"""

import json
import os
from neurova.error_logger import write_frontend_errors, read_all_errors, clear_errors


class TestWriteFrontendErrors:
    """测试写入前端错误日志"""

    def test_write_empty_list(self, tmp_path):
        """空列表写入应返回 0"""
        count = write_frontend_errors([], log_dir=str(tmp_path))
        assert count == 0
        # 不应创建文件
        log_file = tmp_path / "all_errors.log"
        assert not log_file.exists()

    def test_write_single_error(self, tmp_path):
        """写入单条错误"""
        errors = [{"type": "javascript", "message": "test error"}]
        count = write_frontend_errors(errors, log_dir=str(tmp_path))
        assert count == 1

        log_file = tmp_path / "all_errors.log"
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["source"] == "frontend"
        assert data["type"] == "javascript"
        assert data["message"] == "test error"

    def test_write_multiple_errors(self, tmp_path):
        """写入多条错误"""
        errors = [
            {"type": "js", "message": "err1"},
            {"type": "network", "message": "err2"},
        ]
        count = write_frontend_errors(errors, log_dir=str(tmp_path))
        assert count == 2

        lines = (tmp_path / "all_errors.log").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_write_appends_to_existing(self, tmp_path):
        """追加写入已有文件"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text('{"source":"frontend","type":"old","message":"old"}\n', encoding="utf-8")

        write_frontend_errors([{"type": "new", "message": "new"}], log_dir=str(tmp_path))
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["message"] == "old"
        assert json.loads(lines[1])["message"] == "new"

    def test_write_with_full_fields(self, tmp_path):
        """完整字段写入"""
        errors = [{
            "type": "react",
            "message": "Cannot read property",
            "stack": "at Component\n  at App",
            "url": "http://localhost:3000/",
            "componentName": "Dashboard",
            "userAgent": "Mozilla/5.0",
            "timestamp": "2025-01-01T00:00:00",
        }]
        write_frontend_errors(errors, log_dir=str(tmp_path))

        data = json.loads((tmp_path / "all_errors.log").read_text(encoding="utf-8"))
        assert data["source"] == "frontend"
        assert data["timestamp"] == "2025-01-01T00:00:00"
        assert data["level"] == "ERROR"
        assert data["type"] == "react"
        assert data["message"] == "Cannot read property"
        assert data["stack"] == "at Component\n  at App"
        assert data["url"] == "http://localhost:3000/"
        assert data["component"] == "Dashboard"
        assert data["user_agent"] == "Mozilla/5.0"

    def test_write_creates_log_dir(self, tmp_path):
        """如果日志目录不存在应自动创建"""
        nested = tmp_path / "a" / "b" / "c"
        write_frontend_errors([{"message": "test"}], log_dir=str(nested))
        assert nested.exists()

    def test_write_empty_string_fields(self, tmp_path):
        """空字符串字段"""
        write_frontend_errors([{"type": "", "message": ""}], log_dir=str(tmp_path))
        data = json.loads((tmp_path / "all_errors.log").read_text(encoding="utf-8"))
        assert data["type"] == ""
        assert data["message"] == ""


class TestReadAllErrors:
    """测试读取错误日志"""

    def test_read_empty_file(self, tmp_path):
        """文件不存在应返回空列表"""
        errors = read_all_errors(log_dir=str(tmp_path))
        assert errors == []

    def test_read_single_line(self, tmp_path):
        """读取单条日志"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text('{"source":"frontend","type":"js","message":"test"}\n', encoding="utf-8")
        errors = read_all_errors(log_dir=str(tmp_path))
        assert len(errors) == 1
        assert errors[0]["type"] == "js"

    def test_read_multiple_lines(self, tmp_path):
        """读取多条日志"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text(
            '{"msg":"1"}\n{"msg":"2"}\n{"msg":"3"}\n',
            encoding="utf-8",
        )
        errors = read_all_errors(log_dir=str(tmp_path))
        assert len(errors) == 3

    def test_read_skips_bad_lines(self, tmp_path):
        """无效 JSON 行应跳过"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text(
            '{"valid": true}\nnot json\n{"also valid": true}\n',
            encoding="utf-8",
        )
        errors = read_all_errors(log_dir=str(tmp_path))
        assert len(errors) == 2

    def test_read_empty_lines_skipped(self, tmp_path):
        """空行应跳过"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text('{"a":1}\n\n\n{"b":2}\n', encoding="utf-8")
        errors = read_all_errors(log_dir=str(tmp_path))
        assert len(errors) == 2

    def test_read_after_write(self, tmp_path):
        """写入后读取应一致"""
        write_frontend_errors([
            {"message": "hello"},
            {"message": "world"},
        ], log_dir=str(tmp_path))
        errors = read_all_errors(log_dir=str(tmp_path))
        assert len(errors) == 2
        assert errors[0]["message"] == "hello"
        assert errors[1]["message"] == "world"


class TestClearErrors:
    """测试清空错误日志"""

    def test_clear_existing_file(self, tmp_path):
        """清空已有文件"""
        log_file = tmp_path / "all_errors.log"
        log_file.write_text("data\n", encoding="utf-8")
        result = clear_errors(log_dir=str(tmp_path))
        assert result is True
        assert log_file.read_text(encoding="utf-8") == ""

    def test_clear_nonexistent_file(self, tmp_path):
        """清空不存在的文件"""
        result = clear_errors(log_dir=str(tmp_path))
        assert result is True

    def test_clear_after_write(self, tmp_path):
        """写入后清空"""
        write_frontend_errors([{"message": "x"}], log_dir=str(tmp_path))
        assert len(read_all_errors(log_dir=str(tmp_path))) == 1
        clear_errors(log_dir=str(tmp_path))
        assert len(read_all_errors(log_dir=str(tmp_path))) == 0
