"""
测试三级内存隔离功能
"""
import tempfile
import shutil
import sys
from pathlib import Path

import pytest

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from neurova.cognitive_layers.memory_layer import AgentMemoryLayer
    _HAS_AGENT_MEMORY_LAYER = True
except ImportError:
    _HAS_AGENT_MEMORY_LAYER = False

pytestmark = pytest.mark.skipif(not _HAS_AGENT_MEMORY_LAYER, reason="AgentMemoryLayer not found in memory_layer")
