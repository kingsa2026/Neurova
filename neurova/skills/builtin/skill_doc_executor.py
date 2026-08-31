"""SkillMarkdownExecutor - SKILL.md 指令型技能执行器

Agent Skills 标准语义的可执行映射：远端市场技能（阿里云/讯飞等 SKILL.md
格式技能包）调用时，把 SKILL.md 指令体返回给 Agent（注入当轮上下文），
附带 scripts/ 清单与任务参数。

安全边界：不自动执行包内下载脚本（scripts/ 仅列出清单）——脚本执行留给
Agent 既有工具链（审批门控/沙箱），市场层不做任意代码执行。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.skills.executor import BaseSkillExecutor, SkillResult

logger = get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)


def parse_skill_md(text: str) -> Tuple[Dict[str, str], str]:
    """解析 SKILL.md：返回 (frontmatter dict, 指令正文)。

    frontmatter 解析做宽容处理（key: value 单行），解析失败不阻断——
    指令正文始终完整返回。
    """
    meta: Dict[str, str] = {}
    body = text
    m = _FRONTMATTER_RE.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(0).strip().strip("-").strip().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                if key:
                    meta[key] = value.strip()
    return meta, body.strip()


class SkillMarkdownExecutor(BaseSkillExecutor):
    """SKILL.md 指令型技能执行器

    execute(params) → SkillResult(success, output={
        skill_id, name, description, instructions, scripts, task, skill_dir
    })
    """

    def __init__(self, skill_id: str, skill_dir: Any, skill_name: str = "", description: str = ""):
        super().__init__(skill_id, skill_name or skill_id)
        self.skill_dir = Path(skill_dir)
        self._description = description

    def execute(self, params: Optional[Dict[str, Any]] = None, *args, **kwargs) -> SkillResult:
        params = params or {}
        skill_md = self.skill_dir / "SKILL.md"
        if not skill_md.exists():
            return SkillResult(
                success=False,
                output=None,
                error=f"SKILL.md not found under {self.skill_dir}",
            )
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            return SkillResult(success=False, output=None, error=f"read SKILL.md failed: {e}")

        meta, instructions = parse_skill_md(text)

        scripts: list = []
        scripts_dir = self.skill_dir / "scripts"
        if scripts_dir.exists():
            scripts = sorted(p.name for p in scripts_dir.iterdir() if p.is_file())

        task = (
            params.get("task")
            or params.get("input")
            or params.get("query")
            or ""
        )
        return SkillResult(
            success=True,
            output={
                "skill_id": self.skill_id,
                "name": meta.get("name") or self.skill_name,
                "description": self._description or meta.get("description", ""),
                "instructions": instructions,
                "scripts": scripts,
                "task": str(task),
                "skill_dir": str(self.skill_dir),
                "note": "SKILL.md 指令型技能：instructions 供 Agent 遵循执行；scripts 需经 Agent 工具链审批后运行",
            },
            metadata={"source": "skill_md", "skill_dir": str(self.skill_dir)},
        )
