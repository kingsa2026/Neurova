"""
Computer Manager - 计算资源管理器
"""

import json
import shutil
import threading
import time
from pathlib import Path
from typing import List, Optional, Dict, Set, Any

from neurova.core.logger import get_logger
from neurova.models.computer import (
    Computer,
    ComputerKind,
    ComputerEngine,
    ComputerStatus,
    get_computer_manager,
)

logger = get_logger(__name__)

class ComputerManager:
    """
    Computer 管理器

    功能:
    1. Computer 生命周期管理
    2. Agent 分配与绑定
    3. Heartbeat 处理
    4. BYOA 配对管理
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化 ComputerManager

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir) if data_dir else Path("data/computers")

        # Thread safety
        self._lock = threading.RLock()

        # Storage: {computer_id: Computer}
        self._computers: Dict[str, Computer] = {}

        # Indexes
        self._user_computers: Dict[str, Set[str]] = {}  # user_id → set(computer_id)
        self._company_computers: Dict[str, Set[str]] = {}  # company_id → set(computer_id)

        # Initialize
        self._on_init()

        logger.info("ComputerManager initialized")

    def _on_init(self) -> None:
        """初始化回调"""
        self._init_dirs()
        self._load_computers()

    def _init_dirs(self) -> None:
        """初始化目录结构"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)

            # Create subdirectories
            (self.data_dir / "devices").mkdir(exist_ok=True)
            (self.data_dir / "tokens").mkdir(exist_ok=True)
            (self.data_dir / "backups").mkdir(exist_ok=True)

            logger.info(f"Initialized computer directories: {self.data_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize directories: {e}")

    def _load_computers(self) -> None:
        """加载 Computer 数据"""
        try:
            devices_dir = self.data_dir / "devices"
            if not devices_dir.exists():
                return

            for device_file in devices_dir.glob("*.json"):
                try:
                    with open(device_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    computer = Computer.from_dict(data)
                    self._computers[computer.computer_id] = computer

                    # Update indexes
                    if computer.owner_user_id:
                        if computer.owner_user_id not in self._user_computers:
                            self._user_computers[computer.owner_user_id] = set()
                        self._user_computers[computer.owner_user_id].add(computer.computer_id)

                    if computer.company_id:
                        if computer.company_id not in self._company_computers:
                            self._company_computers[computer.company_id] = set()
                        self._company_computers[computer.company_id].add(computer.computer_id)

                except Exception as e:
                    logger.warning(f"Failed to load computer {device_file}: {e}")

            logger.info(f"Loaded {len(self._computers)} computers")

        except Exception as e:
            logger.error(f"Failed to load computers: {e}")

    def _save_computer(self, computer: Computer) -> bool:
        """保存 Computer"""
        try:
            devices_dir = self.data_dir / "devices"
            device_file = devices_dir / f"{computer.computer_id}.json"

            with open(device_file, "w", encoding="utf-8") as f:
                json.dump(computer.to_dict(), f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved computer: {computer.computer_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save computer {computer.computer_id}: {e}")
            return False

    def create_computer(
        self,
        name: str,
        owner_user_id: str,
        kind: ComputerKind = ComputerKind.CLOUD,
        engine: ComputerEngine = ComputerEngine.MANAGED,
        company_id: str = "",
    ) -> Optional[Computer]:
        """
        创建 Computer

        Args:
            name: Computer 名称
            owner_user_id: 所有者用户 ID
            kind: 类型 (cloud/local/vps)
            engine: 引擎类型
            company_id: 所属公司

        Returns:
            创建的 Computer
        """
        with self._lock:
            try:
                computer = Computer(
                    name=name,
                    owner_user_id=owner_user_id,
                    kind=kind,
                    engine=engine,
                    company_id=company_id,
                    status=ComputerStatus.ONLINE if kind == ComputerKind.CLOUD else ComputerStatus.OFFLINE,
                )

                # Store
                self._computers[computer.computer_id] = computer

                # Update indexes
                if owner_user_id not in self._user_computers:
                    self._user_computers[owner_user_id] = set()
                self._user_computers[owner_user_id].add(computer.computer_id)

                if company_id:
                    if company_id not in self._company_computers:
                        self._company_computers[company_id] = set()
                    self._company_computers[company_id].add(computer.computer_id)

                # Save to disk
                self._save_computer(computer)

                logger.info(f"Created computer: {computer.computer_id} by {owner_user_id}")
                return computer

            except Exception as e:
                logger.error(f"Failed to create computer: {e}")
                return None

    def get_computer(self, computer_id: str, user_id: Optional[str] = None) -> Optional[Computer]:
        """
        获取 Computer (带权限检查)

        Args:
            computer_id: Computer ID
            user_id: 用户 ID (用于权限检查)

        Returns:
            Computer 对象或 None
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return None

            # Permission check: owner or admin
            if user_id and computer.owner_user_id != user_id:
                # TODO: Check admin role
                # For now, allow access if company match
                if computer.company_id and user_id.endswith(f"@{computer.company_id}"):
                    pass  # Allow
                else:
                    return None

            return computer

    def list_user_computers(self, user_id: str) -> List[Computer]:
        """
        列出用户的 Computers

        Args:
            user_id: 用户 ID

        Returns:
            Computer 列表
        """
        with self._lock:
            computer_ids = self._user_computers.get(user_id, set())
            return [
                self._computers[cid]
                for cid in computer_ids
                if cid in self._computers
            ]

    def heartbeat(self, computer_id: str, version: Optional[str] = None) -> bool:
        """
        接收 Computer heartbeat

        Args:
            computer_id: Computer ID
            version: daemon 版本

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                logger.warning(f"Heartbeat from unknown computer: {computer_id}")
                return False

            computer.heartbeat(version=version)
            logger.debug(f"Heartbeat from {computer_id}")
            return True

    def offline_computer(self, computer_id: str) -> bool:
        """
        标记 Computer 离线

        Args:
            computer_id: Computer ID

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if computer:
                computer.offline()
                logger.warning(f"Computer marked offline: {computer_id}")
                return True
            return False

    def assign_agent_to_computer(self, computer_id: str, agent_id: str, agent_data: Any) -> bool:
        """
        分配 Agent 到 Computer

        Args:
            computer_id: Computer ID
            agent_id: Agent ID
            agent_data: Agent 数据

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return False

            computer.assign_agent(agent_id, agent_data)
            self._save_computer(computer)

            logger.info(f"Assigned agent {agent_id} to computer {computer_id}")
            return True

    def remove_agent_from_computer(self, computer_id: str, agent_id: str) -> bool:
        """
        从 Computer 移除 Agent

        Args:
            computer_id: Computer ID
            agent_id: Agent ID

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return False

            if computer.remove_agent(agent_id):
                self._save_computer(computer)
                logger.info(f"Removed agent {agent_id} from computer {computer_id}")
                return True
            return False

    def pair_byoa_computer(
        self,
        computer_id: str,
        pair_token: str,
        host_name: str,
        available_engines: List[str],
        daemon_version: str,
        supervised: bool = False,
    ) -> Optional[Computer]:
        """
        BYOA Computer 配对

        Args:
            computer_id: Computer ID
            pair_token: 配对 token
            host_name: 主机名
            available_engines: 可用引擎列表
            daemon_version: daemon 版本
            supervised: 是否作为服务运行

        Returns:
            Computer 对象或 None
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return None

            # Generate device token
            import hashlib
            device_token = hashlib.sha256(pair_token.encode()).hexdigest()

            computer.daemon_token = device_token
            computer.daemon_version = daemon_version
            computer.paired_at = time.time()
            computer.credential_hash = device_token

            # Update metadata
            computer.metadata["host_name"] = host_name
            computer.metadata["available_engines"] = available_engines
            computer.metadata["supervised"] = supervised

            self._save_computer(computer)

            logger.info(f"Paired BYOA computer: {computer_id}")
            return computer

    def revoke_computer(self, computer_id: str) -> bool:
        """
        撤销 Computer 访问

        Args:
            computer_id: Computer ID

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return False

            computer.revoked_at = time.time()
            computer.status = ComputerStatus.OFFLINE
            computer.daemon_token = None

            self._save_computer(computer)

            logger.warning(f"Computer revoked: {computer_id}")
            return True

    def delete_computer(self, computer_id: str, hard: bool = False) -> bool:
        """
        删除 Computer

        Args:
            computer_id: Computer ID
            hard: 硬删除 (vs soft delete)

        Returns:
            是否成功
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return False

            if hard:
                # Hard delete: remove files
                try:
                    device_file = self.data_dir / "devices" / f"{computer_id}.json"
                    if device_file.exists():
                        device_file.unlink()

                    # Remove associated data
                    tokens_dir = self.data_dir / "tokens" / computer_id
                    if tokens_dir.exists():
                        shutil.rmtree(tokens_dir)

                    # Remove from storage
                    del self._computers[computer_id]

                    # Update indexes
                    for user_id in self._user_computers:
                        self._user_computers[user_id].discard(computer_id)

                    logger.info(f"Hard deleted computer: {computer_id}")
                    return True

                except Exception as e:
                    logger.error(f"Failed to hard delete computer {computer_id}: {e}")
                    return False
            else:
                # Soft delete
                computer.status = ComputerStatus.DELETED
                computer.deleted_at = time.time()
                self._save_computer(computer)

                logger.info(f"Soft deleted computer: {computer_id}")
                return True

    def admin_list_all_computers(self, admin_id: str, include_deleted: bool = False) -> List[Computer]:
        """
        管理员列出所有 Computers

        Args:
            admin_id: 管理员 ID
            include_deleted: 是否包含已删除

        Returns:
            Computer 列表
        """
        with self._lock:
            computers = []

            for computer in self._computers.values():
                if not include_deleted and computer.status.value == "deleted":
                    continue
                computers.append(computer)

            # Sort by created_at descending
            computers.sort(key=lambda c: c.created_at or 0, reverse=True)

            return computers

    def get_cloud_computer(self) -> Optional[Computer]:
        """获取 Cloud Computer 实例 (每公司一行)"""
        with self._lock:
            for computer in self._computers.values():
                if computer.kind == ComputerKind.CLOUD:
                    return computer
            return None

    def cleanup_offline_computers(self, timeout_seconds: int = 90 * 60) -> int:
        """
        清理离线 Computer (超过超时时间)

        Args:
            timeout_seconds: 超时时间 (秒)

        Returns:
            清理数量
        """
        with self._lock:
            cleaned_count = 0
            current_time = time.time()

            for computer_id, computer in self._computers.items():
                if computer.last_seen_at:
                    if current_time - computer.last_seen_at > timeout_seconds:
                        self.offline_computer(computer_id)
                        cleaned_count += 1

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} offline computers")

            return cleaned_count

# Global instance management
_computer_manager_instance: Optional[ComputerManager] = None
_computer_manager_lock = threading.Lock()

def get_computer_manager_singleton() -> ComputerManager:
    """获取全局 ComputerManager 实例 (Singleton)"""
    global _computer_manager_instance

    if _computer_manager_instance is None:
        with _computer_manager_lock:
            if _computer_manager_instance is None:
                _computer_manager_instance = ComputerManager()

    return _computer_manager_instance

def reset_computer_manager_singleton() -> None:
    """重置 ComputerManager 实例 (用于测试)"""
    global _computer_manager_instance
    _computer_manager_instance = None
