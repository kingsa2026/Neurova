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
import hashlib
import json
from neurova.core.logger import get_logger
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.lazy_singleton import lazySingleton

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
    APPROVAL = "approval"


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


#: 审计库文件名（落点推导见 `auditDbPath()`，别处不要手拼）。
AUDIT_DB_NAME = "audit.db"


def auditDbPath() -> str:
    """审计库落点：数据根下唯一一处；旧 `~/.neurova/audit.db` 在空缺时收养。

    为什么连 `-wal`/`-shm` 一起收：WAL 模式下未 checkpoint 的帧只存在于 `-wal`，
    只搬主库等于把最近的审计记录留在原地——"看着搬完了、实则丢数据"就是这一形。
    """
    from neurova.core.data_root import adoptHomeLanding, dataLanding

    target = dataLanding(AUDIT_DB_NAME, legacy=())
    for suffix in ("", "-wal", "-shm"):
        adoptHomeLanding(target.parent / (target.name + suffix), AUDIT_DB_NAME + suffix)
    return str(target)


# ---------------------------------------------------------------------------
# S4 审计防篡改哈希链（拍板 D-S2 = 全量事件入链）
#
# 每行落两列：prev_hash（前一条 entry_hash；首条为全零创世串）与
# entry_hash = sha256(prev_hash ‖ canonical_json(本条去哈希字段))。
# 哈希覆盖 AuditLogEntry 全部业务字段（不含两列哈希本身与库端 created_at），
# 任何字段被静默改写都会使该行 entry_hash 复算不符，校验按 id 序定位断点。
# ---------------------------------------------------------------------------

#: 哈希链版本域：audit.db 独立成库，schema 演进按域登记（core/db_migration.py）。
AUDIT_DB_DOMAIN = "audit_log"

#: 创世 prev_hash：全零 64 位（sha256 hex 长度），首条审计事件的链头。
GENESIS_PREV_HASH = "0" * 64

# v1 基线：audit_logs 原始表结构（与历史 _init_db 逐字一致）+ 索引。
_AUDIT_SCHEMA_V1 = """
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
);
CREATE INDEX IF NOT EXISTS idx_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_severity ON audit_logs(severity);
"""


def _migrateAuditLogHashColumns(conn: sqlite3.Connection) -> None:
    """v2（S4）：给 audit_logs 补 prev_hash / entry_hash 两列。

    旧库 ALTER TABLE 幂等补齐；迁移前既有行两列保持 NULL（legacy 形态），
    链校验按 legacy 跳过——不回填、不臆造历史哈希。
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(audit_logs)").fetchall()
    }
    if "prev_hash" not in columns:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN prev_hash TEXT")
    if "entry_hash" not in columns:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN entry_hash TEXT")


# 模块级登记（与 api/auth.py、agent/swarm_event_store.py 同范式）：import 即入
# 登记表可审计；register_migration 对同版本重复注册幂等忽略。
register_migration(1, _AUDIT_SCHEMA_V1, domain=AUDIT_DB_DOMAIN)
register_migration(2, _migrateAuditLogHashColumns, domain=AUDIT_DB_DOMAIN)


def canonicalJson(obj: Any) -> str:
    """规范化 JSON：键排序、紧凑分隔符、保留非 ASCII 原文——同内容必同串。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def computeEntryHash(prev_hash: str, payload: Dict[str, Any]) -> str:
    """entry_hash = sha256(prev_hash ‖ canonical_json(payload))。"""
    return hashlib.sha256(
        (prev_hash + canonicalJson(payload)).encode("utf-8")
    ).hexdigest()


def _chainPayload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """抽取并归一化参与哈希链的字段（去哈希两列；写路与校验路共用同一份清单）。

    None 归空串/空表，与落库形态（`or ""` / `{}`）一致，保证写读往返可复算。
    """
    return {
        "event_type": fields.get("event_type") or "",
        "severity": fields.get("severity") or "",
        "user_id": fields.get("user_id") or "",
        "action": fields.get("action") or "",
        "details": fields.get("details") or {},
        "timestamp": fields.get("timestamp") if fields.get("timestamp") is not None else 0.0,
        "ip_address": fields.get("ip_address") or "",
        "user_agent": fields.get("user_agent") or "",
        "resource_type": fields.get("resource_type") or "",
        "resource_id": fields.get("resource_id") or "",
        "metadata": fields.get("metadata") or {},
    }


def _entryChainFields(entry: AuditLogEntry) -> Dict[str, Any]:
    """写路径：由 AuditLogEntry 构建链哈希载荷。"""
    return _chainPayload(
        {
            "event_type": entry.event_type.value,
            "severity": entry.severity.value,
            "user_id": entry.user_id,
            "action": entry.action,
            "details": entry.details,
            "timestamp": entry.timestamp,
            "ip_address": entry.ip_address,
            "user_agent": entry.user_agent,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "metadata": entry.metadata,
        }
    )


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

        self._db_path = db_path or auditDbPath()
        self._ensure_db_dir()
        self._init_db()
        self._initialized = True

        logger.info("AuditLogger initialized with db: %s", self._db_path)

    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """借出一条池化短连接（P1-4 / ADR 0014）。

        审计写是"每事件一次"的高频短连接（实测裸连接 5.22ms → 池 2.06ms），
        是本轮收益最大的迁移点。

        **优先用 `_connection()` 上下文**：裸连接时代，异常路径漏 close 只是
        "迟早被 GC 回收"；池化后漏归还 = `_created_count` 只增不减，漏满
        max_connections 后取连接会阻塞到 timeout（P0-2 里"健康检查卡 30s"
        就是同一形状）。故保留成对的 get/close 入口以兼容旧调用，但新增与
        修改的调用点一律走上下文。

        非默认路径（测试注入 tmp_path）同样进池：池按 db_path 注册，路径隔离
        即池隔离，不会串库。
        """
        from neurova.core.database import get_short_connection

        return get_short_connection(self._db_path)

    def _close_conn(self, conn: sqlite3.Connection) -> None:
        """归还短连接到池（幂等；失败降级为关闭，不抛给调用方）。"""
        from neurova.core.database import release_short_connection

        try:
            release_short_connection(conn)
        except Exception:  # noqa: BLE001 - 归还失败不改变调用方语义
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    @contextmanager
    def _connection(self):
        """借出/归还池化短连接（异常路径也归还）。"""
        conn = self._get_conn()
        try:
            yield conn
        finally:
            self._close_conn(conn)

    def _init_db(self):
        """初始化数据库表（schema 唯一事实源：db_migration 注册表 domain=audit_log）。"""
        conn = None
        try:
            conn = self._get_conn()
            apply_migrations(conn, domain=AUDIT_DB_DOMAIN)
            logger.info("Audit database initialized")
        except Exception as e:
            logger.error("Failed to initialize audit database: %s", e)
            raise
        finally:
            if conn is not None:
                self._close_conn(conn)

    def log(self, entry: AuditLogEntry) -> bool:
        """
        记录审计日志（S4：同一 BEGIN IMMEDIATE 事务内取链尾 prev_hash 并落
        entry_hash，写锁自事务开始即持有，并发写入不会各自链到同一尾节点）

        Args:
            entry: 审计日志条目

        Returns:
            bool: 是否成功
        """
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            conn.execute("BEGIN IMMEDIATE")
            try:
                tail = cursor.execute(
                    "SELECT entry_hash FROM audit_logs ORDER BY id DESC LIMIT 1"
                ).fetchone()
                prev_hash = GENESIS_PREV_HASH
                if tail is not None and tail["entry_hash"]:
                    prev_hash = tail["entry_hash"]
                entry_hash = computeEntryHash(prev_hash, _entryChainFields(entry))

                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        event_type, severity, user_id, action, details,
                        timestamp, ip_address, user_agent, resource_type,
                        resource_id, metadata, prev_hash, entry_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        prev_hash,
                        entry_hash,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            logger.debug("Audit log recorded: %s - %s", entry.event_type.value, entry.action)
            return True

        except Exception as e:
            logger.error("Failed to record audit log: %s", e)
            return False
        finally:
            if conn is not None:
                self._close_conn(conn)

    def verifyChain(self) -> Tuple[bool, Optional[int]]:
        """全表按 id 序校验哈希链，返回 (ok, first_broken_id)。

        - 每行复算 entry_hash，并与 prev_hash 链接比对；
        - entry_hash 为空的行按 legacy（迁移前旧行）跳过，不误报；
        - 首个有哈希行只验自身哈希（其 prev_hash 指向的行可能已归档删除，
          无外部锚点时链头截断本不可检，如实不误报）。
        """
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, prev_hash, entry_hash, event_type, severity, user_id,
                       action, details, timestamp, ip_address, user_agent,
                       resource_type, resource_id, metadata
                FROM audit_logs ORDER BY id ASC
                """
            )
            prev_expected: Optional[str] = None
            for row in cursor.fetchall():
                entry_hash = row["entry_hash"]
                if not entry_hash:
                    continue  # legacy 行：迁移前写入，无哈希可验
                fields = _chainPayload(
                    {
                        "event_type": row["event_type"],
                        "severity": row["severity"],
                        "user_id": row["user_id"],
                        "action": row["action"],
                        "details": json.loads(row["details"]) if row["details"] else {},
                        "timestamp": row["timestamp"],
                        "ip_address": row["ip_address"],
                        "user_agent": row["user_agent"],
                        "resource_type": row["resource_type"],
                        "resource_id": row["resource_id"],
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    }
                )
                row_prev = row["prev_hash"] or GENESIS_PREV_HASH
                if computeEntryHash(row_prev, fields) != entry_hash:
                    return False, row["id"]
                if prev_expected is not None and row_prev != prev_expected:
                    return False, row["id"]
                prev_expected = entry_hash
            return True, None
        except Exception as e:
            logger.error("Failed to verify audit chain: %s", e)
            return False, None
        finally:
            if conn is not None:
                self._close_conn(conn)

    def log_auth_login(
        self,
        user_id: Optional[str],
        ip_address: str = "",
        user_agent: str = "",
        success: bool = True,
        attempted_username: str = "",
    ) -> bool:
        """记录登录事件（登录与刷新令牌成败共用同一语义）。

        user_id 允许 None——用户不存在、令牌不可解等未解析形态落库为空串，
        不臆造身份；attempted_username 把尝试的用户名带进 details 供事后追溯。
        """
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGIN if success else AuditEventType.AUTH_FAILED,
            severity=AuditSeverity.MEDIUM if success else AuditSeverity.HIGH,
            user_id=user_id or "",
            action="Login successful" if success else "Login failed",
            details=({"attempted_username": attempted_username} if attempted_username else {}),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self.log(entry)

    def log_auth_logout(self, user_id: Optional[str], ip_address: str = "") -> bool:
        """记录登出事件（user_id 允许 None——令牌不可解时落库为空串）。"""
        entry = AuditLogEntry(
            event_type=AuditEventType.AUTH_LOGOUT,
            severity=AuditSeverity.LOW,
            user_id=user_id or "",
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
        resource_id: Optional[str] = None,
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
            resource_id: 资源ID精确过滤（如蜂群审批轨迹按 run 标识拉取）
            limit: 限制数量
            offset: 偏移量

        Returns:
            List[AuditLogEntry]: 审计日志列表
        """
        conn = None
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

            if resource_id:
                query += " AND resource_id = ?"
                params.append(resource_id)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            results = cursor.fetchall()

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
        finally:
            if conn is not None:
                self._close_conn(conn)

    def get_by_id(self, log_id: int) -> Optional[AuditLogEntry]:
        """根据ID获取审计日志"""
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM audit_logs WHERE id = ?", (log_id,))
            row = cursor.fetchone()

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
        finally:
            if conn is not None:
                self._close_conn(conn)

    def get_statistics(self, start_time: Optional[float] = None, end_time: Optional[float] = None) -> Dict[str, Any]:
        """
        获取审计统计信息

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            Dict: 统计信息
        """
        conn = None
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
            # BUG AUDIT S-09: 此前三查询复用同一个 params 列表，start/end_time
            # 被重复 append，第 2/3 条 SQL 绑定数不匹配 → ProgrammingError 被吞 →
            # 传时间范围时审计统计恒为空。每条查询使用独立 params。
            query = "SELECT event_type, COUNT(*) as count FROM audit_logs WHERE 1=1"
            params2 = []
            if start_time:
                query += " AND timestamp >= ?"
                params2.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params2.append(end_time)
            query += " GROUP BY event_type"

            cursor.execute(query, params2)
            by_event_type = {row["event_type"]: row["count"] for row in cursor.fetchall()}

            # 按严重级别统计
            query = "SELECT severity, COUNT(*) as count FROM audit_logs WHERE 1=1"
            params3 = []
            if start_time:
                query += " AND timestamp >= ?"
                params3.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params3.append(end_time)
            query += " GROUP BY severity"

            cursor.execute(query, params3)
            by_severity = {row["severity"]: row["count"] for row in cursor.fetchall()}

            return {
                "total": total,
                "by_event_type": by_event_type,
                "by_severity": by_severity,
                "time_range": {"start": start_time, "end": end_time},
            }

        except Exception as e:
            logger.error("Failed to get audit statistics: %s", e)
            return {}
        finally:
            if conn is not None:
                self._close_conn(conn)

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
        conn = None
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

            logger.info("Archived %s audit logs older than %s days", count, days_old)
            return count

        except Exception as e:
            logger.error("Failed to archive old audit logs: %s", e)
            return 0
        finally:
            if conn is not None:
                self._close_conn(conn)

    def cleanup(self) -> bool:
        """
        清理数据库（压缩和优化）

        Returns:
            bool: 是否成功
        """
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 压缩数据库
            cursor.execute("VACUUM")

            # 重新索引
            cursor.execute("REINDEX")

            logger.info("Audit database cleaned up")
            return True

        except Exception as e:
            logger.error("Failed to cleanup audit database: %s", e)
            return False
        finally:
            if conn is not None:
                self._close_conn(conn)


# 全局实例
_audit_logger: Optional[AuditLogger] = None


@lazySingleton("_audit_logger")
def get_audit_logger(db_path: Optional[str] = None) -> AuditLogger:
    """
    获取审计日志管理器单例

    Args:
        db_path: 数据库路径

    Returns:
        AuditLogger: 审计日志管理器实例
    """
    return AuditLogger(db_path)


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


def verify_audit_chain() -> Tuple[bool, Optional[int]]:
    """便捷函数：全表按 id 序校验当前审计库哈希链，返回 (ok, first_broken_id)。

    S4 防篡改判据入口：ok=False 时 first_broken_id 为首条被改写/断链的行 id。
    """
    return get_audit_logger().verifyChain()
