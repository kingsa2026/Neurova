"""
Skill 清单 Provider

聚合多个 ManifestSource，提供：
- 合并 + 去重（先到先得，local 来源优先于 remote）
- 缓存（list 结果缓存，重复调用不重新拉取）
- refresh() 主动失效缓存
- get_manifest(id) 单条查询（与 list 共享同一缓存对象）
"""

from __future__ import annotations

from typing import Dict, List, Optional

from neurova.skills.manifest_entry import SkillManifestEntry
from neurova.skills.manifest_source import ManifestSource


class SkillManifestProvider:
    """按需拉取并聚合 Skill 清单"""

    def __init__(self, sources: Optional[List[ManifestSource]] = None) -> None:
        self.sources: List[ManifestSource] = list(sources) if sources else []
        self._cache: Optional[List[SkillManifestEntry]] = None
        self._cache_by_id: Dict[str, SkillManifestEntry] = {}

    def list_manifests(self) -> List[SkillManifestEntry]:
        """列出所有来源合并后的 manifest（带缓存）"""
        if self._cache is not None:
            return self._cache

        merged: List[SkillManifestEntry] = []
        by_id: Dict[str, SkillManifestEntry] = {}
        for source in self.sources:
            try:
                manifests = source.list_manifests()
            except Exception:
                # 单个来源失败不影响其它来源
                continue
            for entry in manifests:
                if entry.id in by_id:
                    continue  # 先到先得：local 来源优先
                by_id[entry.id] = entry
                merged.append(entry)

        self._cache = merged
        self._cache_by_id = by_id
        return self._cache

    def get_manifest(self, manifest_id: str) -> Optional[SkillManifestEntry]:
        """查询单条 manifest（不存在返回 None），与 list 共享缓存"""
        if self._cache is None:
            self.list_manifests()
        return self._cache_by_id.get(manifest_id)

    def refresh(self) -> None:
        """失效缓存，下次 list 重新拉取"""
        self._cache = None
        self._cache_by_id = {}
