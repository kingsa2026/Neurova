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

"""
UserBackup
"""
def UserBackup(*args, **kwargs):
    """TODO: Auto-restored from .pyc, needs implementation"""
    pass

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
