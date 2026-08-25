"""
MemoryExporter — 记忆可解释性 Markdown 导出/导入。

对齐升级方案 P1-2.2（借鉴 ReMe「可读可编辑」）：

- export_markdown(): 把记忆条目转为人类可读的 Markdown（含分类、重要度、
  时间戳等元数据），供用户在 Web 端直接查看与编辑
- parse_edited_markdown(): 解析（可能被用户编辑过的）Markdown，与当前
  记忆做「版本化 diff」——记录基准版本（updated_at）与新旧正文
- apply(): 仅把变更写回 content 文本层；不触碰 embedding / 向量索引
  （方案 7 风险对策：保留原始向量，仅编辑文本）

设计约束（AGENTS.md）:
- 深模块：依赖注入 MemoryManager（鸭子类型，仅需 get_memories /
  get_memory / update_memory 三个方法），不反向依赖 Agent
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HEADER_TITLE = "# Neurova 记忆导出"
_ENTRY_HEADING_RE = re.compile(r"^##\s+\[(?P<id>[^\]]+)\]\s*(?P<title>.*)$", re.MULTILINE)
# 元数据行: - 分类: x | 重要度: 0.80 | 温度: 0.50 | 创建: ... | 更新: ...
_META_LINE_RE = re.compile(r"^-\s*分类:\s*(?P<category>.*?)\s*\|\s*重要度:\s*(?P<importance>[\d.]+)", re.MULTILINE)


def _memory_field(mem: Any, key: str, default: Any = None) -> Any:
    """从记忆条目取字段；兼容 dict 与属性对象两种形态。"""
    if isinstance(mem, dict):
        return mem.get(key, default)
    value = getattr(mem, key, default)
    return default if value is None else value


@dataclass
class MemoryDiffEntry:
    """一条记忆的版本化 diff。"""

    memory_id: str
    title: str = ""
    old_content: str = ""
    new_content: str = ""
    base_version: str = ""  # 导出时的 updated_at（并发冲突检测基准）
    changed: bool = False


@dataclass
class ImportPlan:
    """一次导入的计划（尚未写回）。"""

    entries: List[MemoryDiffEntry] = field(default_factory=list)
    exported_at: str = ""

    @property
    def change_count(self) -> int:
        return sum(1 for e in self.entries if e.changed)


class MemoryExporter:
    """记忆 ↔ Markdown 双向转换器。"""

    def __init__(self, memory_manager: Any):
        """
        Args:
            memory_manager: 需提供 get_memories() / get_memory(id) /
                update_memory(id, **kwargs) 接口（如 MemoryManager）
        """
        self._manager = memory_manager

    # ── 导出 ────────────────────────────────────────────────────

    def export_markdown(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """导出记忆为可读 Markdown。"""
        if hasattr(self._manager, "get_memories"):
            memories = self._manager.get_memories(category=category, limit=limit)
        else:
            memories = []
        memories = memories or []

        lines: List[str] = [
            _HEADER_TITLE,
            "",
            f"> 导出时间: {datetime.now().isoformat(timespec='seconds')} | 条目数: {len(memories)}",
            "> 提示: 仅可编辑正文文本；导入时只应用文本变更，向量索引不受影响。",
            "",
        ]

        for mem in memories:
            lines.extend(self._render_entry(mem))

        return "\n".join(lines).rstrip() + "\n"

    def _render_entry(self, mem: Dict[str, Any]) -> List[str]:
        mid = str(_memory_field(mem, "id", ""))
        content = str(_memory_field(mem, "content", "") or "")
        first_line = content.splitlines()[0][:40] if content else "(空)"
        importance = float(_memory_field(mem, "importance", 0.0) or 0.0)
        temperature = float(_memory_field(mem, "temperature", 0.0) or 0.0)

        entry_lines = [
            f"## [{mid}] {first_line}",
            f"- 分类: {_memory_field(mem, 'category', 'general')} | 重要度: {importance:.2f} | "
            f"温度: {temperature:.2f}",
            f"- 创建: {_memory_field(mem, 'created_at', '?')} | "
            f"更新: {_memory_field(mem, 'updated_at', '?')} | "
            f"访问: {_memory_field(mem, 'access_count', 0)}",
            "",
            content,
            "",
            "---",
            "",
        ]
        return entry_lines

    # ── 解析 + 版本化 diff ──────────────────────────────────────

    def parse_edited_markdown(self, markdown_text: str) -> ImportPlan:
        """
        解析（可能被编辑过的）Markdown，产出与当前记忆的版本化 diff。

        diff 基准为导出时记录的 updated_at；apply(strict_version=True)
        时用于检测并发修改冲突。
        """
        plan = ImportPlan(exported_at=self._parse_export_time(markdown_text))

        headings = list(_ENTRY_HEADING_RE.finditer(markdown_text))
        for idx, match in enumerate(headings):
            mid = match.group("id").strip()
            start = match.end()
            end = headings[idx + 1].start() if idx + 1 < len(headings) else len(markdown_text)
            body = markdown_text[start:end]

            new_content = self._extract_body(body)
            meta = self._parse_meta(body)

            current = self._safe_get(mid)
            if current is None:
                # 记忆已不存在：仍记录条目，apply 时归入 missing
                plan.entries.append(
                    MemoryDiffEntry(
                        memory_id=mid,
                        title=match.group("title"),
                        new_content=new_content,
                        changed=bool(new_content),
                    )
                )
                continue

            old_content = str(_memory_field(current, "content", "") or "")
            base_version = meta.get("updated_at") or str(
                _memory_field(current, "updated_at", "")
            )
            plan.entries.append(
                MemoryDiffEntry(
                    memory_id=mid,
                    title=match.group("title"),
                    old_content=old_content,
                    new_content=new_content,
                    base_version=base_version,
                    changed=new_content != old_content,
                )
            )

        return plan

    def _extract_body(self, body: str) -> str:
        """提取条目正文：去掉元数据行、分隔线与首尾空白。"""
        lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("- 分类:") or stripped.startswith("- 创建:"):
                continue
            if set(stripped) == {"-"}:
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    def _parse_meta(self, body: str) -> Dict[str, str]:
        meta: Dict[str, str] = {}
        m = _META_LINE_RE.search(body)
        if m:
            meta["category"] = m.group("category")
            meta["importance"] = m.group("importance")
        created = re.search(r"创建:\s*([^|]+)", body)
        updated = re.search(r"更新:\s*([^|\s]+)", body)
        if created:
            meta["created_at"] = created.group(1).strip()
        if updated:
            meta["updated_at"] = updated.group(1).strip()
        return meta

    def _parse_export_time(self, text: str) -> str:
        m = re.search(r"导出时间:\s*([^\s|]+)", text)
        return m.group(1) if m else ""

    def _safe_get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._manager.get_memory(memory_id)
        except Exception:
            return None

    # ── 写回（仅文本层） ────────────────────────────────────────

    def apply(
        self,
        plan: ImportPlan,
        manager: Optional[Any] = None,
        strict_version: bool = False,
    ) -> Dict[str, int]:
        """
        把 diff 写回记忆。仅更新 content 文本层，绝不传 embedding 相关字段。

        Args:
            plan: parse_edited_markdown 的产物
            manager: 缺省用构造时注入的 manager
            strict_version: True 时校验 base_version 与当前 updated_at 一致，
                不一致记为 conflict 并跳过（防并发覆盖）

        Returns:
            统计 {"updated", "unchanged", "missing", "conflicts"}
        """
        mgr = manager or self._manager
        stats = {"updated": 0, "unchanged": 0, "missing": 0, "conflicts": 0}

        for entry in plan.entries:
            current = self._safe_get(entry.memory_id)
            if current is None:
                stats["missing"] += 1
                continue

            if strict_version and entry.base_version and entry.base_version != str(
                _memory_field(current, "updated_at", "")
            ):
                logger.warning(
                    "记忆 %s 版本冲突: 基准 %s vs 当前 %s",
                    entry.memory_id,
                    entry.base_version,
                    _memory_field(current, "updated_at"),
                )
                stats["conflicts"] += 1
                continue

            if not entry.changed:
                stats["unchanged"] += 1
                continue

            # 关键约束：仅 content —— 不动 importance/category/embedding
            try:
                mgr.update_memory(entry.memory_id, content=entry.new_content)
                stats["updated"] += 1
                logger.info("记忆 %s 文本层已更新（Markdown 导入）", entry.memory_id)
            except Exception as e:  # noqa: BLE001 - 单条失败不影响其余写回
                logger.error("记忆 %s 写回失败: %s", entry.memory_id, e)

        return stats


__all__ = ["MemoryExporter", "ImportPlan", "MemoryDiffEntry"]
