"""bayesian_eki 诚实标注守卫。

高斯过程代理与单步 EKI 更新已实现；完整批量求解器没有生产消费者，已退役。
剩余简化面（_compute_information_gain 词汇启发式、_flush_updates 未实现）
继续钉住诚实标注。
"""
from __future__ import annotations

import os
import sys

import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.bayesian_eki import cognitive_optimizer
from neurova.cognitive_layers.memory_layer.bayesian_eki.cognitive_optimizer import EKICognitiveOptimizer


# ────── docstring 诚实标注 ──────


class TestHonestDocstring:
    """验证 docstring 诚实标注：已实现组件列全，未实现项仍如实标注"""

    def test_init_docstring_marks_unimplemented_components(self):
        """__init__.py docstring 应保留「未实现」诚实标注（剩余简化面）"""
        from neurova.cognitive_layers.memory_layer import bayesian_eki

        docstring = bayesian_eki.__doc__ or ""
        # 应包含"未实现"标注
        assert "未实现" in docstring or "not implemented" in docstring.lower(), (
            "bayesian_eki __init__.py docstring 应诚实标注未实现组件"
        )

    def test_init_docstring_lists_implemented_components(self):
        """__init__.py docstring 应列出已实现组件"""
        from neurova.cognitive_layers.memory_layer import bayesian_eki

        docstring = bayesian_eki.__doc__ or ""
        assert "EKICognitiveOptimizer" in docstring
        assert "TaskValue" in docstring

    def test_init_docstring_marks_gaussian_process_implemented(self):
        """高斯过程代理已实现：docstring 应列出 GaussianProcessSurrogate"""
        from neurova.cognitive_layers.memory_layer import bayesian_eki

        docstring = bayesian_eki.__doc__ or ""
        assert "GaussianProcessSurrogate" in docstring, (
            "高斯过程代理已实现，docstring 应列出 GaussianProcessSurrogate"
        )
        assert "高斯过程" in docstring or "gaussian" in docstring.lower()

    def test_init_docstring_does_not_claim_retired_solver(self):
        from neurova.cognitive_layers.memory_layer import bayesian_eki

        docstring = bayesian_eki.__doc__ or ""
        assert "EnsembleKalmanInversion" not in docstring


# ────── _flush_updates 显式失败 ──────


class TestFlushUpdatesRaises:
    """验证 _flush_updates 抛出 NotImplementedError（而非空方法）"""

    def test_flush_updates_raises_not_implemented(self):
        """_flush_updates 应抛出 NotImplementedError，而非静默返回 None"""
        optimizer = EKICognitiveOptimizer(ensemble_size=5, learning_rate=0.1)
        with pytest.raises(NotImplementedError):
            optimizer._flush_updates()


# ────── 简化实现标注 ──────


class TestSimplifiedImplementationMarked:
    """验证仍为简化实现的方法 docstring 包含标注"""

    def test_compute_information_gain_docstring_marks_simplified(self):
        """_compute_information_gain docstring 应标注'简化实现'"""
        docstring = EKICognitiveOptimizer._compute_information_gain.__doc__ or ""
        assert "简化" in docstring or "simplified" in docstring.lower(), (
            "_compute_information_gain docstring 应标注为简化实现"
        )
