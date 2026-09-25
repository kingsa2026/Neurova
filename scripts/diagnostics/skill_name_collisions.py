"""同名技能覆盖的复算 / 迁移入口（工单 006 验收项 · Issue #189 键域迁移）。

`SkillRegistry.register` 按 `skill.name` 建键（ADR 0017 定的键域：name 是执行与
展示域），而技能的身份是 `skill_id`。历史 manifest 里 `ai_tool` / `general_tool`
被多条不同身份的自动技能共用，后到者**静默**顶掉先到者——工具面上"少了几条"
却无从察觉（Issue #189 启动实测累计 10 次）。

工单 006 只加告警与计数、不硬拒（存量库当场硬拒会让装配失败）；本脚本现在有两件事：

- **复算**（默认，只读）：把"我记得有 8 条"变成可查读数；
- **迁移**（`--apply`）：就地收敛名字域，同 name 不同身份的条目各自拿到携带身份
  的名字。判据只写一份——`neurova.skills.skill_name_domain`，本脚本不含第二份口径。

用法：
    python scripts/diagnostics/skill_name_collisions.py [manifest.json ...]
    python scripts/diagnostics/skill_name_collisions.py --apply [manifest.json ...]
    不带路径参数时扫 `data/agents/*/skills/manifest.json` 与公共/用户库。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
# 仓库根须先于 `import neurova` 进 sys.path（脚本以文件路径执行）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.core.data_root import get_data_root  # noqa: E402
from neurova.skills.skill_name_domain import (  # noqa: E402
    applyToManifestFile,
    recountManifestCollisions,
)


def recount_name_collisions(manifest_path: Path) -> Dict[str, Any]:
    """按 name 复算一份 manifest 上的同名覆盖（委托唯一判据实现）。

    计数口径 = **同一 name 下身份不同的额外条目数**（先到者保留，其余每个记
    1 次覆盖），与 `SkillRegistry._warn_on_name_collision` 同口径。
    """
    import json

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(payload, dict):
        return {"manifest": str(path), "collision_count": 0, "collisions": []}
    return {"manifest": str(path), **recountManifestCollisions(payload)}


def migrate_name_domain(manifest_path: Path) -> Dict[str, Any]:
    """在磁盘上就地收敛一份 manifest 的名字域（幂等）。"""
    path = Path(manifest_path)
    report = applyToManifestFile(path)
    if report is None:
        return {"manifest": str(path), "renamed_count": 0, "renamed": [], "skipped": True}
    return {"manifest": str(path), **report}


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
    apply = False
    if "--apply" in argv:
        apply = True
        argv.remove("--apply")
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
        if not apply:
            continue
        moved = migrate_name_domain(target)
        print(f"  迁移：改名 {moved['renamed_count']} 条")
        for item in moved.get("renamed", []):
            print(f"    {item['id']}: {item['from']} → {item['to']}")
        after = recount_name_collisions(target)
        print(f"  迁移后同名覆盖 {after['collision_count']} 次")
    if not apply:
        print("（只读复算；加 --apply 就地迁移名字域）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
