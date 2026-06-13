"""
记忆缓存模块

提供记忆数据的缓存功能，包括：
- LRU 缓存
- TTL 缓存
- 分层缓存

注意：此模块已废弃，请使用 neurova.core.cache 统一缓存模块。
"""

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

# 从统一缓存模块导入
from neurova.core.cache import CacheEntry, MemoryCache

# 保留旧的导入以兼容现有代码
__all__ = ["CacheEntry", "MemoryCache"]
