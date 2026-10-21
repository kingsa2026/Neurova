# -*- coding: utf-8 -*-
"""agent 数据落点的**唯一装配点**（v2 统一布局）。

目标布局：

    data/<agent_id>/
        agent_config.json      # 运行时配置（唯一一份）
        soul.json              # 灵魂配置
        personality.json       # 人格特质
        sleep_settings.json    # 睡眠设置
        media_config.json      # 媒体存储配置
        seen_cursors.json      # 协作游标
        context_ledger.db      # 上下文淘汰账本（SQLite）
        checkpoints.git/       # 检查点 bare 仓库
        sessions/              # 会话文件（原 data/sessions/<id>）
        workspaces/            # agent 工作区（原 agent_workspaces/<id>）
        memory/                # 记忆库与附件（原 <workspace>/memory）
        skills/                # agent 私库（原 data/agents/<id>/skills）
        proposals/             # RSI 提案台账
        evolution/             # 进化评测/证据
        trajectories/<user>/   # 轨迹（原 data/trajectories/<user>/<id>）

不随 agent 私有化的全局面（仍留在数据根）：`agents/agents.json` 登记索引、
`knowledge/`、`users.db` 等跨 agent 共享库。

`NEUROVA_AGENT_WORKSPACES_DIR` 仍可注入，但注入的是**agent 根目录的父目录**；
注入后形状与生产同构，不允许再退回 `agent_workspaces/<id>` 这种扁平旧形态。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, List

AGENT_WORKSPACES_ENV = "NEUROVA_AGENT_WORKSPACES_DIR"

_DEFAULT_AGENT_ID = "default"
_SAFE_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# data/ 下由其他子系统共享、绝不能当成 agent 根目录的名字。
# 新增全局数据根时同步补这里；发现侧与写入侧共用同一份拒绝名单。
RESERVED_AGENT_ROOT_NAMES = frozenset(
    {
        "admin",
        "agents",
        "annotations",
        "approval",
        "attachments",
        "audit",
        "backups",
        "checkpoints",
        "collaboration",
        "context_ledger",
        "dlq",
        "evolution",
        "experience_knowledge",
        "generated_skills",
        "generations",
        "knowledge",
        "knowledge_graph",
        "knowledge_ingress",
        "language",
        "llm",
        "marketplace",
        "media",
        "media_config",
        "memory_layer",
        "memory_pending",
        "models",
        "negative_screen",
        "outbox",
        "outputs",
        "personality",
        "public",
        "resource_quota",
        "security",
        "seen-cursors",
        "sessions",
        "settings",
        "shared_config",
        "skills",
        "sleep_settings",
        "storage",
        "tools",
        "trajectories",
        "uploads",
        "users",
    }
)

# agent 根目录下出现任一子项即可判定"这是 agent 根"，发现侧据此区分全局目录。
_AGENT_ROOT_MARKERS = (
    "agent_config.json",
    "soul.json",
    "personality.json",
    "sleep_settings.json",
    "media_config.json",
    "seen_cursors.json",
    "context_ledger.db",
    "checkpoints.git",
    "sessions",
    "workspaces",
    "memory",
    "skills",
    "proposals",
    "evolution",
    "trajectories",
)


def _resolve_agent_id(agent_id: str) -> str:
    value = str(agent_id or "").strip() or _DEFAULT_AGENT_ID
    if not _SAFE_AGENT_ID_RE.fullmatch(value):
        raise ValueError(f"非法 agent_id: {agent_id!r}（只允许字母/数字/下划线/连字符）")
    if value in RESERVED_AGENT_ROOT_NAMES:
        raise ValueError(
            f"agent_id {value!r} 与数据根下的全局目录同名，不能作为 agent 根目录"
        )
    return value


def is_reserved_agent_id(agent_id: str) -> bool:
    """该 id 是否被数据根下的全局目录占用（不能作为 agent 根目录名）。"""
    return str(agent_id or "").strip() in RESERVED_AGENT_ROOT_NAMES


def get_agent_root() -> Path:
    """agent 根目录的父目录（生产＝数据根；`NEUROVA_AGENT_WORKSPACES_DIR` 可注入）。"""
    injected = (os.environ.get(AGENT_WORKSPACES_ENV) or "").strip()
    if injected:
        return Path(injected)
    from neurova.core.data_root import get_data_root

    return get_data_root()


def get_agent_workspaces_root() -> Path:
    """兼容旧名：返回 agent 根目录的父目录（不再返回扁平 workspace 根）。"""
    return get_agent_root()


def get_agent_root_dir(agent_id: str = "") -> Path:
    """单个 agent 的根目录 `data/<agent_id>/`（agent_id 空值回落 default）。"""
    return get_agent_root() / _resolve_agent_id(agent_id)


def get_agent_workspace_dir(agent_id: str = "") -> Path:
    """agent 工作区 `data/<agent_id>/workspaces/`。"""
    return get_agent_root_dir(agent_id) / "workspaces"


def get_agent_memory_dir(agent_id: str = "") -> Path:
    """agent 记忆目录 `data/<agent_id>/memory/`。"""
    return get_agent_root_dir(agent_id) / "memory"


def get_agent_memory_db_path(agent_id: str = "") -> Path:
    """记忆主库 `data/<agent_id>/memory/memory.db`。"""
    return get_agent_memory_dir(agent_id) / "memory.db"


def get_agent_sessions_dir(agent_id: str = "") -> Path:
    """agent 会话目录 `data/<agent_id>/sessions/`。"""
    return get_agent_root_dir(agent_id) / "sessions"


def get_agent_config_path(agent_id: str = "") -> Path:
    """agent 运行时配置 `data/<agent_id>/agent_config.json`。"""
    return get_agent_root_dir(agent_id) / "agent_config.json"


def get_agent_soul_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "soul.json"


def get_agent_personality_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "personality.json"


def get_agent_sleep_settings_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "sleep_settings.json"


def get_agent_media_config_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "media_config.json"


def get_agent_cursors_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "seen_cursors.json"


def get_agent_context_ledger_path(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "context_ledger.db"


def get_agent_checkpoints_dir(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "checkpoints.git"


def get_agent_skills_dir(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "skills"


def get_agent_proposals_dir(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "proposals"


def get_agent_evolution_dir(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "evolution"


def get_agent_trajectories_dir(agent_id: str = "") -> Path:
    return get_agent_root_dir(agent_id) / "trajectories"


def get_agent_trajectory_dir(agent_id: str = "", user_id: str = "") -> Path:
    return get_agent_trajectories_dir(agent_id) / _safe_path_segment(user_id)


def ensure_agent_root_dir(agent_id: str = "") -> Path:
    target = get_agent_root_dir(agent_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_agent_workspace_dir(agent_id: str = "") -> Path:
    target = get_agent_workspace_dir(agent_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_agent_memory_dir(agent_id: str = "") -> Path:
    target = get_agent_memory_dir(agent_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def agentMemoryDirUnder(agentRoot) -> Path:
    """agent 根目录下"记忆落点"那一段的唯一拼法（`<agentRoot>/memory`）。

    参数是 **agent 根目录**（`get_agent_root_dir`），不是 workspace。
    """
    return Path(agentRoot) / "memory"


def agentMemoryDbPathUnder(agentRoot) -> Path:
    """记忆主库路径 `<agentRoot>/memory/memory.db`（参数同 `agentMemoryDirUnder`）。"""
    return agentMemoryDirUnder(agentRoot) / "memory.db"


def _safe_path_segment(value: str) -> str:
    segment = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip()
    return segment or "default"


def is_agent_root(path: Path) -> bool:
    """目录是否像一个 agent 根（用于发现，不用于写入）。"""
    if not path.is_dir() or path.name in RESERVED_AGENT_ROOT_NAMES:
        return False
    if path.name.startswith("."):
        return False
    return any((path / marker).exists() for marker in _AGENT_ROOT_MARKERS)


def discover_agent_ids() -> List[str]:
    """发现当前数据根下的 agent id（文件系统标记 + 全局登记索引）。

    只认 agent 根标记，不把 `knowledge/`、`sessions/` 这类全局目录误当 agent。
    登记索引文件损坏时退回文件系统发现，不让一个坏 JSON 阻断启动。
    """
    root = get_agent_root()
    found = set()
    if root.is_dir():
        for child in root.iterdir():
            if is_agent_root(child):
                found.add(child.name)

    registry = root / "agents" / "agents.json"
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for agent_id in raw:
                try:
                    _resolve_agent_id(agent_id)
                except ValueError:
                    continue
                found.add(str(agent_id))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return sorted(found)


def iter_agent_roots(agent_ids: Iterable[str] | None = None) -> Iterable[Path]:
    ids = list(agent_ids) if agent_ids is not None else discover_agent_ids()
    for agent_id in ids:
        yield get_agent_root_dir(agent_id)
