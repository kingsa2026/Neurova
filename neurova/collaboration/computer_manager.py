"""
Computer Manager - 计算资源管理器
"""

import hashlib
import json
import secrets
import shutil
import threading
import time
from typing import List, Optional, Dict, Set, Any

from neurova.core.logger import get_logger
from neurova.models.computer import (
    Computer,
    ComputerKind,
    ComputerEngine,
    ComputerPairing,
    ComputerStatus,
)
from neurova.core.data_root import callerPath

logger = get_logger(__name__)

PAIR_TOKEN_TTL_SECONDS = 300
MAX_PAIR_TOKEN_TTL_SECONDS = 300

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
        self.data_dir = callerPath(data_dir, "computers")

        # Thread safety
        self._lock = threading.RLock()

        # Storage: {computer_id: Computer}
        self._computers: Dict[str, Computer] = {}

        # Indexes
        self._user_computers: Dict[str, Set[str]] = {}  # user_id → set(computer_id)
        self._company_computers: Dict[str, Set[str]] = {}  # company_id → set(computer_id)

        # 一次性配对票据只活在当前进程；键为摘要，绑定设备与属主，消费在同一 RLock 内完成。
        self._pair_tickets: Dict[str, Dict[str, Any]] = {}

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

    def _is_admin_user(self, user_id: str) -> bool:
        """管理员判定（审计 §3.4-11）：users 表 role == 'admin'。

        任何查表失败（查无此人/非数字 id/用户库不可用）都按非管理员处理——
        fail-closed，不给"公司后缀匹配"那类可伪造旁路留位置。
        """
        uid = str(user_id or "").strip()
        if not uid:
            return False
        try:
            from neurova.auth.user_model import UserModel

            row = UserModel().get_user_by_id(int(uid))
            return str(getattr(row, "role", "") or "").lower() == "admin"
        except Exception:  # noqa: BLE001 - 判定不了就按非管理员
            return False

    def get_computer(self, computer_id: str, user_id: Optional[str] = None) -> Optional[Computer]:
        """
        获取 Computer (带权限检查)

        Args:
            computer_id: Computer ID
            user_id: 用户 ID (用于权限检查)；缺省＝内部取数通道
                （如 daemon 心跳先取数、再验配对令牌），调用方须自行完成鉴权

        Returns:
            Computer 对象或 None
        """
        with self._lock:
            computer = self._computers.get(computer_id)
            if not computer:
                return None

            # Permission check: owner or admin。
            # 审计 §3.4-11：原 TODO 落成"company_id 后缀匹配即放行"——
            # 任何登录用户把 id 写成 user@{company_id} 就能读他人计算节点。
            # 现收口为 **属主或管理员**，其余一律拒绝。
            # None 是 daemon 心跳验签前的内部取数通道；空字符串不是内部通道。
            if user_id is not None:
                uid = str(user_id).strip()
                if not uid:
                    return None
                if computer.owner_user_id != uid and not self._is_admin_user(uid):
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
            uid = str(user_id or "").strip()
            if not uid:
                return []
            computer_ids = self._user_computers.get(uid, set())
            return [
                self._computers[cid]
                for cid in computer_ids
                if cid in self._computers
                and self._computers[cid].status != ComputerStatus.DELETED
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

    def _purgeExpiredPairTickets(self, now: float) -> None:
        for digest, ticket in list(self._pair_tickets.items()):
            if ticket["expires_at"] <= now:
                del self._pair_tickets[digest]

    def _invalidatePairTickets(self, computer_id: str) -> None:
        for digest, ticket in list(self._pair_tickets.items()):
            if ticket["computer_id"] == computer_id:
                del self._pair_tickets[digest]

    def issue_pair_token(
        self,
        computer_id: str,
        user_id: str,
        ttl_seconds: float = PAIR_TOKEN_TTL_SECONDS,
    ) -> Optional[str]:
        """属主签发短期一次性配对票据；同一设备只保留最后一张。"""
        with self._lock:
            computer = self.get_computer(computer_id, user_id=user_id)
            if not computer or computer.status == ComputerStatus.DELETED:
                return None
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, (int, float))
                or ttl_seconds <= 0
                or ttl_seconds > MAX_PAIR_TOKEN_TTL_SECONDS
            ):
                return None

            now = time.time()
            self._purgeExpiredPairTickets(now)
            self._invalidatePairTickets(computer_id)
            pair_token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(pair_token.encode("utf-8")).hexdigest()
            self._pair_tickets[digest] = {
                "computer_id": computer_id,
                "owner_user_id": str(user_id).strip(),
                "expires_at": now + ttl_seconds,
            }
            return pair_token

    def pair_byoa_computer(
        self,
        computer_id: str,
        pair_token: str,
        host_name: str,
        available_engines: List[str],
        daemon_version: str,
        supervised: bool = False,
        *,
        user_id: str,
    ) -> Optional[ComputerPairing]:
        """原子消费配对票据，另发长期 daemon 凭据；原文只在返回值中出现。"""
        with self._lock:
            computer = self.get_computer(computer_id, user_id=user_id)
            if not computer or computer.status == ComputerStatus.DELETED:
                return None

            presented = str(pair_token or "").strip()
            if not presented:
                return None
            digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
            ticket = self._pair_tickets.pop(digest, None)
            if not ticket:
                return None
            if (
                ticket["computer_id"] != computer_id
                or ticket["owner_user_id"] != str(user_id).strip()
                or ticket["expires_at"] <= time.time()
            ):
                return None

            daemon_token = secrets.token_urlsafe(32)
            computer.daemon_token = hashlib.sha256(daemon_token.encode("utf-8")).hexdigest()
            computer.daemon_version = daemon_version
            computer.paired_at = time.time()
            computer.revoked_at = None
            computer.updated_at = computer.paired_at
            computer.metadata["host_name"] = host_name
            computer.metadata["available_engines"] = available_engines
            computer.metadata["supervised"] = supervised

            if not self._save_computer(computer):
                return None

            logger.info(f"Paired BYOA computer: {computer_id}")
            return ComputerPairing(computer=computer, daemon_token=daemon_token)

    def revoke_computer(self, computer_id: str, *, user_id: str) -> bool:
        """撤销 Computer 访问；只有属主或管理员可操作。"""
        with self._lock:
            computer = self.get_computer(computer_id, user_id=user_id)
            if not computer:
                return False

            self._invalidatePairTickets(computer_id)
            computer.revoked_at = time.time()
            computer.status = ComputerStatus.OFFLINE
            computer.daemon_token = None
            computer.updated_at = computer.revoked_at
            saved = self._save_computer(computer)

            if saved:
                logger.warning(f"Computer revoked: {computer_id}")
            return saved

    def delete_computer(
        self,
        computer_id: str,
        hard: bool = False,
        *,
        user_id: str,
    ) -> bool:
        """删除 Computer；computer_id 只定位，写权限由 user_id 判定。"""
        with self._lock:
            computer = self.get_computer(computer_id, user_id=user_id)
            if not computer:
                return False

            self._invalidatePairTickets(computer_id)
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
                    for company_id in self._company_computers:
                        self._company_computers[company_id].discard(computer_id)

                    logger.info(f"Hard deleted computer: {computer_id}")
                    return True

                except Exception as e:
                    logger.error(f"Failed to hard delete computer {computer_id}: {e}")
                    return False

            computer.status = ComputerStatus.DELETED
            computer.deleted_at = time.time()
            computer.daemon_token = None
            computer.updated_at = computer.deleted_at
            saved = self._save_computer(computer)

            if saved:
                logger.info(f"Soft deleted computer: {computer_id}")
            return saved

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
                if computer.kind == ComputerKind.CLOUD and computer.status != ComputerStatus.DELETED:
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
