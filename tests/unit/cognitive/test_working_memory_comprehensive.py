"""
Neurova Working Memory Augmenter - 全面单元测试

测试目标:
1. WorkingMemoryAugmenter 主类
"""

import pytest
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable

try:
    from neurova.cognitive_layers.memory_layer.working_memory import (
        WorkingMemoryAugmenter,
    )
    _HAS_WORKING_MEMORY = True
except ImportError:
    _HAS_WORKING_MEMORY = False

pytestmark = pytest.mark.skipif(not _HAS_WORKING_MEMORY, reason="WorkingMemoryAugmenter API changed - CachedPlan/FoldedState/SingleTurnCompressor/MultiTurnStateFolder/PlanCache removed")
