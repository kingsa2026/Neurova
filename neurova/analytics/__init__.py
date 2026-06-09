"""
数据分析模块

提供系统指标收集、聚合和分析功能。
"""

import logging

logger = logging.getLogger(__name__)

# 懒导入，避免循环依赖
__all__ = ["collector", "models"]
