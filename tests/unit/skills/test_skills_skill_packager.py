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
def skill_packager() -> SkillPackager:
    """创建SkillPackager实例"""
    return SkillPackager()


@pytest.fixture
def sample_skill() -> SkillInfo:
    """创建示例技能"""
    return SkillInfo(
        name="test_skill",
        description="测试技能",
        content="def run():\n    return 'hello'",
        source=SkillSource.AGENT_PRIVATE,
        version_text="1.0.0",
        evolution_history=[
            {"version": "1.0.0", "change": "初始版本"}
        ],
        experience_records=[
            {
                "skill_name": "test_skill",
                "context": {"input": "test"},
                "result": {"output": "hello"},
                "success": True,
                "timestamp": "2026-05-12T22:00:00",
            }
        ],
    )


class TestSkillPackagerInit:
    """测试SkillPackager初始化"""

    def test_init(self, skill_packager: SkillPackager):
        """初始化"""
        assert skill_packager._registry is not None


class TestPackageForSharing:
    """测试package_for_sharing方法"""

    def test_package_for_sharing(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包用于分享"""
        output_path = tmp_path / "test_skill.zip"
        result = skill_packager.package_for_sharing(sample_skill, output_path)
        
        assert result.exists()
        assert result.stat().st_size > 0
        
        # 验证ZIP内容
        with zipfile.ZipFile(result, "r") as zipf:
            file_list = zipf.namelist()
            assert "skill.json" in file_list
            assert "metadata.json" in file_list

    def test_package_for_sharing_default_path(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包用于分享（默认路径）"""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = skill_packager.package_for_sharing(sample_skill)
            assert result.exists()
            assert result.name == "test_skill.zip"

    def test_package_without_history(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包不包含历史"""
        output_path = tmp_path / "test_skill_no_history.zip"
        result = skill_packager.package_for_sharing(
            sample_skill, output_path, include_history=False
        )
        
        assert result.exists()
        
        # 验证历史已被移除
        with zipfile.ZipFile(result, "r") as zipf:
            manifest_data = json.loads(zipf.read("skill.json"))
            assert "evolution_history" not in manifest_data

    def test_package_without_stats(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包不包含统计"""
        output_path = tmp_path / "test_skill_no_stats.zip"
        result = skill_packager.package_for_sharing(
            sample_skill, output_path, include_stats=False
        )
        
        assert result.exists()
        
        # 验证统计已被移除
        with zipfile.ZipFile(result, "r") as zipf:
            manifest_data = json.loads(zipf.read("skill.json"))
            assert "usage_statistics" not in manifest_data
            assert "experience_records" not in manifest_data


class TestPackageForEvolution:
    """测试package_for_evolution方法"""

    def test_package_for_evolution(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包用于进化"""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = skill_packager.package_for_evolution(sample_skill)
            
            assert result.exists()
            assert "evolution" in result.name
            
            # 验证ZIP内容包含历史和经验
            with zipfile.ZipFile(result, "r") as zipf:
                file_list = zipf.namelist()
                assert "skill.json" in file_list
                assert "evolution_history.json" in file_list
                assert "experiences.json" in file_list


class TestUnpackPackage:
    """测试unpack_package方法"""

    def test_unpack_package(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """解包"""
        # 先打包
        zip_path = tmp_path / "test_skill.zip"
        skill_packager.package_for_sharing(sample_skill, zip_path)
        
        # 再解包
        unpacked = skill_packager.unpack_package(zip_path)
        
        assert unpacked is not None
        assert unpacked.name == "test_skill"
        assert unpacked.version_text == "1.0.0"

    def test_unpack_nonexistent_package(self, skill_packager: SkillPackager):
        """解包不存在的文件"""
        with pytest.raises(FileNotFoundError):
            skill_packager.unpack_package(Path("nonexistent.zip"))

    def test_unpack_invalid_zip(self, skill_packager: SkillPackager, tmp_path: Path):
        """解包无效的ZIP文件"""
        invalid_zip = tmp_path / "invalid.zip"
        invalid_zip.write_text("not a zip file")
        
        with pytest.raises(zipfile.BadZipFile):
            skill_packager.unpack_package(invalid_zip)


class TestPackageToFile:
    """测试package_to_file方法"""

    def test_package_to_file(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包技能到指定文件"""
        output_path = tmp_path / "output.zip"
        result = skill_packager.package_to_file(sample_skill, output_path)
        
        assert result.exists()
        assert result.stat().st_size > 0

    def test_package_to_file_unsupported_format(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包到不支持的格式"""
        output_path = tmp_path / "output.tar"
        
        with pytest.raises(ValueError):
            skill_packager.package_to_file(sample_skill, output_path, format="tar")


class TestGetPackageInfo:
    """测试get_package_info方法"""

    def test_get_package_info(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """获取打包文件信息"""
        # 先打包
        zip_path = tmp_path / "test_skill.zip"
        skill_packager.package_for_sharing(sample_skill, zip_path)
        
        # 获取信息
        info = skill_packager.get_package_info(zip_path)
        
        assert info["skill_name"] == "test_skill"
        assert info["version"] == "1.0.0"
        assert info["file_count"] > 0
        assert "files" in info

    def test_get_nonexistent_package_info(self, skill_packager: SkillPackager):
        """获取不存在的打包文件信息"""
        with pytest.raises(FileNotFoundError):
            skill_packager.get_package_info(Path("nonexistent.zip"))

    def test_get_package_info_no_manifest(self, skill_packager: SkillPackager, tmp_path: Path):
        """获取没有清单的打包文件信息"""
        # 创建一个没有skill.json的ZIP文件
        zip_path = tmp_path / "no_manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            zipf.writestr("README.md", "# Test")
        
        with pytest.raises(FileNotFoundError):
            skill_packager.get_package_info(zip_path)


class TestIntegration:
    """集成测试"""

    def test_package_and_unpack(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包后解包"""
        # 打包
        zip_path = tmp_path / "integration_test.zip"
        skill_packager.package_for_sharing(sample_skill, zip_path)
        
        # 解包
        unpacked = skill_packager.unpack_package(zip_path)
        
        assert unpacked.name == sample_skill.name
        assert unpacked.description == sample_skill.description

    def test_package_for_evolution_and_read(self, skill_packager: SkillPackager, sample_skill: SkillInfo, tmp_path: Path):
        """打包用于进化并读取"""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            # 打包
            zip_path = skill_packager.package_for_evolution(sample_skill)
            
            # 验证内容
            with zipfile.ZipFile(zip_path, "r") as zipf:
                # 读取进化历史
                evolution_data = json.loads(zipf.read("evolution_history.json"))
                assert len(evolution_data) > 0
                
                # 读取经验记录
                experiences_data = json.loads(zipf.read("experiences.json"))
                assert len(experiences_data) > 0
