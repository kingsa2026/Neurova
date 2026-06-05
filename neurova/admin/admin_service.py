from __future__ import annotations

"""
admin_service - Auto-restored from .pyc
"""

from dataclasses import dataclass
import datetime
import io
import json
import logging
from pathlib import Path
import shutil
import typing

import secrets
import tarfile
from typing import Any, Dict, List, Optional

try:
    import bcrypt
except ImportError:
    bcrypt = None

from neurova.auth.user_model import User
from neurova.core.module_system import Module

# auth imports
import neurova.auth.user_group_model

# core imports
import neurova.core.module_system
import neurova.core.startup_manager

@dataclass
class UserBackup:
    """用户备份数据"""
    backup_id: str
    user_id: str
    created_at: datetime.datetime
    backup_path: str
    size_bytes: int
    description: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "backup_path": self.backup_path,
            "size_bytes": self.size_bytes,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserBackup":
        return cls(
            backup_id=data["backup_id"],
            user_id=data["user_id"],
            created_at=datetime.datetime.fromisoformat(data["created_at"]),
            backup_path=data["backup_path"],
            size_bytes=data["size_bytes"],
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
        )

class AdminService:
    """
    AdminService
    """
    def __annotate__(self, *args, **kwargs):
        pass
    def __init__(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _on_init(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _on_start(self, *args, **kwargs):
        pass
    def _init_dirs(self, *args, **kwargs):
        pass
    def _load_backups(self, *args, **kwargs):
        pass
    def _save_backups(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def create_user(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _init_user_workspace(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def update_user(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def delete_user(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def _cleanup_user_data(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def backup_user(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def list_backups(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def restore_user(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def delete_backup(self, *args, **kwargs):
        pass
    def __annotate__(self, *args, **kwargs):
        pass
    def get_system_stats(self, *args, **kwargs):
        pass
