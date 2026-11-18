
"""端到端测试配置

提供E2E测试所需的fixtures和基础设施

QwenPaw 对照批 C12：双档 marker——
- `e2e_mock`：in-process mock LLM 档（不依赖真后端进程，恒跑）；
- `e2e_real`：真后端子进程档（`NEUROVA_E2E_REAL=1` 才跑，否则诚实跳过）。
页面对象封装见 `tests/e2e/pages/`。
"""

import os

import pytest
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neurova.core.event_bus import EventBus
from neurova.core.config import ConfigManager
from neurova.core.logger import LogManager
from neurova.security.rbac import RBACManager
from neurova.auth.password_hasher import PasswordHasher


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e_mock: mock 档（in-process mock LLM，恒跑）")
    config.addinivalue_line("markers", "e2e_real: 真后端档（NEUROVA_E2E_REAL=1 才跑）")


def pytest_collection_modifyitems(config, items):
    """真后端档默认跳过（诚实跳过原因随用例可见），显式开启才跑。"""
    real_enabled = os.environ.get("NEUROVA_E2E_REAL", "").strip() == "1"
    if real_enabled:
        return
    skip_real = pytest.mark.skip(
        reason="真后端档未开启：设置 NEUROVA_E2E_REAL=1 后运行（避免无后端时的假失败）")
    for item in items:
        if "e2e_real" in item.keywords:
            item.add_marker(skip_real)


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
    log_manager = LogManager(str(e2e_temp_storage / "logs"))

    return {
        "event_bus": event_bus,
        "config_manager": config_manager,
        "log_manager": log_manager
    }


# （S7 死码退役批）原 e2e_module_system fixture 已随 core/state_manager.py 一并退役：
# 它给 ModuleRegistry 传了 4 个不存在的 kwargs（ModuleRegistry.__init__ 不收参），
# 且 tests/e2e/ 下无任何消费者。


@pytest.fixture
def e2e_security_services():
    """提供安全相关服务"""
    rbac_manager = RBACManager()
    password_hasher = PasswordHasher()
    
    return {
        "rbac_manager": rbac_manager,
        "password_hasher": password_hasher
    }

