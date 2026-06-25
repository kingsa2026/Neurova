from __future__ import annotations

"""
Neurova 安全审计日志模块

功能:
1. 完整记录所有敏感操作（登录、配置修改、权限变更等）
2. 操作人、操作时间、操作内容、影响范围
3. 可追溯的审计链
4. 审计日志导出（CSV/JSON）

审计事件类型:
- AUTH_LOGIN, AUTH_LOGOUT, AUTH_FAILED
- CONFIG_CHANGE, PERMISSION_CHANGE
- USER_CHANGE, ROLE_CHANGE, API_KEY_CHANGE
"""

import csv
import datetime
import json
from neurova.core.logger import get_logger
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class AuditEventType(str, Enum):
    """审计事件类型"""

    AUTH_LOGIN = "auth_login"
    AUTH_LOGOUT = "auth_logout"
    AUTH_FAILED = "auth_failed"
    CONFIG_CHANGE = "config_change"
    PERMISSION_CHANGE = "permission_change"
    USER_CHANGE = "user_change"
    ROLE_CHANGE = "role_change"
    API_KEY_CHANGE = "api_key_change"
    SYSTEM_EVENT = "system_event"
    SECURITY_EVENT = "security_event"
    DATA_ACCESS = "data_access"
    TOOL_EXECUTION = "tool_execution"


class AuditSeverity(str, Enum):
    """审计严重级别"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditLogEntry:
    """审计日志条目"""

    event_type: AuditEventType
    severity: AuditSeverity
    user_id: str = ""
    action: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ip_address: str = ""
    user_agent: str = ""
    resource_type: str = ""
    resource_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "user_id": self.user_id,
            "action": self.action,
            "details": self.details,
            "timestamp": self.timestamp,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditLogEntry":
        """从字典创建"""
        return cls(
            event_type=AuditEventType(data.get("event_type", "system_event")),
            severity=AuditSeverity(data.get("severity", "low")),
            user_id=data.get("user_id", ""),
            action=data.get("action", ""),
            details=data.get("details", {}),
            timestamp=data.get("timestamp", time.time()),
            ip_address=data.get("ip_address", ""),
            user_agent=data.get("user_agent", ""),
            resource_type=data.get("resource_type", ""),
            resource_id=data.get("resource_id", ""),
            metadata=data.get("metadata", {}),
        )


# Alias for backward compatibility
AuditLog = AuditLogEntry


class AuditLogger:
    """
    审计日志管理器

    提供完整的审计日志记录、查询、导出功能。
    使用 SQLite 存储，线程安全。
    """

    _instance: Optional["AuditLogger"] = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None):
        """单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化审计日志管理器

        Args:
            db_path: 数据库路径
        """
        if self._initialized:
            return

        self._db_path = db_path or str(Path.home() / ".neurova" / "audit.db")
        self._ensure_db_dir()
        self._init_db()
        self._initialized = True

        logger.info("AuditLogger initialized with db: %s", self._db_path)

    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    user_id TEXT,
                    action TEXT,
                    details TEXT,
                    timestamp REAL NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    resource_type TEXT,
                    resource_id TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON audit_logs(event_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON audit_logs(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_logs(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_severity ON audit_logs(severity)")

            conn.commit()
            conn.close()

            logger.info("Audit database initialized")

        except Exception as e:
            logger.error("Failed to initialize audit database: %s", e)
            raise

    def log(self, entry: AuditLogEntry) -> bool:
        """
        记录审计日志

        Args:
            entry: 审计日志条目

        Returns:
            bool: 是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    event_type, severity, user_id, action, details,
                    timestamp, ip_address, user_agent, resource_type,
                    resource_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry.event_type.value,
                    entry.severity.value,
                    entry.user_id,
                    entry.action,
                    json.dumps(entry.details),
                    entry.timestamp,
                    entry.ip_address,
                    entry.user_agent,
                    entry.resource_type,
                    entry.resource_id,
                    json.dumps(entry.metadata),
                ),
            )

            conn.commit()
            conn.close()

            logger.debug("Audit log recorded: %s - %s", entry.event_type.value, entry.action)
            return True

        except Exception as e:
            logger.error("Failed to record audit log: %s", e)
            return False

    def log_auth_login(self, user_id: str, ip_address: str = "", user_agent: str = "", success: bool = True) -> bool:
        """记录登录事件"""
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGIN if success else AuditEventType.AUTH_FAILED,
            severity=AuditSeverity.MEDIUM if success else AuditSeverity.HIGH,
            user_id=user_id,
            action="Login successful" if success else "Login failed",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self.log(entry)

    def log_auth_logout(self, user_id: str, ip_address: str = "") -> bool:
        """记录登出事件"""
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGOUT,
            severity=AuditSeverity.LOW,
            user_id=user_id,
            action="User logged out",
            ip_address=ip_address,
        )
        return self.log(entry)

    def log_config_change(self, user_id: str, config_key: str, old_value: Any = None, new_value: Any = None) -> bool:
        """记录配置变更"""
        entry = AuditLogEntry(
            event_type=AuditEventType.CONFIG_CHANGE,
            severity=AuditSeverity.HIGH,
            user_id=user_id,
            action=f"Config changed: {config_key}",
            details={
                "config_key": config_key,
                "old_value": str(old_value) if old_value is not None else None,
                "new_value": str(new_value) if new_value is not None else None,
            },
        )
        return self.log(entry)

    def log_user_change(
        self, user_id: str, target_user_id: str, change_type: str, details: Dict[str, Any] = None
    ) -> bool:
        """记录用户变更"""
        entry = AuditLogEntry(
            event_type=AuditEventType.USER_CHANGE,
            severity=AuditSeverity.MEDIUM,
            user_id=user_id,
            action=f"User {change_type}: {target_user_id}",
            details=details or {},
            resource_type="user",
            resource_id=target_user_id,
        )
        return self.log(entry)

    def log_role_change(self, user_id: str, target_user_id: str, old_role: str, new_role: str) -> bool:
        """记录角色变更"""
        entry = AuditLogEntry(
            event_type=AuditEventType.ROLE_CHANGE,
            severity=AuditSeverity.HIGH,
            user_id=user_id,
            action=f"Role changed for user {target_user_id}",
            details={"old_role": old_role, "new_role": new_role},
            resource_type="user",
            resource_id=target_user_id,
        )
        return self.log(entry)

    def log_api_key_change(self, user_id: str, api_key_id: str, action: str, details: Dict[str, Any] = None) -> bool:
        """记录 API 密钥变更"""
        entry = AuditLogEntry(
            event_type=AuditEventType.API_KEY_CHANGE,
            severity=AuditSeverity.MEDIUM,
            user_id=user_id,
            action=f"API key {action}: {api_key_id}",
            details=details or {},
            resource_type="api_key",
            resource_id=api_key_id,
        )
        return self.log(entry)

    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLogEntry]:
        """
        查询审计日志

        Args:
            event_type: 事件类型过滤
            user_id: 用户ID过滤
            severity: 严重级别过滤
            start_time: 开始时间
            end_time: 结束时间
            limit: 限制数量
            offset: 偏移量

        Returns:
            List[AuditLogEntry]: 审计日志列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            query = "SELECT * FROM audit_logs WHERE 1=1"
            params = []

            if event_type:
                query += " AND event_type = ?"
                params.append(event_type.value)

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if severity:
                query += " AND severity = ?"
                params.append(severity.value)

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)

            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            results = cursor.fetchall()
            conn.close()

            entries = []
            for row in results:
                entry = AuditLogEntry(
                    event_type=AuditEventType(row["event_type"]),
                    severity=AuditSeverity(row["severity"]),
                    user_id=row["user_id"] or "",
                    action=row["action"] or "",
                    details=json.loads(row["details"]) if row["details"] else {},
                    timestamp=row["timestamp"],
                    ip_address=row["ip_address"] or "",
                    user_agent=row["user_agent"] or "",
                    resource_type=row["resource_type"] or "",
                    resource_id=row["resource_id"] or "",
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )
                entries.append(entry)

            return entries

        except Exception as e:
            logger.error("Failed to query audit logs: %s", e)
            return []

    def get_by_id(self, log_id: int) -> Optional[AuditLogEntry]:
        """根据ID获取审计日志"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM audit_logs WHERE id = ?", (log_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            return AuditLogEntry(
                event_type=AuditEventType(row["event_type"]),
                severity=AuditSeverity(row["severity"]),
                user_id=row["user_id"] or "",
                action=row["action"] or "",
                details=json.loads(row["details"]) if row["details"] else {},
                timestamp=row["timestamp"],
                ip_address=row["ip_address"] or "",
                user_agent=row["user_agent"] or "",
                resource_type=row["resource_type"] or "",
                resource_id=row["resource_id"] or "",
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )

        except Exception as e:
            logger.error("Failed to get audit log by ID: %s", e)
            return None

    def get_statistics(self, start_time: Optional[float] = None, end_time: Optional[float] = None) -> Dict[str, Any]:
        """
        获取审计统计信息

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            Dict: 统计信息
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            query = "SELECT COUNT(*) as total FROM audit_logs WHERE 1=1"
            params = []

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)

            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)

            cursor.execute(query, params)
            total = cursor.fetchone()["total"]

            # 按事件类型统计
            query = "SELECT event_type, COUNT(*) as count FROM audit_logs WHERE 1=1"
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            query += " GROUP BY event_type"

            cursor.execute(query, params)
            by_event_type = {row["event_type"]: row["count"] for row in cursor.fetchall()}

            # 按严重级别统计
            query = "SELECT severity, COUNT(*) as count FROM audit_logs WHERE 1=1"
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            query += " GROUP BY severity"

            cursor.execute(query, params)
            by_severity = {row["severity"]: row["count"] for row in cursor.fetchall()}

            conn.close()

            return {
                "total": total,
                "by_event_type": by_event_type,
                "by_severity": by_severity,
                "time_range": {"start": start_time, "end": end_time},
            }

        except Exception as e:
            logger.error("Failed to get audit statistics: %s", e)
            return {}

    def export_csv(self, file_path: str, **kwargs) -> bool:
        """
        导出审计日志为 CSV

        Args:
            file_path: 文件路径
            **kwargs: 查询参数

        Returns:
            bool: 是否成功
        """
        try:
            entries = self.query(**kwargs)

            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # 写入表头
                writer.writerow(
                    [
                        "ID",
                        "Event Type",
                        "Severity",
                        "User ID",
                        "Action",
                        "Timestamp",
                        "IP Address",
                        "User Agent",
                        "Resource Type",
                        "Resource ID",
                        "Details",
                        "Metadata",
                    ]
                )

                # 写入数据
                for i, entry in enumerate(entries, 1):
                    writer.writerow(
                        [
                            i,
                            entry.event_type.value,
                            entry.severity.value,
                            entry.user_id,
                            entry.action,
                            datetime.datetime.fromtimestamp(entry.timestamp).isoformat(),
                            entry.ip_address,
                            entry.user_agent,
                            entry.resource_type,
                            entry.resource_id,
                            json.dumps(entry.details),
                            json.dumps(entry.metadata),
                        ]
                    )

            logger.info("Audit logs exported to CSV: %s", file_path)
            return True

        except Exception as e:
            logger.error("Failed to export audit logs to CSV: %s", e)
            return False

    def export_json(self, file_path: str, **kwargs) -> bool:
        """
        导出审计日志为 JSON

        Args:
            file_path: 文件路径
            **kwargs: 查询参数

        Returns:
            bool: 是否成功
        """
        try:
            entries = self.query(**kwargs)

            data = {
                "export_time": datetime.datetime.now().isoformat(),
                "total_entries": len(entries),
                "entries": [entry.to_dict() for entry in entries],
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info("Audit logs exported to JSON: %s", file_path)
            return True

        except Exception as e:
            logger.error("Failed to export audit logs to JSON: %s", e)
            return False

    def archive_old_logs(self, days_old: int = 90) -> int:
        """
        归档旧日志

        Args:
            days_old: 天数阈值

        Returns:
            int: 归档的日志数量
        """
        try:
            cutoff_time = time.time() - (days_old * 24 * 60 * 60)

            conn = self._get_conn()
            cursor = conn.cursor()

            # 先统计数量
            cursor.execute("SELECT COUNT(*) as count FROM audit_logs WHERE timestamp < ?", (cutoff_time,))
            count = cursor.fetchone()["count"]

            # 删除旧日志
            cursor.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff_time,))

            conn.commit()
            conn.close()

            logger.info("Archived %s audit logs older than %s days", count, days_old)
            return count

        except Exception as e:
            logger.error("Failed to archive old audit logs: %s", e)
            return 0

    def cleanup(self) -> bool:
        """
        清理数据库（压缩和优化）

        Returns:
            bool: 是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 压缩数据库
            cursor.execute("VACUUM")

            # 重新索引
            cursor.execute("REINDEX")

            conn.close()

            logger.info("Audit database cleaned up")
            return True

        except Exception as e:
            logger.error("Failed to cleanup audit database: %s", e)
            return False


# 全局实例
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(db_path: Optional[str] = None) -> AuditLogger:
    """
    获取审计日志管理器单例

    Args:
        db_path: 数据库路径

    Returns:
        AuditLogger: 审计日志管理器实例
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(db_path)
    return _audit_logger


def log_audit(
    event_type: AuditEventType, severity: AuditSeverity, user_id: str = "", action: str = "", **kwargs
) -> bool:
    """
    便捷函数：记录审计日志

    Args:
        event_type: 事件类型
        severity: 严重级别
        user_id: 用户ID
        action: 操作描述
        **kwargs: 其他参数

    Returns:
        bool: 是否成功
    """
    logger_instance = get_audit_logger()
    entry = AuditLogEntry(event_type=event_type, severity=severity, user_id=user_id, action=action, **kwargs)
    return logger_instance.log(entry)
