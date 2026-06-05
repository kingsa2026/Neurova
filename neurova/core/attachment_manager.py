from __future__ import annotations

"""
统一附件管理模块 - Attachment Manager

功能:
- 附件元数据存储
- 附件 ID 管理
- 附件信息查询

遵循统一模块规范:
- 统一模块接口
- 统一模块事件总线
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
from pathlib import Path
import threading
import typing
import uuid

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AttachmentInfo:
    """附件信息数据类"""
    attachment_id: str
    filename: str
    file_path: str
    file_size: int
    content_type: str
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }


class AttachmentManager:
    """
    附件管理器
    
    管理附件的元数据存储和查询。
    """
    
    def __init__(self, config: typing.Dict[str, typing.Any] = None):
        """
        初始化附件管理器
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 附件存储目录
        self._storage_dir = Path(self._config.get("storage_dir", "data/attachments"))
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 元数据存储
        self._metadata_file = self._storage_dir / "metadata.json"
        self._attachments: typing.Dict[str, AttachmentInfo] = {}
        
        # 加载现有元数据
        self._load_metadata()
        
        logger.info("AttachmentManager 初始化完成")
    
    def _load_metadata(self) -> None:
        """加载元数据"""
        try:
            if self._metadata_file.exists():
                with open(self._metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for attachment_id, info in data.items():
                        # 转换时间字符串
                        if 'created_at' in info:
                            info['created_at'] = datetime.datetime.fromisoformat(info['created_at'])
                        self._attachments[attachment_id] = AttachmentInfo(**info)
                logger.debug(f"加载了 {len(self._attachments)} 个附件元数据")
        except Exception as e:
            logger.error(f"加载附件元数据失败: {e}")
    
    def _save_metadata(self) -> None:
        """保存元数据"""
        try:
            data = {}
            for attachment_id, info in self._attachments.items():
                data[attachment_id] = info.to_dict()
            
            with open(self._metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("附件元数据已保存")
        except Exception as e:
            logger.error(f"保存附件元数据失败: {e}")
    
    def save(self, filename: str, file_content: bytes, content_type: str = "application/octet-stream",
             metadata: typing.Dict[str, typing.Any] = None) -> AttachmentInfo:
        """
        保存附件
        
        Args:
            filename: 文件名
            file_content: 文件内容
            content_type: 内容类型
            metadata: 附加元数据
            
        Returns:
            附件信息
        """
        with self._lock:
            # 生成唯一ID
            attachment_id = str(uuid.uuid4())
            
            # 生成文件路径
            file_ext = Path(filename).suffix if filename else ""
            file_path = self._storage_dir / f"{attachment_id}{file_ext}"
            
            # 保存文件
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            # 创建附件信息
            attachment_info = AttachmentInfo(
                attachment_id=attachment_id,
                filename=filename,
                file_path=str(file_path),
                file_size=len(file_content),
                content_type=content_type,
                metadata=metadata or {}
            )
            
            # 存储元数据
            self._attachments[attachment_id] = attachment_info
            self._save_metadata()
            
            # 发送事件
            self._emit_attachment_event("attachment_created", attachment_info)
            
            logger.info(f"附件已保存: {attachment_id} - {filename}")
            return attachment_info
    
    def get(self, attachment_id: str) -> typing.Optional[AttachmentInfo]:
        """
        获取附件信息
        
        Args:
            attachment_id: 附件ID
            
        Returns:
            附件信息，不存在返回 None
        """
        with self._lock:
            return self._attachments.get(attachment_id)
    
    def list(self, content_type: str = None, limit: int = 100) -> typing.List[AttachmentInfo]:
        """
        列出附件
        
        Args:
            content_type: 内容类型过滤
            limit: 返回数量限制
            
        Returns:
            附件信息列表
        """
        with self._lock:
            attachments = list(self._attachments.values())
            
            # 按内容类型过滤
            if content_type:
                attachments = [a for a in attachments if a.content_type == content_type]
            
            # 按创建时间排序（最新的在前）
            attachments.sort(key=lambda x: x.created_at, reverse=True)
            
            return attachments[:limit]
    
    def delete(self, attachment_id: str) -> bool:
        """
        删除附件
        
        Args:
            attachment_id: 附件ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if attachment_id not in self._attachments:
                logger.warning(f"附件不存在: {attachment_id}")
                return False
            
            attachment_info = self._attachments[attachment_id]
            
            # 删除文件
            file_path = Path(attachment_info.file_path)
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.error(f"删除附件文件失败: {e}")
            
            # 删除元数据
            del self._attachments[attachment_id]
            self._save_metadata()
            
            # 发送事件
            self._emit_attachment_event("attachment_deleted", attachment_info)
            
            logger.info(f"附件已删除: {attachment_id}")
            return True
    
    def _emit_attachment_event(self, event_type: str, attachment_info: AttachmentInfo) -> None:
        """
        发送附件事件
        
        Args:
            event_type: 事件类型
            attachment_info: 附件信息
        """
        try:
            # 这里可以集成事件总线
            logger.debug(f"附件事件: {event_type} - {attachment_info.attachment_id}")
        except Exception as e:
            logger.error(f"发送附件事件失败: {e}")
    
    def get_storage_stats(self) -> typing.Dict[str, typing.Any]:
        """
        获取存储统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            total_size = sum(a.file_size for a in self._attachments.values())
            type_counts = {}
            
            for attachment in self._attachments.values():
                content_type = attachment.content_type
                type_counts[content_type] = type_counts.get(content_type, 0) + 1
            
            return {
                "total_attachments": len(self._attachments),
                "total_size": total_size,
                "type_counts": type_counts,
                "storage_directory": str(self._storage_dir)
            }
    
    def cleanup_orphaned_files(self) -> int:
        """
        清理孤立文件
        
        Returns:
            清理的文件数量
        """
        with self._lock:
            cleaned_count = 0
            
            # 获取所有附件ID
            attachment_ids = set(self._attachments.keys())
            
            # 扫描存储目录
            for file_path in self._storage_dir.iterdir():
                if file_path.is_file() and file_path.name != "metadata.json":
                    # 从文件名提取ID（去除扩展名）
                    file_id = file_path.stem
                    
                    if file_id not in attachment_ids:
                        try:
                            file_path.unlink()
                            cleaned_count += 1
                            logger.debug(f"清理孤立文件: {file_path}")
                        except Exception as e:
                            logger.error(f"清理孤立文件失败: {e}")
            
            logger.info(f"清理了 {cleaned_count} 个孤立文件")
            return cleaned_count


# 全局实例管理
_attachment_manager: typing.Optional[AttachmentManager] = None
_manager_lock = threading.Lock()


def get_attachment_manager(config: typing.Dict[str, typing.Any] = None) -> AttachmentManager:
    """
    获取全局附件管理器
    
    Args:
        config: 配置字典
        
    Returns:
        AttachmentManager 实例
    """
    global _attachment_manager
    if _attachment_manager is None:
        with _manager_lock:
            if _attachment_manager is None:
                _attachment_manager = AttachmentManager(config)
    return _attachment_manager


def reset_attachment_manager() -> None:
    """
    重置全局附件管理器
    """
    global _attachment_manager
    with _manager_lock:
        _attachment_manager = None