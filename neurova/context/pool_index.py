from __future__ import annotations

"""ContextPool 读路径索引（Issue #65：query() 从全池线性扫降到分区直取）。

背景（实测基线，Issue #65）：池是**永久归档**（只增不减），而 ``query()`` 此前
每次都对全池做「list() 拷贝 → TTL 过滤 → 逐条 content.lower() → 逐条
source/session 比较 → sort」。写路径早已 O(1)（``_by_hash`` 索引），读路径却
严格线性：10k 条 20 次 query = 0.438s，10 万条量级单次约 200ms。

本模块提供**分区索引**（source / session）：

- ``query(source=...)`` / ``query(session_id=...)`` 直接取分区列表（O(k)），
  不再全池遍历后逐条比较；
- 关键字匹配的降本策略见 ``keyword_matches``：**无大小写差异的关键词**
  （中文/数字/符号——本仓主要语料）直接 ``needle in content``（C 层、零分配），
  与旧的 ``needle.lower() in content.lower()`` 严格等价，且不再逐条构造小写副本；
  含大小写差异的关键词仍走精确的小写比较（语义不变，成本由埋点观测）。

索引契约（调用方 ``ContextPool`` 必须持 ``_lock`` 调用，本类自身不加锁）：

1. 池条目按插入序 append，分区列表保持该插入序（``query()`` 的稳定排序依赖它）；
2. 任何**整体重排**（clear / dedup / compress / cleanup_expired）后必须
   ``rebuild()``；
3. 条目 metadata（session_id）或内容被就地修改的路径必须 ``remove()`` + ``add()``
   重挂，否则分区会指向陈旧归属。
"""

from typing import Any, Dict, List


class PoolReadIndex:
    """source / session_id 分区索引 + 大小写敏感度判定。"""

    def __init__(self) -> None:
        self._by_source: Dict[Any, List[Any]] = {}
        self._by_session: Dict[Any, List[Any]] = {}
        self._count = 0

    # ── 维护 ───────────────────────────────────────────────

    def add(self, entry: Any) -> None:
        """挂载单条（插入序 append）。"""
        source = getattr(entry, "source", None)
        self._by_source.setdefault(source, []).append(entry)
        session_id = (getattr(entry, "metadata", None) or {}).get("session_id")
        self._by_session.setdefault(session_id, []).append(entry)
        self._count += 1

    def remove(self, entry: Any) -> None:
        """按对象身份摘除（CPython list.remove 有 identity 快路径）。

        条目已不在分区内（如刚 rebuild 过）时静默忽略——索引只做加速，
        绝不允许因索引不同步而影响池语义。
        """
        removed = False
        for mapping, key in (
            (self._by_source, getattr(entry, "source", None)),
            (self._by_session, (getattr(entry, "metadata", None) or {}).get("session_id")),
        ):
            bucket = mapping.get(key)
            if bucket is None:
                continue
            try:
                bucket.remove(entry)
            except ValueError:
                continue
            removed = True
            if not bucket:
                mapping.pop(key, None)
        # 计数是"条目数"而非"维度挂载数"：一条在两维各挂一次，只减一
        if removed:
            self._count -= 1

    def rebuild(self, entries) -> None:
        """整体重排后重建（O(N)，仅在 clear/dedup/compress/cleanup 后调用）。"""
        self._by_source = {}
        self._by_session = {}
        self._count = 0
        for entry in entries:
            self.add(entry)

    def clear(self) -> None:
        self._by_source = {}
        self._by_session = {}
        self._count = 0

    def ensure_synced(self, entries) -> bool:
        """条目数不一致即重建（返回是否重建过）。

        防线：本索引由 ``ContextPool`` 的公开路径维护，但 ``_collector._contexts``
        是 Python 可见的普通 list——测试/历史代码存在直接增删它的写法（旧实现
        每次都读实时列表，故这种行为"能用"）。计数漂移即重建，保证优化后的
        取数结果与"读实时列表"的旧语义一致。
        """
        if self._count == len(entries):
            return False
        self.rebuild(entries)
        return True

    # ── 查询 ───────────────────────────────────────────────

    def session_entries(self, session_id: Any) -> List[Any]:
        """某 session 的条目列表（插入序）。返回内部列表：调用方只读。"""
        return self._by_session.get(session_id, [])

    def source_entries(self, source: Any) -> List[Any]:
        """某 source 的条目列表（插入序）。返回内部列表：调用方只读。"""
        return self._by_source.get(source, [])

    def session_partitions(self):
        """全部 (session_key, entries) 分区（插入序）。调用方只读。"""
        return self._by_session.items()

    def stats(self) -> Dict[str, Any]:
        return {
            "session_partitions": len(self._by_session),
            "source_partitions": len(self._by_source),
            "indexed_entries": self._count,
        }

    # ── 关键字匹配 ─────────────────────────────────────────

    @classmethod
    def is_caseless(cls, needle: str) -> bool:
        """needle 每个字符在大小写展开下都"原地不动"（中文/数字/符号等）。

        此时 ``needle in content`` 与 ``needle.lower() in content.lower()``
        **严格等价**（每个字符的大小写等价类退化为自身），故可省掉逐条
        lower() 分配——这正是 Issue #65 里读路径的主要成本（10k 条时
        逐条 lower 占 query 耗时的绝大部分）。

        判定保守，任一不满足即回退精确路径（保证结果与旧实现逐字一致）：

        1. ``needle == needle.lower() == needle.upper()``——必须同时比较
           lower/upper：``"Σ".upper() == "Σ"`` 但 ``"Σ".lower() == "σ"``，
           单看 upper 会把有大小写差异的字符误判为无差异。该条件同时排除了
           所有"有大小写"字符（'A'/'Σ'/'ß'/'K'(U+212A)/'İ'/'Ａ'…）；
        2. ``needle.lower()`` 的展开里不得出现"非原地"字符——子串包含按字符
           逐个比较，needle 自身不动不代表其展开也不动（多字符展开是实测
           可出现的形态）。

        校验：``tests/unit/context/test_context_pool_query_index.py`` 对
        Unicode 全码位 + 随机串做穷举（可证伪的安全网）。
        """
        if not needle:
            return False
        if not (needle == needle.lower() == needle.upper()):
            return False
        for ch in needle.lower():
            if not (ch == ch.lower() == ch.upper()):
                return False
        return True

    @staticmethod
    def content_lower(entry: Any) -> str:
        """条目内容的小写副本（精确回退路径）。

        独立方法便于测试计数：无大小写差异的关键词不得走到这里，否则又回到
        「每条一次 lower() 分配」的旧成本（Issue #65 读路径瓶颈）。
        """
        return str(getattr(entry, "content", "") or "").lower()

    def keyword_matches(self, entry: Any, needle: str, caseless: bool) -> bool:
        """关键字过滤（语义与旧实现一致：不区分大小写的子串包含）。"""
        content = str(getattr(entry, "content", "") or "")
        if caseless:
            return needle in content
        return needle.lower() in self.content_lower(entry)


__all__ = ["PoolReadIndex"]
