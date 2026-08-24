"""
Manifest 来源

定义 ManifestSource 抽象基类，并提供两个具体来源：
- LocalBuiltinSource：扫描 neurova/skills/builtin/ 目录列出内置 skill
- RemoteHubSource：从远程 hub 拉取（懒加载 client，失败时降级为空列表）
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional

from neurova.skills.manifest_entry import SkillManifestEntry


class ManifestSource(ABC):
    """Manifest 来源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """来源名称（用于日志与调试）"""
        ...

    @abstractmethod
    def list_manifests(self) -> List[SkillManifestEntry]:
        """列出该来源下的所有 Skill 清单条目"""
        ...


class LocalBuiltinSource(ManifestSource):
    """扫描 neurova/skills/builtin/ 目录，列出内置 skill"""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        # 默认扫描 neurova/skills/builtin/ 目录（本文件位于 neurova/skills/）
        self._base_dir = Path(base_dir) if base_dir else (Path(__file__).parent / "builtin")

    @property
    def name(self) -> str:
        return "local_builtin"

    def list_manifests(self) -> List[SkillManifestEntry]:
        entries: List[SkillManifestEntry] = []
        if not self._base_dir.exists():
            return entries
        for sub in sorted(self._base_dir.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name.startswith("_") or sub.name in ("__pycache__",):
                continue
            entries.append(self._build_entry(sub))
        return entries

    def _build_entry(self, sub: Path) -> SkillManifestEntry:
        skill_id = sub.name
        name = skill_id
        version = "0.1.0"
        # 尝试从 skill 模块中提取 name / version
        for fname in ("skill.py", "__init__.py"):
            fpath = sub / fname
            if not fpath.exists():
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                break
            m = re.search(r'super\(\)\.__init__\(\s*["\']([^"\']+)["\']', text)
            if m:
                name = m.group(1)
            v = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
            if v:
                version = v.group(1)
            break
        return SkillManifestEntry(
            id=skill_id, name=name, version=version, source="local"
        )


class RemoteHubSource(ManifestSource):
    """远程 hub 来源（懒加载 client，失败时降级为空列表）"""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "remote_hub"

    def list_manifests(self) -> List[SkillManifestEntry]:
        client = self._client or _get_default_client()
        if client is None:
            return []
        try:
            remote_skills = client.list_remote_skills()
        except Exception:
            return []
        entries: List[SkillManifestEntry] = []
        for s in remote_skills:
            entries.append(
                SkillManifestEntry(
                    id=getattr(s, "name", ""),
                    name=getattr(s, "name", ""),
                    version=getattr(s, "version", "0.1.0"),
                    source="remote",
                    description=getattr(s, "description", ""),
                    author=getattr(s, "author", ""),
                    tags=getattr(s, "tags", []),
                )
            )
        return entries


def _get_default_client() -> Any:
    """懒加载默认 SkillHubClient，导入失败则返回 None"""
    try:
        from neurova.skills.hub_client import SkillHubClient

        return SkillHubClient()
    except Exception:
        return None
