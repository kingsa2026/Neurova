# -*- coding: utf-8 -*-
"""
P2 可选项②：JSON 结构化日志开关防回归网（NEUROVA_LOG_JSON=1）

structlog 价值落地：生产采集（Loki/ELK）直接解析 JSON 行免正则——
不引入新依赖（stdlib Formatter 子类），开关进程级（handler 首建时读取）。
"""
import json
import logging

import pytest

from neurova.core.logger import _logger_cache


class TestJsonLogFormatter:
    def test_json_mode_emits_parseable_lines(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LOG_JSON", "1")
        from neurova.core.logger import get_logger

        import io as _io

        # 清单例缓存走真实构造路径（formatter 选择逻辑被真实执行）
        monkeypatch.delitem(_logger_cache, "p2-json-probe", raising=False)
        logger = get_logger("p2-json-probe", level=logging.INFO)
        stream = _io.StringIO()
        logger.handlers[0].stream = stream
        logger.info('带"引号"的消息')

        line = stream.getvalue().strip().splitlines()[-1]
        payload = json.loads(line)  # 引号安全：必须可解析
        assert payload["level"] == "INFO"
        assert '带"引号"的消息' == payload["msg"]

    def test_text_mode_default(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_LOG_JSON", raising=False)
        from neurova.core.logger import _json_log_enabled

        assert _json_log_enabled() is False

    def test_exception_field_structured(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LOG_JSON", "1")
        from neurova.core.logger import _JsonLogFormatter

        fmt = _JsonLogFormatter()
        try:
            raise ValueError("boom-123")
        except ValueError:
            import sys

            line = fmt.format(
                logging.LogRecord("p", logging.ERROR, "p.py", 1, "failed", None, sys.exc_info())
            )
        payload = json.loads(line)
        assert payload["level"] == "ERROR"
        assert "boom-123" in payload["exc"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
