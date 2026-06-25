"""
附件存储管理器 - 管理记忆系统的文件附件

功能:
- 文件存储与检索
- 附件与记忆的关联管理
- 文件类型验证
- 数据库持久化
"""

import datetime
import hashlib
import json
from neurova.core.logger import get_logger
import os
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class AttachmentManager:
    """
    附件管理器

    管理记忆系统的文件附件，支持：
    1. 文件存储与检索
    2. 附件与记忆的关联管理
    3. 文件类型验证
    4. 数据库持久化
    """

    def __init__(
        self,
        db_path: str = None,
        storage_dir: str = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化附件管理器

        Args:
            db_path: 数据库路径
            storage_dir: 文件存储目录
            config: 配置字典
        """
        self._db_path = db_path
        self._storage_dir = storage_dir
        self._config = config or {}
        self._lock = threading.RLock()

        # 数据库连接
        self._conn = None

        # 配置参数
        self._max_file_size = self._config.get("max_file_size", 50 * 1024 * 1024)  # 50MB
        self._allowed_extensions = set(
            self._config.get(
                "allowed_extensions",
                [
                    ".txt",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".xls",
                    ".xlsx",
                    ".ppt",
                    ".pptx",
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".bmp",
                    ".svg",
                    ".mp3",
                    ".wav",
                    ".mp4",
                    ".avi",
                    ".mov",
                    ".zip",
                    ".rar",
                    ".7z",
                    ".tar",
                    ".gz",
                    ".json",
                    ".xml",
                    ".csv",
                    ".md",
                    ".html",
                ],
            )
        )

        # 初始化数据库
        if self._db_path:
            self._init_db()

        # 确保存储目录存在
        if self._storage_dir:
            os.makedirs(self._storage_dir, exist_ok=True)

        logger.info("AttachmentManager initialized: db=%s, storage=%s", db_path, storage_dir)

    @classmethod
    def from_agent_config(
        cls,
        agent_id: str = None,
        agent_workspace_path: str = None,
        db_path: str = None,
        **kwargs,
    ) -> "AttachmentManager":
        """
        从 Agent 配置创建 AttachmentManager

        Args:
            agent_id: Agent ID
            agent_workspace_path: Agent 工作区路径
            db_path: 数据库路径
            **kwargs: 其他参数

        Returns:
            AttachmentManager实例
        """
        if db_path is None and agent_workspace_path:
            db_path = os.path.join(agent_workspace_path, "attachments.db")

        storage_dir = None
        if agent_workspace_path:
            storage_dir = os.path.join(agent_workspace_path, "attachments")

        return cls(db_path=db_path, storage_dir=storage_dir, **kwargs)

    def _init_db(self) -> None:
        """初始化数据库"""
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

            # 初始化附件表
            self._init_attachment_table()

            logger.info("Database initialized: %s", self._db_path)
        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def _init_attachment_table(self) -> None:
        """初始化附件表"""
        if not self._conn:
            return

        try:
            cursor = self._conn.cursor()

            # 创建附件表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_type TEXT,
                    mime_type TEXT,
                    file_category TEXT,
                    file_hash TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    agent_id TEXT,
                    user_id TEXT
                )
            """)

            # 创建记忆-附件关联表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_attachments (
                    memory_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (memory_id, attachment_id),
                    FOREIGN KEY (attachment_id) REFERENCES attachments (id)
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_attachments_agent_id ON attachments (agent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_attachments_user_id ON attachments (user_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_attachments_memory_id ON memory_attachments (memory_id)"
            )

            self._conn.commit()

        except Exception as e:
            logger.error("Failed to initialize attachment table: %s", e)
            raise

    def save_attachment(
        self,
        file_data: bytes,
        filename: str,
        memory_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        保存附件

        Args:
            file_data: 文件数据
            filename: 原始文件名
            memory_id: 关联的记忆ID
            agent_id: Agent ID
            user_id: 用户ID
            metadata: 元数据

        Returns:
            附件信息字典
        """
        with self._lock:
            # 验证文件名
            if not self._validate_filename(filename):
                raise ValueError(f"Invalid filename: {filename}")

            # 验证文件类型
            if not self._validate_file_type(filename):
                raise ValueError(f"File type not allowed: {filename}")

            # 验证文件大小
            if len(file_data) > self._max_file_size:
                raise ValueError(f"File too large: {len(file_data)} > {self._max_file_size}")

            # 生成存储文件名
            stored_name = self._generate_stored_name(filename)

            # 计算文件哈希
            file_hash = hashlib.md5(file_data).hexdigest()

            # 确定文件类别和MIME类型
            file_category = self._get_file_category(filename)
            mime_type = self._get_mime_type(filename)

            # 保存文件到存储目录
            file_path = None
            if self._storage_dir:
                file_path = os.path.join(self._storage_dir, stored_name)
                with open(file_path, "wb") as f:
                    f.write(file_data)

            # 生成附件ID
            attachment_id = str(uuid.uuid4())

            # 保存到数据库
            if self._conn:
                try:
                    cursor = self._conn.cursor()
                    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

                    cursor.execute(
                        """
                        INSERT INTO attachments 
                        (id, filename, stored_name, file_path, file_size, file_type, 
                         mime_type, file_category, file_hash, metadata, created_at, 
                         agent_id, user_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            attachment_id,
                            filename,
                            stored_name,
                            file_path,
                            len(file_data),
                            os.path.splitext(filename)[1],
                            mime_type,
                            file_category,
                            file_hash,
                            json.dumps(metadata or {}),
                            now,
                            agent_id,
                            user_id,
                        ),
                    )

                    # 如果有关联的记忆，建立关联
                    if memory_id:
                        cursor.execute(
                            """
                            INSERT INTO memory_attachments (memory_id, attachment_id, created_at)
                            VALUES (?, ?, ?)
                        """,
                            (memory_id, attachment_id, now),
                        )

                    self._conn.commit()

                except Exception as e:
                    logger.error("Failed to save attachment to database: %s", e)
                    # 清理已保存的文件
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                    raise

            # 返回附件信息
            attachment_info = {
                "id": attachment_id,
                "filename": filename,
                "stored_name": stored_name,
                "file_path": file_path,
                "file_size": len(file_data),
                "file_type": os.path.splitext(filename)[1],
                "mime_type": mime_type,
                "file_category": file_category,
                "file_hash": file_hash,
                "metadata": metadata or {},
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "agent_id": agent_id,
                "user_id": user_id,
            }

            logger.info("Attachment saved: %s (%s)", attachment_id, filename)
            return attachment_info

    def get_attachment(self, attachment_id: str) -> Optional[Dict[str, Any]]:
        """
        获取附件信息

        Args:
            attachment_id: 附件ID

        Returns:
            附件信息字典，如果不存在返回None
        """
        with self._lock:
            if not self._conn:
                return None

            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
                row = cursor.fetchone()

                if row:
                    return self._row_to_dict(row)
                return None

            except Exception as e:
                logger.error("Failed to get attachment: %s", e)
                return None

    def get_attachment_data(self, attachment_id: str) -> Optional[bytes]:
        """
        获取附件数据

        Args:
            attachment_id: 附件ID

        Returns:
            附件数据，如果不存在返回None
        """
        attachment = self.get_attachment(attachment_id)
        if not attachment:
            return None

        file_path = attachment.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return None

        try:
            with open(file_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.error("Failed to read attachment data: %s", e)
            return None

    def get_memory_attachments(self, memory_id: str) -> List[Dict[str, Any]]:
        """
        获取记忆的所有附件

        Args:
            memory_id: 记忆ID

        Returns:
            附件信息列表
        """
        with self._lock:
            if not self._conn:
                return []

            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    SELECT a.* FROM attachments a
                    JOIN memory_attachments ma ON a.id = ma.attachment_id
                    WHERE ma.memory_id = ?
                    ORDER BY a.created_at DESC
                """,
                    (memory_id,),
                )

                rows = cursor.fetchall()
                return [self._row_to_dict(row) for row in rows]

            except Exception as e:
                logger.error("Failed to get memory attachments: %s", e)
                return []

    def delete_attachment(self, attachment_id: str) -> bool:
        """
        删除附件

        Args:
            attachment_id: 附件ID

        Returns:
            是否删除成功
        """
        with self._lock:
            if not self._conn:
                return False

            try:
                # 获取附件信息
                attachment = self.get_attachment(attachment_id)
                if not attachment:
                    return False

                # 删除文件
                file_path = attachment.get("file_path")
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)

                # 删除数据库记录
                cursor = self._conn.cursor()

                # 先删除关联记录
                cursor.execute("DELETE FROM memory_attachments WHERE attachment_id = ?", (attachment_id,))

                # 删除附件记录
                cursor.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

                self._conn.commit()

                logger.info("Attachment deleted: %s", attachment_id)
                return True

            except Exception as e:
                logger.error("Failed to delete attachment: %s", e)
                return False

    def link_to_memory(self, attachment_id: str, memory_id: str) -> bool:
        """
        将附件关联到记忆

        Args:
            attachment_id: 附件ID
            memory_id: 记忆ID

        Returns:
            是否关联成功
        """
        with self._lock:
            if not self._conn:
                return False

            try:
                cursor = self._conn.cursor()
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # 检查是否已存在关联
                cursor.execute(
                    """
                    SELECT 1 FROM memory_attachments 
                    WHERE memory_id = ? AND attachment_id = ?
                """,
                    (memory_id, attachment_id),
                )

                if cursor.fetchone():
                    return True  # 已存在关联

                # 创建关联
                cursor.execute(
                    """
                    INSERT INTO memory_attachments (memory_id, attachment_id, created_at)
                    VALUES (?, ?, ?)
                """,
                    (memory_id, attachment_id, now),
                )

                self._conn.commit()

                logger.debug("Attachment %s linked to memory %s", attachment_id, memory_id)
                return True

            except Exception as e:
                logger.error("Failed to link attachment to memory: %s", e)
                return False

    def unlink_from_memory(self, attachment_id: str, memory_id: str) -> bool:
        """
        取消附件与记忆的关联

        Args:
            attachment_id: 附件ID
            memory_id: 记忆ID

        Returns:
            是否取消关联成功
        """
        with self._lock:
            if not self._conn:
                return False

            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM memory_attachments 
                    WHERE memory_id = ? AND attachment_id = ?
                """,
                    (memory_id, attachment_id),
                )

                self._conn.commit()

                logger.debug("Attachment %s unlinked from memory %s", attachment_id, memory_id)
                return True

            except Exception as e:
                logger.error("Failed to unlink attachment from memory: %s", e)
                return False

    def list_attachments(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        file_category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        列出附件

        Args:
            agent_id: Agent ID过滤
            user_id: 用户ID过滤
            file_category: 文件类别过滤
            limit: 数量限制
            offset: 偏移量

        Returns:
            附件信息列表
        """
        with self._lock:
            if not self._conn:
                return []

            try:
                cursor = self._conn.cursor()

                # 构建查询
                query = "SELECT * FROM attachments WHERE 1=1"
                params = []

                if agent_id:
                    query += " AND agent_id = ?"
                    params.append(agent_id)

                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)

                if file_category:
                    query += " AND file_category = ?"
                    params.append(file_category)

                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [self._row_to_dict(row) for row in rows]

            except Exception as e:
                logger.error("Failed to list attachments: %s", e)
                return []

    def update_metadata(self, attachment_id: str, metadata: Dict[str, Any]) -> bool:
        """
        更新附件元数据

        Args:
            attachment_id: 附件ID
            metadata: 新元数据

        Returns:
            是否更新成功
        """
        with self._lock:
            if not self._conn:
                return False

            try:
                cursor = self._conn.cursor()
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()

                cursor.execute(
                    """
                    UPDATE attachments 
                    SET metadata = ?, updated_at = ?
                    WHERE id = ?
                """,
                    (json.dumps(metadata), now, attachment_id),
                )

                self._conn.commit()

                logger.debug("Attachment metadata updated: %s", attachment_id)
                return True

            except Exception as e:
                logger.error("Failed to update attachment metadata: %s", e)
                return False

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取存储统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            stats = {
                "total_attachments": 0,
                "total_size": 0,
                "by_category": {},
                "by_agent": {},
                "by_user": {},
            }

            if not self._conn:
                return stats

            try:
                cursor = self._conn.cursor()

                # 总数和总大小
                cursor.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM attachments")
                row = cursor.fetchone()
                stats["total_attachments"] = row[0]
                stats["total_size"] = row[1]

                # 按类别统计
                cursor.execute("""
                    SELECT file_category, COUNT(*), COALESCE(SUM(file_size), 0)
                    FROM attachments
                    GROUP BY file_category
                """)
                for row in cursor.fetchall():
                    category = row[0] or "unknown"
                    stats["by_category"][category] = {
                        "count": row[1],
                        "size": row[2],
                    }

                # 按Agent统计
                cursor.execute("""
                    SELECT agent_id, COUNT(*), COALESCE(SUM(file_size), 0)
                    FROM attachments
                    WHERE agent_id IS NOT NULL
                    GROUP BY agent_id
                """)
                for row in cursor.fetchall():
                    stats["by_agent"][row[0]] = {
                        "count": row[1],
                        "size": row[2],
                    }

                # 按用户统计
                cursor.execute("""
                    SELECT user_id, COUNT(*), COALESCE(SUM(file_size), 0)
                    FROM attachments
                    WHERE user_id IS NOT NULL
                    GROUP BY user_id
                """)
                for row in cursor.fetchall():
                    stats["by_user"][row[0]] = {
                        "count": row[1],
                        "size": row[2],
                    }

                return stats

            except Exception as e:
                logger.error("Failed to get storage stats: %s", e)
                return stats

    def cleanup_orphaned_files(self) -> Dict[str, Any]:
        """
        清理孤立文件

        Returns:
            清理结果统计
        """
        with self._lock:
            result = {
                "cleaned": 0,
                "errors": 0,
                "freed_space": 0,
            }

            if not self._storage_dir or not os.path.exists(self._storage_dir):
                return result

            # 获取数据库中所有文件路径
            db_files = set()
            if self._conn:
                try:
                    cursor = self._conn.cursor()
                    cursor.execute("SELECT file_path FROM attachments")
                    for row in cursor.fetchall():
                        if row[0]:
                            db_files.add(row[0])
                except Exception as e:
                    logger.error("Failed to get file paths from database: %s", e)

            # 扫描存储目录
            for root, dirs, files in os.walk(self._storage_dir):
                for file in files:
                    file_path = os.path.join(root, file)

                    # 检查是否在数据库中
                    if file_path not in db_files:
                        try:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            result["cleaned"] += 1
                            result["freed_space"] += file_size
                            logger.debug("Cleaned orphaned file: %s", file_path)
                        except Exception as e:
                            result["errors"] += 1
                            logger.warning("Failed to clean orphaned file %s: %s", file_path, e)

            logger.info("Cleanup completed: %s files cleaned, %s bytes freed", result['cleaned'], result['freed_space'])
            return result

    def _validate_filename(self, filename: str) -> bool:
        """
        验证文件名

        Args:
            filename: 文件名

        Returns:
            是否有效
        """
        if not filename:
            return False

        # 检查文件名长度
        if len(filename) > 255:
            return False

        # 检查非法字符
        illegal_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        for char in illegal_chars:
            if char in filename:
                return False

        return True

    def _validate_file_type(self, filename: str) -> bool:
        """
        验证文件类型

        Args:
            filename: 文件名

        Returns:
            是否允许
        """
        if not self._allowed_extensions:
            return True

        ext = os.path.splitext(filename)[1].lower()
        return ext in self._allowed_extensions

    def _generate_stored_name(self, filename: str) -> str:
        """
        生成存储文件名

        Args:
            filename: 原始文件名

        Returns:
            存储文件名
        """
        ext = os.path.splitext(filename)[1]
        unique_id = str(uuid.uuid4())
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}_{unique_id}{ext}"

    def _get_file_category(self, filename: str) -> str:
        """
        获取文件类别

        Args:
            filename: 文件名

        Returns:
            文件类别
        """
        ext = os.path.splitext(filename)[1].lower()

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp"}
        audio_exts = {".mp3", ".wav", ".ogg", ".flac", ".aac"}
        video_exts = {".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}
        document_exts = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"}
        archive_exts = {".zip", ".rar", ".7z", ".tar", ".gz"}

        if ext in image_exts:
            return "image"
        elif ext in audio_exts:
            return "audio"
        elif ext in video_exts:
            return "video"
        elif ext in document_exts:
            return "document"
        elif ext in archive_exts:
            return "archive"
        else:
            return "other"

    def _get_mime_type(self, filename: str) -> str:
        """
        获取MIME类型

        Args:
            filename: 文件名

        Returns:
            MIME类型
        """
        ext = os.path.splitext(filename)[1].lower()

        mime_types = {
            ".txt": "text/plain",
            ".html": "text/html",
            ".htm": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".xml": "application/xml",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".zip": "application/zip",
            ".rar": "application/x-rar-compressed",
            ".7z": "application/x-7z-compressed",
            ".tar": "application/x-tar",
            ".gz": "application/gzip",
            ".csv": "text/csv",
            ".md": "text/markdown",
        }

        return mime_types.get(ext, "application/octet-stream")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """
        将数据库行转换为字典

        Args:
            row: 数据库行

        Returns:
            字典
        """
        result = dict(row)

        # 解析JSON字段
        if result.get("metadata"):
            try:
                result["metadata"] = json.loads(result["metadata"])
            except Exception:
                result["metadata"] = {}

        return result

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                logger.info("AttachmentManager closed")

    def __del__(self):
        """析构函数"""
        self.close()


# 全局单例
_attachment_manager: Optional[AttachmentManager] = None
_manager_lock = threading.Lock()


def get_attachment_manager(
    db_path: str = None,
    storage_dir: str = None,
    config: Optional[Dict[str, Any]] = None,
) -> AttachmentManager:
    """
    获取全局附件管理器单例

    Args:
        db_path: 数据库路径
        storage_dir: 文件存储目录
        config: 配置字典

    Returns:
        AttachmentManager实例
    """
    global _attachment_manager
    if _attachment_manager is None:
        with _manager_lock:
            if _attachment_manager is None:
                _attachment_manager = AttachmentManager(
                    db_path=db_path,
                    storage_dir=storage_dir,
                    config=config,
                )
    return _attachment_manager


def reset_attachment_manager() -> None:
    """重置全局附件管理器（用于测试）"""
    global _attachment_manager
    with _manager_lock:
        if _attachment_manager:
            _attachment_manager.close()
        _attachment_manager = None
