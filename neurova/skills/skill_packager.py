"""
Skill Packager - 自主打包工具

实现 Neurova CogArch 1.0.0 的自主打包工具（Neurova 特色）。
打包技能 + 使用经验 + 进化历史，便于分享和部署。

主要功能:
- 打包用于分享
- 打包用于进化
- 解包
"""

from __future__ import annotations

import datetime
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SkillPackager:
    """
    技能打包器

    支持将技能及其相关数据打包为可分享的归档文件。
    """

    def __init__(self, skills_dir: Path, output_dir: Optional[Path] = None):
        """
        Args:
            skills_dir: 技能目录路径
            output_dir: 输出目录路径，默认为 skills_dir/packages
        """
        self._skills_dir = Path(skills_dir)
        self._output_dir = Path(output_dir) if output_dir else self._skills_dir / "packages"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def package_for_sharing(
        self,
        skill_id: str,
        include_experience: bool = True,
        include_history: bool = False,
    ) -> Optional[Path]:
        """
        打包技能用于分享

        Args:
            skill_id: 技能ID
            include_experience: 是否包含使用经验
            include_history: 是否包含进化历史

        Returns:
            打包文件路径，失败返回 None
        """
        skill_dir = self._skills_dir / skill_id
        if not skill_dir.exists():
            logger.error("Skill directory not found: %s", skill_dir)
            return None

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        package_name = f"{skill_id}_share_{timestamp}.zip"
        package_path = self._output_dir / package_name

        try:
            with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 打包技能核心文件
                self._add_directory_to_zip(zf, skill_dir, prefix="skill/")

                # 打包使用经验
                if include_experience:
                    exp_dir = self._skills_dir / skill_id / "experience"
                    if exp_dir.exists():
                        self._add_directory_to_zip(zf, exp_dir, prefix="experience/")

                # 打包进化历史
                if include_history:
                    history_dir = self._skills_dir / skill_id / "evolution_history"
                    if history_dir.exists():
                        self._add_directory_to_zip(zf, history_dir, prefix="evolution/")

                # 写入打包元数据
                meta = {
                    "skill_id": skill_id,
                    "package_type": "sharing",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "include_experience": include_experience,
                    "include_history": include_history,
                }
                zf.writestr("package_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

            logger.info("Packaged skill '%s' for sharing: %s", skill_id, package_path)
            return package_path

        except Exception as e:
            logger.error("Failed to package skill '%s': %s", skill_id, e)
            if package_path.exists():
                package_path.unlink()
            return None

    def package_for_evolution(
        self,
        skill_id: str,
        evolution_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        打包技能用于进化

        包含完整的进化上下文：技能、经验、性能指标、进化历史

        Args:
            skill_id: 技能ID
            evolution_context: 额外的进化上下文

        Returns:
            打包文件路径
        """
        skill_dir = self._skills_dir / skill_id
        if not skill_dir.exists():
            logger.error("Skill directory not found: %s", skill_dir)
            return None

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        package_name = f"{skill_id}_evo_{timestamp}.zip"
        package_path = self._output_dir / package_name

        try:
            with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 打包所有技能数据
                self._add_directory_to_zip(zf, skill_dir, prefix="skill/")

                # 写入进化上下文
                evo_context = evolution_context or {}
                evo_context["skill_id"] = skill_id
                evo_context["package_type"] = "evolution"
                evo_context["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

                zf.writestr("evolution_context.json", json.dumps(evo_context, ensure_ascii=False, indent=2))

            logger.info("Packaged skill '%s' for evolution: %s", skill_id, package_path)
            return package_path

        except Exception as e:
            logger.error("Failed to package skill '%s' for evolution: %s", skill_id, e)
            if package_path.exists():
                package_path.unlink()
            return None

    def unpack_package(
        self,
        package_path: Path,
        target_dir: Optional[Path] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        解包技能包

        Args:
            package_path: 包文件路径
            target_dir: 目标目录，默认为 skills_dir

        Returns:
            包含包元数据的字典，失败返回 None
        """
        package_path = Path(package_path)
        if not package_path.exists():
            logger.error("Package file not found: %s", package_path)
            return None

        target = Path(target_dir) if target_dir else self._skills_dir

        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                # 读取元数据
                meta = None
                for name in zf.namelist():
                    if name.endswith("package_meta.json") or name.endswith("evolution_context.json"):
                        meta = json.loads(zf.read(name))
                        break

                # 解压文件
                zf.extractall(target)

                logger.info("Unpacked package to: %s", target)
                return meta

        except zipfile.BadZipFile:
            logger.error("Invalid zip file: %s", package_path)
            return None
        except Exception as e:
            logger.error("Failed to unpack package: %s", e)
            return None

    def package_to_file(
        self,
        skill_id: str,
        output_path: Path,
        package_type: str = "sharing",
    ) -> Optional[Path]:
        """
        打包技能到指定文件路径

        Args:
            skill_id: 技能ID
            output_path: 输出文件路径
            package_type: 包类型 (sharing/evolution/full)

        Returns:
            输出文件路径
        """
        if package_type == "sharing":
            result = self.package_for_sharing(skill_id)
        elif package_type == "evolution":
            result = self.package_for_evolution(skill_id)
        else:
            # 完整打包
            result = self.package_for_sharing(skill_id, include_experience=True, include_history=True)

        if result and result != output_path:
            shutil.move(str(result), str(output_path))
            return output_path

        return result

    def get_package_info(self, package_path: Path) -> Optional[Dict[str, Any]]:
        """
        获取包信息（不解压）

        Args:
            package_path: 包文件路径

        Returns:
            包信息字典
        """
        package_path = Path(package_path)
        if not package_path.exists():
            return None

        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                info = {
                    "file_count": len(zf.namelist()),
                    "total_size": sum(info.file_size for info in zf.infolist()),
                    "compressed_size": sum(info.compress_size for info in zf.infolist()),
                    "files": zf.namelist(),
                }

                # 读取元数据
                for name in zf.namelist():
                    if name.endswith("package_meta.json") or name.endswith("evolution_context.json"):
                        info["metadata"] = json.loads(zf.read(name))
                        break

                return info

        except Exception as e:
            logger.error("Failed to read package info: %s", e)
            return None

    def _add_directory_to_zip(
        self,
        zf: zipfile.ZipFile,
        directory: Path,
        prefix: str = "",
    ) -> None:
        """将目录添加到 zip 文件"""
        for file_path in directory.rglob("*"):
            if file_path.is_file():
                arcname = prefix + str(file_path.relative_to(directory))
                zf.write(file_path, arcname)
