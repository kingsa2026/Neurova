# -*- coding: utf-8 -*-
"""Issue #55 P2 回归：会误导指标的假数据必须默认禁用。

现状：``neurova/analytics/collector.py`` 的 MetricsCollector 全仓无生产调用方，
且 ``_generate_mock_agent_metrics`` / ``_generate_mock_user_metrics`` 用
``random`` 造请求数/成功率/内存/CPU/token/成本——一旦被接线，仪表盘会显示
**看起来合理但完全是编的**数字。

修复：默认抛 MockMetricsDisabledError（响亮失败），显式设置
``NEUROVA_ANALYTICS_ALLOW_MOCK=1``（本地 demo/前端联调）才产出，
且产出指标带 ``metadata["mock"] is True`` 水印。
"""

import asyncio
from types import SimpleNamespace

import pytest

from neurova.analytics.collector import (
    ALLOW_MOCK_METRICS_ENV,
    MetricsCollector,
    MockMetricsDisabledError,
    mock_metrics_enabled,
)


@pytest.fixture(autouse=True)
def _no_mock_env(monkeypatch):
    monkeypatch.delenv(ALLOW_MOCK_METRICS_ENV, raising=False)
    yield


def _agent():
    return SimpleNamespace(agent_id="a1", name="A1")


def _user():
    return SimpleNamespace(user_id="u1", username="U1")


class TestMockMetricsDisabledByDefault:
    def test_env_default_is_off(self):
        assert mock_metrics_enabled() is False

    def test_agent_metrics_refused_without_optin(self):
        col = MetricsCollector()
        with pytest.raises(MockMetricsDisabledError) as exc:
            asyncio.run(col.collect_agent_metrics(_agent()))
        assert ALLOW_MOCK_METRICS_ENV in str(exc.value), (
            "错误信息必须指出开启开关，否则接线者无从下手"
        )

    def test_user_metrics_refused_without_optin(self):
        col = MetricsCollector()
        with pytest.raises(MockMetricsDisabledError):
            asyncio.run(col.collect_user_metrics(_user()))

    def test_private_generators_refuse_directly(self):
        """直接调私有生成器也不许绕过（防止"图省事"的调用方）。"""
        col = MetricsCollector()
        with pytest.raises(MockMetricsDisabledError):
            col._generate_mock_agent_metrics("a1", "A1")
        with pytest.raises(MockMetricsDisabledError):
            col._generate_mock_user_metrics("u1", "U1")


class TestMockMetricsExplicitOptIn:
    def test_env_on_allows_and_watermarks(self, monkeypatch):
        monkeypatch.setenv(ALLOW_MOCK_METRICS_ENV, "1")
        assert mock_metrics_enabled() is True

        col = MetricsCollector()
        metrics = asyncio.run(col.collect_agent_metrics(_agent()))
        assert metrics.metadata.get("mock") is True, (
            "dev-only 假数据必须带 mock 水印，消费方才能打标注"
        )

        user_metrics = asyncio.run(col.collect_user_metrics(_user()))
        assert user_metrics.metadata.get("mock") is True

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv(ALLOW_MOCK_METRICS_ENV, value)
        assert mock_metrics_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv(ALLOW_MOCK_METRICS_ENV, value)
        assert mock_metrics_enabled() is False


class TestModuleIsLabelledDevOnly:
    def test_docstring_states_dev_only(self):
        import ast
        import io

        src = io.open(
            "neurova/analytics/collector.py", encoding="utf-8"
        ).read()
        doc = ast.get_docstring(ast.parse(src)) or ""
        assert "dev-only" in doc, "模块 docstring 必须显式标注 dev-only 与假数风险"
        assert ALLOW_MOCK_METRICS_ENV in doc, "docstring 必须写明开关名"

    def test_real_metrics_path_is_pointed_at(self):
        import ast
        import io

        src = io.open("neurova/analytics/collector.py", encoding="utf-8").read()
        doc = ast.get_docstring(ast.parse(src)) or ""
        assert "neurova.core.metrics" in doc, (
            "必须指路真实指标源（prometheus 埋点），否则接线者仍会用假数"
        )
