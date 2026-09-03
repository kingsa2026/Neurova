"""
Skill安全扫描系统测试

测试SkillScanner、SkillSandbox和SecurityManager的功能。
"""

import pytest

try:
    from neurova.skill import SecurityLevel, SkillScanner, SkillSandbox, SecurityManager
    from neurova.skill.manifest import SkillManifest, SkillRecord
    from neurova.skill.registry import SkillRegistry
    _HAS_SECURITY = True
except (ImportError, ModuleNotFoundError):
    _HAS_SECURITY = False

pytestmark = pytest.mark.skipif(not _HAS_SECURITY, reason="Skill security modules (SecurityLevel/SkillScanner/SkillSandbox/SecurityManager) not found")
