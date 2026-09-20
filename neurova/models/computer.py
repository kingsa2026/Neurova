"""
Computer Model - 计算资源抽象
"""

import uuid
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class ComputerKind(str, Enum):
    """Computer 类型"""

    CLOUD = "cloud"           # Neurova 托管
    LOCAL = "local"           # 用户本地部署 (Mac/PC)
    VPS = "vps"               # 远程 VPS

class ComputerEngine(str, Enum):
    """Computer 引擎类型"""

    MANAGED = "managed"       # Neurova managed (OpenAI Responses API)
    CLAUDE_CODE = "claude"    # Claude Code CLI
    CODEX = "codex"           # GitHub Codex CLI
    GROK_BUILD = "grok"       # Grok Build
    CURSOR = "cursor"         # Cursor Agent
    OPENCODE = "opencode"     # OpenCode
    PI = "pi"                 # pi CLI
    GEMINI = "gemini"         # Gemini CLI
    QWEN = "qwen"             # Qwen Code
    ANTIGRAVITY = "antigravity"  # Antigravity
    ZCODE = "zcode"           # ZCode (via ACP bridge)

class ComputerStatus(str, Enum):
    """Computer 状态"""

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"

@dataclass
class Computer:
    """
    Computer: 计算资源抽象

    - kind: 'cloud' | 'local' | 'vps'
    - engine: managed or specific CLI tool
    - status tracking for heartbeat
    """

    computer_id: str = field(default_factory=lambda: f"comp_{uuid.uuid4().hex[:12]}")
    name: str = ""
    kind: ComputerKind = ComputerKind.CLOUD
    engine: ComputerEngine = ComputerEngine.MANAGED
    status: ComputerStatus = ComputerStatus.OFFLINE
    last_seen_at: Optional[float] = None

    # Ownership & Association
    owner_user_id: str = ""          # 属主用户 ID
    company_id: str = ""             # 所属公司 ID

    # Agents hosted on this computer
    agents: Dict[str, Any] = field(default_factory=dict)  # agent_id -> Agent dict

    # BYOA specific fields
    daemon_token: Optional[str] = None      # 配对 token (device credential)
    daemon_version: Optional[str] = None    # daemon 版本
    paired_at: Optional[float] = None       # 配对时间
    revoked_at: Optional[float] = None      # 撤销时间
    credential_hash: Optional[str] = None   # SHA256 hash of device token

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "computer_id": self.computer_id,
            "name": self.name,
            "kind": self.kind.value,
            "engine": self.engine.value,
            "status": self.status.value,
            "last_seen_at": self.last_seen_at,
            "owner_user_id": self.owner_user_id,
            "company_id": self.company_id,
            "agents": {aid: a for aid, a in self.agents.items()},
            "daemon_token": self.daemon_token,
            "daemon_version": self.daemon_version,
            "paired_at": self.paired_at,
            "revoked_at": self.revoked_at,
            "credential_hash": self.credential_hash,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Computer":
        """从字典创建"""
        comp = cls(
            computer_id=data.get("computer_id", ""),
            name=data.get("name", ""),
            kind=ComputerKind(data.get("kind", "cloud")),
            engine=ComputerEngine(data.get("engine", "managed")),
            status=ComputerStatus(data.get("status", "offline")),
            last_seen_at=data.get("last_seen_at"),
            owner_user_id=data.get("owner_user_id", ""),
            company_id=data.get("company_id", ""),
            daemon_token=data.get("daemon_token"),
            daemon_version=data.get("daemon_version"),
            paired_at=data.get("paired_at"),
            revoked_at=data.get("revoked_at"),
            credential_hash=data.get("credential_hash"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

        # Load agents
        for aid, adata in data.get("agents", {}).items():
            if isinstance(adata, dict):
                comp.agents[aid] = adata
            else:
                comp.agents[aid] = adata.to_dict() if hasattr(adata, 'to_dict') else str(adata)

        return comp

    def is_online(self) -> bool:
        """检查是否在线"""
        return self.status == ComputerStatus.ONLINE

    def is_byoa(self) -> bool:
        """检查是否为 BYOA (Bring Your Own Agent)"""
        return self.kind in [ComputerKind.LOCAL, ComputerKind.VPS]

    def is_cloud(self) -> bool:
        """检查是否为云托管"""
        return self.kind == ComputerKind.CLOUD

    def heartbeat(self, version: Optional[str] = None) -> None:
        """更新心跳"""
        self.status = ComputerStatus.ONLINE
        self.last_seen_at = time.time()
        if version:
            self.daemon_version = version
        self.updated_at = time.time()

    def offline(self) -> None:
        """标记离线"""
        self.status = ComputerStatus.OFFLINE
        self.updated_at = time.time()

    def assign_agent(self, agent_id: str, agent_data: Any) -> None:
        """分配 Agent 到 Computer"""
        if isinstance(agent_data, dict):
            self.agents[agent_id] = agent_data
        else:
            self.agents[agent_id] = agent_data.to_dict() if hasattr(agent_data, 'to_dict') else str(agent_data)

    def remove_agent(self, agent_id: str) -> bool:
        """移除 Agent"""
        if agent_id in self.agents:
            del self.agents[agent_id]
            return True
        return False

    def __repr__(self) -> str:
        status_icon = "●" if self.is_online() else "○"
        byoa_tag = " [BYOA]" if self.is_byoa() else ""
        return f"<Computer {self.name} {status_icon}{byoa_tag}>"

# Global instance management
_computer_manager_instance: Optional["ComputerManager"] = None
_computer_manager_lock = threading.Lock()

def get_computer_manager() -> "ComputerManager":
    """获取全局 ComputerManager 实例 (Singleton)"""
    global _computer_manager_instance

    if _computer_manager_instance is None:
        with _computer_manager_lock:
            if _computer_manager_instance is None:
                _computer_manager_instance = ComputerManager()

    return _computer_manager_instance

def reset_computer_manager() -> None:
    """重置 ComputerManager 实例 (用于测试)"""
    global _computer_manager_instance
    _computer_manager_instance = None
