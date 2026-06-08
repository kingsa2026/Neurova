"""
技能生成器 (Skill Generator)

生成新技能的模块，实现 Meta-skill 的 skill-for-skills 能力。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillGenerationResult:
    """技能生成结果"""
    success: bool = False
    skill_code: str = ""
    skill_config: Dict[str, Any] = field(default_factory=dict)
    skill_name: str = ""
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillRefinementResult:
    """技能优化结果"""
    success: bool = False
    improved: bool = False
    original_skill_id: str = ""
    refined_code: str = ""
    changes: List[str] = field(default_factory=list)
    error: str = ""


@dataclass
class SkillValidationResult:
    """技能验证结果"""
    valid: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    complexity_score: float = 0.0
    security_score: float = 0.0


class SkillGenerator:
    """
    技能生成器
    
    根据需求描述生成新技能的代码和配置。
    实现 Meta-skill 的 skill-for-skills 能力。
    """
    
    def __init__(self, llm_client=None, template_dir: Optional[str] = None):
        """
        初始化技能生成器
        
        Args:
            llm_client: LLM 客户端，用于代码生成
            template_dir: 技能模板目录
        """
        self.llm_client = llm_client
        self.template_dir = template_dir
        self._generation_history: Dict[str, SkillGenerationResult] = {}
        
        logger.info("SkillGenerator 初始化完成")
    
    async def generate_skill(self, requirement: str, context: Optional[Dict[str, Any]] = None) -> SkillGenerationResult:
        """
        生成新技能
        
        Args:
            requirement: 技能需求描述
            context: 上下文信息，包含约束、偏好等
            
        Returns:
            SkillGenerationResult: 技能生成结果
        """
        try:
            # 分析需求
            analysis = await self._analyze_requirement(requirement, context)
            
            # 生成技能代码
            skill_code = await self._generate_skill_code(analysis)
            
            # 生成技能配置
            skill_config = await self._generate_skill_config(analysis)
            
            # 验证生成的技能
            validation = await self.validate_skill(skill_code)
            
            if not validation.valid:
                return SkillGenerationResult(
                    success=False,
                    error=f"生成的技能验证失败: {validation.errors}",
                    warnings=validation.warnings
                )
            
            # 生成技能名称
            skill_name = self._generate_skill_name(requirement)
            
            result = SkillGenerationResult(
                success=True,
                skill_code=skill_code,
                skill_config=skill_config,
                skill_name=skill_name,
                warnings=validation.warnings,
                metadata={
                    "requirement": requirement,
                    "context": context,
                    "complexity_score": validation.complexity_score,
                    "security_score": validation.security_score
                }
            )
            
            # 记录生成历史
            self._generation_history[skill_name] = result
            
            logger.info(f"技能生成成功: {skill_name}")
            return result
            
        except Exception as e:
            logger.error(f"技能生成失败: {e}")
            return SkillGenerationResult(
                success=False,
                error=str(e)
            )
    
    async def refine_skill(self, skill_id: str, feedback: str) -> SkillRefinementResult:
        """
        优化现有技能
        
        Args:
            skill_id: 技能 ID
            feedback: 优化反馈
            
        Returns:
            SkillRefinementResult: 优化结果
        """
        try:
            # 获取原始技能
            if skill_id not in self._generation_history:
                return SkillRefinementResult(
                    success=False,
                    original_skill_id=skill_id,
                    error=f"找不到技能: {skill_id}"
                )
            
            original = self._generation_history[skill_id]
            
            # 分析反馈
            feedback_analysis = await self._analyze_feedback(feedback)
            
            # 优化代码
            refined_code = await self._refine_skill_code(original.skill_code, feedback_analysis)
            
            # 验证优化后的技能
            validation = await self.validate_skill(refined_code)
            
            if not validation.valid:
                return SkillRefinementResult(
                    success=False,
                    original_skill_id=skill_id,
                    error=f"优化后的技能验证失败: {validation.errors}"
                )
            
            result = SkillRefinementResult(
                success=True,
                improved=True,
                original_skill_id=skill_id,
                refined_code=refined_code,
                changes=feedback_analysis.get("changes", [])
            )
            
            logger.info(f"技能优化成功: {skill_id}")
            return result
            
        except Exception as e:
            logger.error(f"技能优化失败: {e}")
            return SkillRefinementResult(
                success=False,
                original_skill_id=skill_id,
                error=str(e)
            )
    
    async def validate_skill(self, skill_code: str) -> SkillValidationResult:
        """
        验证技能代码
        
        Args:
            skill_code: 技能代码
            
        Returns:
            SkillValidationResult: 验证结果
        """
        try:
            errors = []
            warnings = []
            suggestions = []
            
            # 语法检查
            syntax_valid = await self._check_syntax(skill_code)
            if not syntax_valid:
                errors.append("代码语法错误")
            
            # 安全检查
            security_issues = await self._check_security(skill_code)
            errors.extend(security_issues)
            
            # 复杂度分析
            complexity_score = await self._analyze_complexity(skill_code)
            
            # 最佳实践检查
            practice_warnings = await self._check_best_practices(skill_code)
            warnings.extend(practice_warnings)
            
            # 生成建议
            if complexity_score > 0.8:
                suggestions.append("建议简化代码逻辑，降低复杂度")
            
            if len(errors) == 0:
                suggestions.append("代码结构良好，建议添加更多注释")
            
            return SkillValidationResult(
                valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                suggestions=suggestions,
                complexity_score=complexity_score,
                security_score=1.0 - (len(security_issues) * 0.2)
            )
            
        except Exception as e:
            logger.error(f"技能验证失败: {e}")
            return SkillValidationResult(
                valid=False,
                errors=[f"验证过程出错: {str(e)}"]
            )
    
    async def _analyze_requirement(self, requirement: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """分析技能需求"""
        # 使用 LLM 分析需求
        if self.llm_client:
            prompt = f"""
            分析以下技能需求，提取关键信息：
            
            需求: {requirement}
            上下文: {context}
            
            请返回 JSON 格式的分析结果，包含：
            1. 功能描述
            2. 输入输出格式
            3. 依赖项
            4. 复杂度评估
            5. 安全考虑
            """
            
            # 模拟 LLM 调用
            analysis = {
                "功能描述": requirement,
                "输入输出格式": {"input": "dict", "output": "dict"},
                "依赖项": [],
                "复杂度评估": "中等",
                "安全考虑": [],
                "context": context or {}
            }
            
            return analysis
        
        # 默认分析
        return {
            "功能描述": requirement,
            "输入输出格式": {"input": "dict", "output": "dict"},
            "依赖项": [],
            "复杂度评估": "中等",
            "安全考虑": [],
            "context": context or {}
        }
    
    async def _generate_skill_code(self, analysis: Dict[str, Any]) -> str:
        """生成技能代码"""
        # 模拟代码生成
        skill_code = f'''
"""
自动生成的技能

功能: {analysis.get("功能描述", "未知")}
"""

from typing import Any, Dict


def execute(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行技能
    
    Args:
        input_data: 输入数据
        
    Returns:
        Dict[str, Any]: 执行结果
    """
    try:
        # 技能实现
        result = {{"success": True, "data": input_data}}
        
        return result
        
    except Exception as e:
        return {{"success": False, "error": str(e)}}


def get_metadata() -> Dict[str, Any]:
    """
    获取技能元数据
    
    Returns:
        Dict[str, Any]: 技能元数据
    """
    return {{
        "name": "auto_generated_skill",
        "version": "1.0.0",
        "description": "{analysis.get("功能描述", "自动生成的技能")}",
        "author": "Neurova Skill Generator",
        "tags": ["auto-generated"],
        "dependencies": {analysis.get("依赖项", [])}
    }}
'''
        return skill_code
    
    async def _generate_skill_config(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """生成技能配置"""
        # 从上下文中提取信息
        context = analysis.get("context", {})
        file_types = context.get("file_types", [])
        
        # 确定支持的格式
        supported_formats = ["json"]  # 默认格式
        if file_types:
            supported_formats.extend(file_types)
            supported_formats = list(set(supported_formats))  # 去重
        
        return {
            "name": "auto_generated_skill",
            "version": "1.0.0",
            "description": analysis.get("功能描述", ""),
            "parameters": {},
            "output_schema": {},
            "supported_formats": supported_formats,
            "timeout": 30,
            "retry_count": 3,
            "security_level": "standard",
            "context": context
        }
    
    def _generate_skill_name(self, requirement: str) -> str:
        """生成技能名称"""
        # 简单的名称生成逻辑
        import re
        import hashlib
        
        # 提取关键词
        words = re.findall(r'\w+', requirement.lower())
        if len(words) >= 2:
            name = f"{words[0]}_{words[1]}"
        else:
            name = "auto_skill"
        
        # 添加哈希后缀避免冲突
        hash_suffix = hashlib.md5(requirement.encode()).hexdigest()[:6]
        return f"{name}_{hash_suffix}"
    
    async def _analyze_feedback(self, feedback: str) -> Dict[str, Any]:
        """分析优化反馈"""
        # 模拟反馈分析
        return {
            "changes": ["根据反馈优化了代码逻辑"],
            "priority": "高",
            "scope": "功能增强"
        }
    
    async def _refine_skill_code(self, original_code: str, feedback_analysis: Dict[str, Any]) -> str:
        """优化技能代码"""
        # 模拟代码优化
        refined_code = original_code.replace(
            "# 技能实现",
            "# 根据反馈优化的技能实现"
        )
        return refined_code
    
    async def _check_syntax(self, code: str) -> bool:
        """检查代码语法"""
        try:
            compile(code, '<string>', 'exec')
            return True
        except SyntaxError:
            return False
    
    async def _check_security(self, code: str) -> List[str]:
        """安全检查"""
        issues = []
        
        # 检查危险函数
        dangerous_patterns = [
            "exec(",
            "eval(",
            "os.system(",
            "subprocess.call(",
            "__import__(",
        ]
        
        for pattern in dangerous_patterns:
            if pattern in code:
                issues.append(f"发现潜在危险函数: {pattern}")
        
        return issues
    
    async def _analyze_complexity(self, code: str) -> float:
        """分析代码复杂度"""
        # 简单的复杂度评估
        lines = len(code.split('\n'))
        functions = code.count('def ')
        classes = code.count('class ')
        
        # 归一化复杂度分数
        complexity = min(1.0, (lines / 100 + functions / 10 + classes / 5))
        return complexity
    
    async def _check_best_practices(self, code: str) -> List[str]:
        """检查最佳实践"""
        warnings = []
        
        # 检查注释
        if '"""' not in code and "'''" not in code:
            warnings.append("建议添加文档字符串")
        
        # 检查类型提示
        if '->' not in code and ':' not in code.split('def ')[1] if 'def ' in code else True:
            warnings.append("建议添加类型提示")
        
        return warnings