"""run 并发槽租约（资源治理 P2-4）。

借鉴参照系 ad 的租约槽形态（Redis Lua 租约 + 续租 + 属主校验 + 过期
回收），按本仓单进程形态落成进程内租约板：

- acquire/renew/release 全部带**属主校验**——错主续租/释放一律拒绝；
- 过期租约由 `reclaimExpired` 回收（返回 (key, owner) 供调用方做记账
  修复，例如释放模型并发槽计数）；
- TTL 经 `NEUROVA_RUN_LEASE_TTL_S` 注入，**缺省 0 = 租约关闭**（acquire
  恒 False、reclaim 恒空），与既有槽位机制行为完全一致；多实例部署
  需要跨进程槽仲裁时再启用。

单调时钟可注入（测试用假时钟推进，不靠 sleep）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def leaseTtlSeconds() -> float:
    """租约 TTL（秒）；NEUROVA_RUN_LEASE_TTL_S 未设/非法/<=0 → 0（租约关闭）。"""
    raw = os.getenv("NEUROVA_RUN_LEASE_TTL_S", "")
    try:
        return max(0.0, float(str(raw).strip() or 0.0))
    except (TypeError, ValueError):
        return 0.0


class LeaseBoard:
    """进程内租约板：key → (owner, expire_at)，RLock 串行化全部判定。"""

    def __init__(self, clock: Optional[callable] = None):
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._leases: Dict[str, Tuple[str, float]] = {}

    def acquire(self, key: str, owner: str, ttl: float) -> bool:
        """取得/重入 key 的租约；被其他属主未过期持有时拒绝。ttl<=0 恒 False。"""
        if ttl is None or float(ttl) <= 0:
            return False
        now = float(self._clock())
        with self._lock:
            held = self._leases.get(key)
            if held is not None and held[1] > now and held[0] != str(owner):
                return False
            self._leases[key] = (str(owner), now + float(ttl))
            return True

    def renew(self, key: str, owner: str, ttl: float) -> bool:
        """续租：仅当前属主且未过期时可续（过期后须重新 acquire）。"""
        if ttl is None or float(ttl) <= 0:
            return False
        now = float(self._clock())
        with self._lock:
            held = self._leases.get(key)
            if held is None or held[0] != str(owner) or held[1] <= now:
                return False
            self._leases[key] = (str(owner), now + float(ttl))
            return True

    def release(self, key: str, owner: str) -> bool:
        """释放：属主校验——错主（或无人持有）释放被拒，防误删他人槽。"""
        with self._lock:
            held = self._leases.get(key)
            if held is None or held[0] != str(owner):
                return False
            del self._leases[key]
            return True

    def holds(self, key: str, owner: str) -> bool:
        now = float(self._clock())
        with self._lock:
            held = self._leases.get(key)
            return held is not None and held[0] == str(owner) and held[1] > now

    def reclaimExpired(self) -> List[Tuple[str, str]]:
        """回收全部过期租约，返回 (key, owner) 列表。"""
        now = float(self._clock())
        reclaimed: List[Tuple[str, str]] = []
        with self._lock:
            for key in list(self._leases.keys()):
                owner, expireAt = self._leases[key]
                if expireAt <= now:
                    del self._leases[key]
                    reclaimed.append((key, owner))
        return reclaimed

    def reset(self) -> None:
        """清空（测试辅助）。"""
        with self._lock:
            self._leases.clear()
