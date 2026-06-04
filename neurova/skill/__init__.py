"""
Skill模块兼容性层

提供 neurova.skill 命名空间，实际实现在 neurova.skills 和 neurova.skill_system 中。
这是为了兼容现有测试代码中的导入语句。
"""

import sys

from neurova.skills.models import ExperienceRecord
from fastapi import File
from neurova.mem_core import Memory
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
from neurova.skills.models import Skill
import importlib

# evolution imports
import neurova.evolution

# skill imports
import neurova.skill.skill_packer

# skill_system imports
import neurova.skill_system

# skills imports
import neurova.skills.evolution_engine
import neurova.skills.hub_client
import neurova.skills.manifest
import neurova.skills.models
import neurova.skills.pool_service
import neurova.skills.registry
import neurova.skills.security_scanner
import neurova.skills.skill_packager
import neurova.skills.skill_service

pass