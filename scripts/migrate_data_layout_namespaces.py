# -*- coding: utf-8 -*-
"""存量数据落点收口迁移（2026-11-23 拍板：步骤③）。

把数据根顶层的历史遗留目录收进规范命名空间（可逆：一律搬移归档，不删除）：

1. 协作房间遗留 `data/project_*/sessions/session_*.json`
   → 转写为 `data/collaboration/rooms/<room_id>/messages.jsonl`，
   原目录整体归档到 `data/archive/rooms_legacy/<room_id>/`；
2. 训练数据集目录（agentcompany / agentinstruct-* / taubench-* / tooltalk）
   → `data/training_datasets/<name>/`；
3. 其余无 agent_config.json、不在 agents.json 登记册、非保留名的目录
   → `data/archive/<name>/`。

保留（不动）：带 agent_config.json 的 agent 根、agents.json 登记册内的 id、
全部保留名（RESERVED_AGENT_ROOT_NAMES）与顶层文件。

用法：先干跑看计划，再 --apply 执行。
    python scripts/migrate_data_layout_namespaces.py            # 干跑
    python scripts/migrate_data_layout_namespaces.py --apply    # 执行
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from neurova.core.agent_workspaces import RESERVED_AGENT_ROOT_NAMES  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402

TRAINING_EXACT = {"agentcompany", "tooltalk", "openhermes"}
TRAINING_PREFIXES = ("agentinstruct-", "taubench-")

ROLE_BY_SESSION_ROLE = {"user": "user", "assistant": "agent", "system": "system"}


def _registryAgentIds(dataRoot: Path) -> set:
    try:
        raw = json.loads((dataRoot / "agents" / "agents.json").read_text(encoding="utf-8"))
        return set(raw) if isinstance(raw, dict) else set()
    except (OSError, ValueError):
        return set()


def _convertRoomSessions(projectDir: Path, roomDir: Path) -> int:
    """把旧房间会话文件转写为 messages.jsonl（追加，幂等：目标已存在则跳过）。"""
    target = roomDir / "messages.jsonl"
    if target.exists():
        return 0
    sessionsDir = projectDir / "sessions"
    if not sessionsDir.is_dir():
        return 0
    lines: list = []
    for sessionFile in sorted(sessionsDir.glob("session_*.json")):
        try:
            payload = json.loads(sessionFile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for message in payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            metadata = dict(message.get("metadata") or {})
            senderType = str(metadata.get("sender_type")
                             or ROLE_BY_SESSION_ROLE.get(message.get("role"), "agent"))
            record = {
                "room_id": projectDir.name,
                "sender_type": senderType,
                "sender_id": str(metadata.get("sender_id", "")),
                "role": message.get("role", ""),
                "content": message.get("content", ""),
                "timestamp": message.get("timestamp", ""),
                "meta": {k: v for k, v in metadata.items()
                         if k not in ("sender_type", "sender_id")},
            }
            lines.append(json.dumps(record, ensure_ascii=False))
    if not lines:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据根顶层遗留目录收口迁移")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--apply", action="store_true", help="执行迁移（缺省干跑）")
    args = parser.parse_args(argv)

    dataRoot = Path(args.data_root) if args.data_root else get_data_root()
    archiveRoot = dataRoot / "archive"
    registry = _registryAgentIds(dataRoot)

    plan: list = []
    for entry in sorted(dataRoot.iterdir()):
        name = entry.name
        if entry.is_file():
            continue
        if name in RESERVED_AGENT_ROOT_NAMES or name in registry:
            continue
        if (entry / "agent_config.json").exists():
            continue
        if name.startswith("project_"):
            plan.append(("room", entry, dataRoot / "collaboration" / "rooms" / name))
        elif name in TRAINING_EXACT or name.startswith(TRAINING_PREFIXES):
            plan.append(("training", entry, dataRoot / "training_datasets" / name))
        else:
            plan.append(("archive", entry, archiveRoot / name))

    moved = 0
    for kind, src, dst in plan:
        if kind == "room":
            converted = _convertRoomSessions(src, dataRoot / "collaboration" / "rooms" / src.name)
            print(f"[room] {src.name}: 转写 {converted} 条消息 → collaboration/rooms/{src.name}/messages.jsonl；"
                  f"原目录归档 → archive/rooms_legacy/{src.name}/")
            dst = archiveRoot / "rooms_legacy" / src.name
        else:
            print(f"[{kind}] {src.name} → {dst.relative_to(dataRoot)}/")
        if args.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.move(str(src), str(dst))
            moved += 1

    print(f"计划 {len(plan)} 项；执行 {moved if args.apply else 0} 项"
          f"（{'已执行' if args.apply else '干跑，加 --apply 执行'}）。"
          f"保留：agent 根/登记册 id/保留名/顶层文件一律不动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
