"""
Model Adapter v1.0.0 — 多 LLM 自适应推理循环

基于 CUA 架构启发，实现：
- ModelAdapterRegistry: 模型适配器注册表（全局单例）
- BaseModelAdapter: 适配器基类（统一接口）
- 自动匹配: 根据模型名正则匹配最佳适配器

隔离层级: 全局（无状态路由，无数据残留）
"""

from neurova.core.logger import get_logger
logger = get_logger(__name__)

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

try:
    import re
except ImportError:
    re = None  # type: ignore[assignment]

__all__ = ["BaseModel"]
