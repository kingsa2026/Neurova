"""
项目转技能器 (Project to Skill Converter)

将现有项目或代码片段转换为可复用的技能。
实现 Meta-skill 的 project-to-skill 能力。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ExtractedSkill, ProjectAnalysisResult, SkillPackage

logger = get_logger(__name__)


class ProjectToSkillConverter:
    """
    项目转技能器

    将现有项目或代码片段转换为可复用的技能。
    实现 Meta-skill 的 project-to-skill 能力。
    """

    def __init__(self, output_dir: Optional[str] = None):
        """
        初始化项目转技能器

        Args:
            output_dir: 技能输出目录
        """
        self.output_dir = Path(output_dir) if output_dir else Path("./generated_skills")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("ProjectToSkillConverter 初始化完成")

    async def analyze_project(self, project_path: str) -> ProjectAnalysisResult:
        """
        分析项目结构

        Args:
            project_path: 项目路径

        Returns:
            ProjectAnalysisResult: 项目分析结果
        """
        try:
            project_path_obj = Path(project_path)

            if not project_path_obj.exists():
                raise FileNotFoundError(f"项目路径不存在: {project_path}")

            # 收集项目文件
            files = await self._collect_project_files(project_path_obj)

            # 分析依赖
            dependencies = await self._analyze_dependencies(project_path_obj)

            # 识别入口点
            entry_points = await self._identify_entry_points(project_path_obj, files)

            # 计算复杂度
            complexity_score = await self._calculate_complexity(files)

            # 识别主函数
            main_function = await self._identify_main_function(project_path_obj, entry_points)

            result = ProjectAnalysisResult(
                project_path=project_path,
                files=files,
                dependencies=dependencies,
                main_function=main_function,
                complexity_score=complexity_score,
                entry_points=entry_points,
                metadata={
                    "file_count": len(files),
                    "dependency_count": len(dependencies),
                    "project_type": await self._detect_project_type(project_path_obj),
                },
            )

            logger.info("项目分析完成: %s, 文件数: %s", project_path, len(files))
            return result

        except Exception as e:
            logger.error("项目分析失败: %s", e)
            return ProjectAnalysisResult(project_path=project_path, metadata={"error": str(e)})

    async def extract_skill(self, analysis: ProjectAnalysisResult, skill_name: str) -> ExtractedSkill:
        """
        从分析结果提取技能

        Args:
            analysis: 项目分析结果
            skill_name: 技能名称

        Returns:
            ExtractedSkill: 提取的技能
        """
        try:
            # 选择入口点
            entry_point = analysis.entry_points[0] if analysis.entry_points else "main.py"

            # 提取核心代码
            core_code = await self._extract_core_code(analysis.project_path, entry_point)

            # 生成技能包装代码
            wrapped_code = await self._wrap_as_skill(core_code, skill_name, analysis)

            # 生成技能配置
            skill_config = await self._generate_skill_config(skill_name, analysis)

            # 提取参数
            parameters = await self._extract_parameters(core_code)

            result = ExtractedSkill(
                skill_name=skill_name,
                code=wrapped_code,
                config=skill_config,
                dependencies=analysis.dependencies,
                entry_point=entry_point,
                parameters=parameters,
                metadata={
                    "original_project": analysis.project_path,
                    "complexity_score": analysis.complexity_score,
                    "file_count": len(analysis.files),
                },
            )

            logger.info("技能提取成功: %s", skill_name)
            return result

        except Exception as e:
            logger.error("技能提取失败: %s", e)
            return ExtractedSkill(skill_name=skill_name, metadata={"error": str(e)})

    async def package_as_skill(self, extracted: ExtractedSkill) -> SkillPackage:
        """
        打包为技能

        Args:
            extracted: 提取的技能

        Returns:
            SkillPackage: 技能包
        """
        try:
            # 创建技能目录
            skill_dir = self.output_dir / extracted.skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)

            # 写入技能代码
            skill_file = skill_dir / "skill.py"
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(extracted.code)

            # 写入配置文件
            config_file = skill_dir / "config.json"
            import json

            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(extracted.config, f, indent=2, ensure_ascii=False)

            # 写入依赖文件
            if extracted.dependencies:
                deps_file = skill_dir / "requirements.txt"
                with open(deps_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(extracted.dependencies))

            # 写入元数据
            metadata_file = skill_dir / "metadata.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(extracted.metadata, f, indent=2, ensure_ascii=False)

            result = SkillPackage(
                success=True,
                skill_path=skill_dir,
                skill_name=extracted.skill_name,
                version=extracted.config.get("version", "1.0.0"),
                metadata={
                    "files_created": [str(skill_file), str(config_file), str(metadata_file)],
                    "size_bytes": sum(f.stat().st_size for f in skill_dir.iterdir() if f.is_file()),
                },
            )

            logger.info("技能打包成功: %s -> %s", extracted.skill_name, skill_dir)
            return result

        except Exception as e:
            logger.error("技能打包失败: %s", e)
            return SkillPackage(success=False, skill_name=extracted.skill_name, error=str(e))

    async def _collect_project_files(self, project_path: Path) -> List[str]:
        """收集项目文件"""
        files = []

        # 支持的文件扩展名
        supported_extensions = {".py", ".js", ".ts", ".java", ".go", ".rs"}

        for root, dirs, filenames in os.walk(project_path):
            # 跳过隐藏目录和常见忽略目录
            dirs[:] = [
                d for d in dirs if not d.startswith(".") and d not in ["node_modules", "__pycache__", "venv", ".git"]
            ]

            for filename in filenames:
                if Path(filename).suffix in supported_extensions:
                    rel_path = Path(root).relative_to(project_path) / filename
                    files.append(str(rel_path))

        return files

    async def _analyze_dependencies(self, project_path: Path) -> List[str]:
        """分析项目依赖"""
        dependencies = []

        # 检查 requirements.txt
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # 提取包名
                        pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0]
                        dependencies.append(pkg_name)

        # 检查 setup.py
        setup_file = project_path / "setup.py"
        if setup_file.exists():
            # 简单解析 setup.py 中的 install_requires
            with open(setup_file, "r", encoding="utf-8") as f:
                content = f.read()
                if "install_requires" in content:
                    # 简单提取，实际应该用 AST 解析
                    import re

                    match = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
                    if match:
                        deps_str = match.group(1)
                        deps = re.findall(r"'([^']*)'|\"([^\"]*)\"", deps_str)
                        for dep in deps:
                            pkg_name = dep[0] or dep[1]
                            if pkg_name:
                                dependencies.append(pkg_name.split("==")[0].split(">=")[0])

        return list(set(dependencies))  # 去重

    async def _identify_entry_points(self, project_path: Path, files: List[str]) -> List[str]:
        """识别入口点"""
        entry_points = []

        # 常见的入口点文件名
        common_entry_points = ["main.py", "app.py", "server.py", "run.py", "index.py", "cli.py", "start.py", "init.py"]

        # 检查根目录
        for entry in common_entry_points:
            if (project_path / entry).exists():
                entry_points.append(entry)

        # 检查子目录中的入口点
        for file in files:
            file_path = Path(file)
            if file_path.name in common_entry_points:
                entry_points.append(file)

        # 如果没有找到，选择第一个 Python 文件
        if not entry_points and files:
            for file in files:
                if file.endswith(".py"):
                    entry_points.append(file)
                    break

        return entry_points

    async def _calculate_complexity(self, files: List[str]) -> float:
        """计算项目复杂度"""
        if not files:
            return 0.0

        # 基于文件数量和类型的复杂度评估
        len(files)

        # 不同文件类型的权重
        weights = {".py": 1.0, ".js": 0.8, ".ts": 0.9, ".java": 1.2, ".go": 0.7, ".rs": 1.5}

        total_weight = 0
        for file in files:
            ext = Path(file).suffix
            total_weight += weights.get(ext, 0.5)

        # 归一化到 0-1 范围
        complexity = min(1.0, total_weight / 20.0)  # 假设 20 个加权文件为最大复杂度

        return complexity

    async def _identify_main_function(self, project_path: Path, entry_points: List[str]) -> str:
        """识别主函数"""
        if not entry_points:
            return "main"

        # 检查第一个入口点文件
        entry_file = project_path / entry_points[0]
        if not entry_file.exists():
            return "main"

        try:
            with open(entry_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 查找主函数定义
            import re

            patterns = [
                r"def\s+main\s*\(",
                r"def\s+run\s*\(",
                r"def\s+start\s*\(",
                r"def\s+app\s*\(",
                r'if\s+__name__\s*==\s*["\']__main__["\']',
            ]

            for pattern in patterns:
                if re.search(pattern, content):
                    # 提取函数名
                    match = re.search(r"def\s+(\w+)\s*\(", content)
                    if match:
                        return match.group(1)

            return "main"

        except Exception:
            return "main"

    async def _detect_project_type(self, project_path: Path) -> str:
        """检测项目类型"""
        # 检查特征文件
        if (project_path / "package.json").exists():
            return "nodejs"
        elif (project_path / "setup.py").exists() or (project_path / "pyproject.toml").exists():
            return "python"
        elif (project_path / "Cargo.toml").exists():
            return "rust"
        elif (project_path / "go.mod").exists():
            return "golang"
        elif (project_path / "pom.xml").exists():
            return "java"
        else:
            return "unknown"

    async def _extract_core_code(self, project_path: str, entry_point: str) -> str:
        """提取核心代码"""
        entry_file = Path(project_path) / entry_point

        if not entry_file.exists():
            raise FileNotFoundError(f"入口文件不存在: {entry_file}")

        with open(entry_file, "r", encoding="utf-8") as f:
            return f.read()

    async def _wrap_as_skill(self, core_code: str, skill_name: str, analysis: ProjectAnalysisResult) -> str:
        """将代码包装为技能"""
        # 生成技能包装代码
        wrapped_code = f'''
"""
技能: {skill_name}

从项目转换而来: {analysis.project_path}
"""

import sys
from pathlib import Path

# 添加项目路径到 sys.path
project_path = Path("{analysis.project_path}")
if str(project_path) not in sys.path:
    sys.path.insert(0, str(project_path))

# 导入原始代码
{core_code}

# 技能接口
def execute(input_data):
    """
    执行技能
    
    Args:
        input_data: 输入数据
        
    Returns:
        执行结果
    """
    try:
        # 调用主函数
        if callable({analysis.main_function}):
            result = {analysis.main_function}(input_data)
            return {{"success": True, "result": result}}
        else:
            return {{"success": False, "error": "主函数不可调用"}}
    except Exception as e:
        return {{"success": False, "error": str(e)}}

def get_metadata():
    """
    获取技能元数据
    
    Returns:
        技能元数据
    """
    return {{
        "name": "{skill_name}",
        "version": "1.0.0",
        "description": "从项目 {analysis.project_path} 转换的技能",
        "author": "Neurova ProjectToSkill Converter",
        "tags": ["converted", "project-to-skill"],
        "dependencies": {analysis.dependencies},
        "entry_point": "{analysis.entry_points[0] if analysis.entry_points else 'main.py'}",
        "original_project": "{analysis.project_path}"
    }}
'''
        return wrapped_code

    async def _generate_skill_config(self, skill_name: str, analysis: ProjectAnalysisResult) -> Dict[str, Any]:
        """生成技能配置"""
        return {
            "name": skill_name,
            "version": "1.0.0",
            "description": f"从项目 {analysis.project_path} 转换的技能",
            "author": "Neurova ProjectToSkill Converter",
            "tags": ["converted", "project-to-skill"],
            "parameters": {},
            "output_schema": {},
            "dependencies": analysis.dependencies,
            "entry_point": analysis.entry_points[0] if analysis.entry_points else "",
            "timeout": 60,
            "retry_count": 3,
            "security_level": "standard",
            "original_project": analysis.project_path,
            "complexity_score": analysis.complexity_score,
        }

    async def _extract_parameters(self, code: str) -> Dict[str, Any]:
        """从代码中提取参数"""
        parameters = {}

        # 简单的参数提取逻辑
        import re

        # 查找函数定义
        func_pattern = r"def\s+(\w+)\s*\((.*?)\):"
        matches = re.findall(func_pattern, code, re.DOTALL)

        for func_name, args_str in matches:
            if func_name in ["execute", "main", "run", "start"]:
                # 解析参数
                args = [arg.strip() for arg in args_str.split(",") if arg.strip()]

                for arg in args:
                    # 处理默认值
                    if "=" in arg:
                        name, default = arg.split("=", 1)
                        name = name.strip()
                        default = default.strip()
                        parameters[name] = {"type": "any", "required": False, "default": default}
                    else:
                        # 处理类型提示
                        if ":" in arg:
                            name, type_hint = arg.split(":", 1)
                            name = name.strip()
                            type_hint = type_hint.strip()
                            parameters[name] = {"type": type_hint, "required": True}
                        else:
                            parameters[arg] = {"type": "any", "required": True}

        return parameters
