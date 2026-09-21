"""肌肉记忆脏条目作废重攒（工单 008 的一次性迁移脚本）。

背景：文本模式的非 JSON 参数被降级成 `{"_raw": "location=…, city=…"}`，并被
肌肉记忆**原样存下**（现网 `agent_workspaces/kai/memory/muscle_memory/muscle_l2.json`
全部 2 条都是这形态）。命中后必然被参数校验拒 ⇒ 给结构身份粘永久失败票。

写侧已改存规范 dict（`MuscleMemory._canonical_params`），但存量脏条目无法反推
用户当时想调什么，故**作废重攒**：原文件归档留底（不删除），新文件清空等下一轮
写入自然填充。归档动作可回退——把归档副本改回原名即可。

用法：
    python scripts/diagnostics/muscle_memory_rearchive.py [文件路径 ...]
"""

from __future__ import annotations

import datetime
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = tuple(
    (ROOT / "agent_workspaces").glob("*/memory/muscle_memory/muscle_l*.json")
)


def archive_dirty_memory(target: Path) -> Optional[Path]:
    """归档并清空一个肌肉记忆文件；无脏条目时原样返回 None。"""
    target = Path(target)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8") or "[]")
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = target.with_name(f"{target.name}.pre-muscle-ngram-{stamp}")
    shutil.copy2(target, archived)
    target.write_text("[]", encoding="utf-8")
    return archived


def main(argv: List[str]) -> int:
    targets = [Path(arg) for arg in argv[1:]] or list(DEFAULT_TARGETS)
    if not targets:
        print("没有命中任何肌肉记忆文件（默认扫 agent_workspaces/*/memory/muscle_memory/）")
        return 0
    for target in targets:
        archived = archive_dirty_memory(target)
        if archived is None:
            print(f"跳过（不存在或无条目）：{target}")
            continue
        print(f"已归档：{target} → {archived.name}；原文件已清空待重攒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
