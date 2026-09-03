
"""端到端测试配置

提供E2E测试所需的fixtures和基础设施
"""

import pytest
import tempfile
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neurova.core.event_bus import EventBus
from neurova.core.config import ConfigManager
from neurova.core.state_manager import StateManager
from neurova.core.module_system import ModuleRegistry
from neurova.core.logger import LogManager
from neurova.security.rbac import RBACManager
from neurova.auth.password_hasher import PasswordHasher


@pytest.fixture
def e2e_temp_storage():
    """提供临时存储目录"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def e2e_core_services(e2e_temp_storage):
    """提供完整的核心服务实例"""
    event_bus = EventBus()
    config_manager = ConfigManager(str(e2e_temp_storage / "config.json"))
    state_manager = StateManager()
    log_manager = LogManager(str(e2e_temp_storage / "logs"))
    
    return {
        "event_bus": event_bus,
        "config_manager": config_manager,
        "state_manager": state_manager,
        "log_manager": log_manager
    }


@pytest.fixture
def e2e_module_system(e2e_core_services):
    """提供模块系统实例"""
    services = e2e_core_services
    module_registry = ModuleRegistry(
        event_bus=services["event_bus"],
        config_manager=services["config_manager"],
        state_manager=services["state_manager"],
        log_manager=services["log_manager"]
    )
    return module_registry


@pytest.fixture
def e2e_security_services():
    """提供安全相关服务"""
    rbac_manager = RBACManager()
    password_hasher = PasswordHasher()
    
    return {
        "rbac_manager": rbac_manager,
        "password_hasher": password_hasher
    }

