"""肌肉记忆脏条目作废重攒（工单 008 的一次性迁移脚本）。

背景：文本模式的非 JSON 参数被降级成 `{"_raw": "location=…, city=…"}`，并被
肌肉记忆**原样存下**（现网 `agent_workspaces/kai/memory/muscle_memory/muscle_l2.json`
全部 2 条都是这形态）。命中后必然被参数校验拒 ⇒ 给结构身份粘永久失败票。

写侧已改存规范 dict（`MuscleMemory._canonical_params`），但存量脏条目无法反推
用户当时想调什么，故**作废重攒**：原文件归档留底（不删除），新文件清空等下一轮
写入自然填充。归档动作可回退——把归档副本改回原名即可。

归档落点在**仓内** `docs/05-reports/muscle-memory-ledger/`（不是源文件旁边）：
`agent_workspaces/` 被 .gitignore 整目录忽略，归档留在那里等于只存在于磁盘上，
回退承诺随时会随一次 `git clean` 蒸发。

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
# 留底目录必须**在版本库内**：`agent_workspaces/` 被 .gitignore 整目录忽略，
# 归档副本落在源文件旁边等于只活在磁盘上——一次 `git clean -xfd` 或换台机器，
# "可回退"就没了。留底写入仓内目录并随提交入库。
LEDGER_DIR = ROOT / "docs" / "05-reports" / "muscle-memory-ledger"
DEFAULT_TARGETS = tuple(
    (ROOT / "agent_workspaces").glob("*/memory/muscle_memory/muscle_l*.json")
)


def archive_dirty_memory(target: Path) -> Optional[Path]:
    """归档并清空一个肌肉记忆文件；无脏条目时原样返回 None。

    归档名沿用票面约定的 `.pre-muscle-ngram-<UTC>` 形状，落点在仓内留底目录
    （每份文件一个同名前缀，不同 agent 不互相覆盖）。
    """
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
    ledger = Path(LEDGER_DIR)
    ledger.mkdir(parents=True, exist_ok=True)
    archived = ledger / f"{target.name}.pre-muscle-ngram-{stamp}"
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
