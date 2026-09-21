"""同名技能覆盖的复算入口（工单 006 验收项）。

`SkillRegistry.register` 按 `skill.name` 建键，而技能的身份是 `skill_id`
（`evolution/skill_encapsulation` 明写"名字不是身份"）。自动技能的
`name ≠ skill_id` 时，后到者**静默**顶掉先到者，工具面上"少了一个"无从察觉。

006 只加告警与计数、**不硬拒**：存量库当场硬拒会让装配失败。本脚本提供
"在真实 manifest 上把计数复算出来"的能力，把验收从"我记得有 8 条"变成可查读数。

用法：
    python scripts/diagnostics/skill_name_collisions.py [manifest.json ...]
    不带参数时扫 `data/agents/*/skills/manifest.json` 与公共/用户库。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from neurova.core.data_root import get_data_root

ROOT = Path(__file__).resolve().parents[2]

# 别名表键不是技能条目，扫描时排除（`SkillService._ALIASES_KEY`）
_ALIASES_KEY = "_skill_aliases"


def recount_name_collisions(manifest_path: Path) -> Dict[str, Any]:
    """按 name 复算一份 manifest 上的同名覆盖。

    计数口径与 `SkillRegistry._warn_on_name_collision` 一致：**同一 name 下
    身份不同的额外条目数**（先到者保留，其余每个记 1 次覆盖）。
    """
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(payload, dict):
        return {"manifest": str(path), "collision_count": 0, "collisions": []}

    by_name: Dict[str, List[str]] = {}
    for key, entry in payload.items():
        if key == _ALIASES_KEY or not isinstance(entry, dict):
            continue
        identity = str(entry.get("id") or key)
        name = str(entry.get("name") or identity)
        by_name.setdefault(name, []).append(identity)

    collisions: List[Dict[str, Any]] = []
    total = 0
    for name, identities in sorted(by_name.items()):
        unique = sorted(set(identities))
        if len(unique) <= 1:
            continue
        total += len(unique) - 1
        collisions.append({"name": name, "resident": unique[0], "shadowed": unique[1:]})
    return {"manifest": str(path), "collision_count": total, "collisions": collisions}


def _default_targets() -> List[Path]:
    targets: List[Path] = []
    data_root = get_data_root()
    for pattern in (
        "agents/*/skills/manifest.json",
        "public/skills/manifest.json",
        "users/*/skills/manifest.json",
    ):
        targets.extend(sorted(data_root.glob(pattern)))
    return targets


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    targets = [Path(a) for a in argv] or _default_targets()
    if not targets:
        print("未找到任何 manifest（数据根下无技能库）")
        return 0
    for target in targets:
        if not target.exists():
            print(f"[跳过] 不存在: {target}")
            continue
        report = recount_name_collisions(target)
        print(f"{report['manifest']}: 同名覆盖 {report['collision_count']} 次")
        for item in report["collisions"]:
            print(f"  - name={item['name']} 保留={item['resident']} 被顶替={item['shadowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
