"""Bypass neurova.skill/__init__.py which imports from the broken neurova.skills package.

This conftest loads neurova.skill.skill_packer by file path and registers
a synthetic `neurova.skill` package so test modules can write
`from neurova.skill.skill_packer import ...`.
"""
import importlib.util
import sys
import types
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _PROJECT_ROOT / "neurova" / "skill" / "skill_packer.py"


def _install_synthetic_package() -> None:
    pkg = types.ModuleType("neurova.skill")
    pkg.__path__ = [str(_TARGET.parent)]
    sys.modules["neurova.skill"] = pkg


def _load_skill_packer():
    spec = importlib.util.spec_from_file_location(
        "neurova.skill.skill_packer", str(_TARGET)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["neurova.skill.skill_packer"] = mod
    spec.loader.exec_module(mod)
    return mod


_install_synthetic_package()
_MODULE = _load_skill_packer()

SkillCategory = _MODULE.SkillCategory
PackedSkill = _MODULE.PackedSkill
TaskExecutionRecord = _MODULE.TaskExecutionRecord
SkillPacker = _MODULE.SkillPacker
get_skill_packer = _MODULE.get_skill_packer
