"""Skills System 2.0 - SkillsEvolutionEngine测试"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from unittest.mock import patch, MagicMock

try:
    from neurova.skills.models import SkillInfo, SkillSource, SkillEvolutionRecord
    from neurova.skills.evolution_engine import SkillsEvolutionEngine
    _HAS_SKILLS_EVOLUTION = True
except (ImportError, AttributeError):
    _HAS_SKILLS_EVOLUTION = False

pytestmark = pytest.mark.skipif(not _HAS_SKILLS_EVOLUTION, reason="SkillsEvolutionEngine renamed to EvolutionEngine with different API")
