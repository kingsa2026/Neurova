"""Skills System 2.0 - SkillPackager测试"""

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from unittest.mock import patch, MagicMock

from neurova.skills.models import SkillInfo, SkillSource, SkillEvolutionRecord
from neurova.skills.skill_packager import SkillPackager


@pytest.fixture
def skill_packager(tmp_path) -> SkillPackager:
    """创建SkillPackager实例"""
    return SkillPackager(skills_dir=tmp_path, output_dir=tmp_path / "packages")


@pytest.fixture
def sample_skill() -> SkillInfo:
    """创建示例技能"""
    return SkillInfo(
        name="test_skill",
        description="测试技能",
        source=SkillSource.LOCAL,
        version="1.0.0",
    )


class TestSkillPackagerInit:
    """测试SkillPackager初始化"""

    def test_init(self, skill_packager: SkillPackager):
        """初始化（目录就位）"""
        assert skill_packager._skills_dir is not None
        assert skill_packager._output_dir is not None


def _make_skill(skills_dir: Path, skill_id: str = "pk1") -> None:
    """在 skills_dir 下建立可打包的技能目录（实现按 skill_id 查找）"""
    skill_dir = skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text("# skill", encoding="utf-8")
    (skill_dir / "manifest.json").write_text('{"id": "%s", "name": "%s", "version": "1.0.0"}' % (skill_id, skill_id), encoding="utf-8")
    exp = skill_dir / "experience"
    exp.mkdir(exist_ok=True)
    (exp / "exp.json").write_text('[{"success": true}]', encoding="utf-8")


class TestPackageForSharing:
    """package_for_sharing(skill_id, include_experience, include_history)"""

    def test_package_for_sharing(self, skill_packager: SkillPackager, tmp_path: Path):
        _make_skill(skill_packager._skills_dir, "share1")
        result = skill_packager.package_for_sharing("share1")
        assert result is not None
        assert result.exists()
        assert result.suffix == ".zip"

    def test_package_nonexistent(self, skill_packager: SkillPackager):
        """技能目录不存在 → None（不 raise）"""
        assert skill_packager.package_for_sharing("ghost") is None

    def test_package_without_experience(self, skill_packager: SkillPackager):
        _make_skill(skill_packager._skills_dir, "noexp")
        result = skill_packager.package_for_sharing("noexp", include_experience=False)
        assert result is not None

    def test_package_with_history(self, skill_packager: SkillPackager):
        _make_skill(skill_packager._skills_dir, "hist")
        result = skill_packager.package_for_sharing("hist", include_history=True)
        assert result is not None


class TestUnpack:
    """unpack_package——异常契约：失败返回 None（不 raise）"""

    def test_unpack_nonexistent_package(self, skill_packager: SkillPackager):
        assert skill_packager.unpack_package(Path("nonexistent.zip")) is None

    def test_unpack_invalid_zip(self, skill_packager: SkillPackager, tmp_path: Path):
        bad = tmp_path / "invalid.zip"
        bad.write_text("not a zip file")
        assert skill_packager.unpack_package(bad) is None

    def test_unpack_roundtrip(self, skill_packager: SkillPackager, tmp_path: Path):
        _make_skill(skill_packager._skills_dir, "rt1")
        pkg = skill_packager.package_for_sharing("rt1")
        assert pkg is not None
        result = skill_packager.unpack_package(pkg)
        assert result is not None


class TestPackageToFile:
    """package_to_file(skill_id, output_path, package_type)"""

    def test_package_to_file(self, skill_packager: SkillPackager, tmp_path: Path):
        _make_skill(skill_packager._skills_dir, "pf1")
        out = tmp_path / "out.zip"
        result = skill_packager.package_to_file("pf1", out)
        assert result == out
        assert out.exists()

    def test_package_to_file_nonexistent(self, skill_packager: SkillPackager, tmp_path: Path):
        result = skill_packager.package_to_file("ghost", tmp_path / "x.zip")
        assert result is None


class TestGetPackageInfo:
    """get_package_info(package_path)"""

    def test_get_package_info(self, skill_packager: SkillPackager):
        _make_skill(skill_packager._skills_dir, "gi1")
        pkg = skill_packager.package_for_sharing("gi1")
        info = skill_packager.get_package_info(pkg)
        assert info is not None
        assert info.get("skill_id") == "gi1" or "skill_id" in str(info)

    def test_get_nonexistent_package_info(self, skill_packager: SkillPackager):
        assert skill_packager.get_package_info(Path("ghost.zip")) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
