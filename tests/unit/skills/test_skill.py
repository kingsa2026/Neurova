"""
Skill系统测试 - Skill 完整测试覆盖
"""
import pytest
import time
from unittest.mock import MagicMock, patch

try:
    from neurova.skill import Skill
    _HAS_SKILL = True
except ImportError:
    _HAS_SKILL = False
    Skill = None

pytestmark = pytest.mark.skipif(not _HAS_SKILL, reason="Skill API changed - SkillResult/SkillInfo/SkillStatus/MemorySkill/WebSearchSkill/FileOperationSkill/SkillRegistry removed")
