"""pydantic v1/v2 兼容 helper

项目当前安装 pydantic v1.10.26, BaseModel 只有 .dict() 没有 .model_dump().
但代码库多处调用 .model_dump() → 全部 AttributeError (预存 bug, 端点从未被调用过
所以未暴露).

本模块提供 safe_model_dump(obj, **kwargs):
  - v1: 调 obj.dict(**kwargs)
  - v2: 调 obj.model_dump(**kwargs) (优先)

调用方应统一改为:
  from neurova.api.endpoints._pydantic_compat import safe_model_dump
  data = safe_model_dump(body, exclude_none=True)
"""

from typing import Any

__all__ = ["safe_model_dump"]


def safe_model_dump(obj: Any, **kwargs: Any) -> Any:
    """兼容 pydantic v1 (dict) 和 v2 (model_dump) 的序列化 helper.

    优先使用 model_dump (v2 标准方法); 若不存在则降级到 dict (v1 方法).

    Args:
        obj: pydantic BaseModel 实例 (或任何有 model_dump/dict 方法的对象)
        **kwargs: 透传给底层方法 (如 exclude_none=True, exclude_defaults=True)

    Returns:
        dict: 序列化结果
    """
    # 优先 v2 路径 (model_dump 是 pydantic v2 标准)
    model_dump = getattr(obj, "model_dump", None)
    if model_dump is not None:
        return model_dump(**kwargs)
    # 降级 v1 路径 (dict 是 pydantic v1 方法, v2 中是 deprecated alias 但仍可用)
    return obj.dict(**kwargs)
