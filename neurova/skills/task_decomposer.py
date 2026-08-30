from __future__ import annotations

"""
Task Decomposer - 任务拆解器

实现 Neurova CogArch 1.0.0 的任务拆解功能。
Agent 能够分析用户请求，拆解为子任务，并识别所需的技能。
"""

import json
from neurova.core.logger import get_logger
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .models import SkillChain, SkillChainStep

logger = get_logger(__name__)


@dataclass
class SubTask:
    """
    子任务数据类
    """

    id: str
    description: str
    task_type: str = "general"
    required_skills: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0
    estimated_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "description": self.description,
            "task_type": self.task_type,
            "required_skills": self.required_skills,
            "dependencies": self.dependencies,
            "priority": self.priority,
            "estimated_time": self.estimated_time,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubTask":
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            task_type=data.get("task_type", "general"),
            required_skills=data.get("required_skills", []),
            dependencies=data.get("dependencies", []),
            priority=data.get("priority", 0),
            estimated_time=data.get("estimated_time", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskDecompositionResult:
    """
    任务拆解结果数据类
    """

    original_request: str
    subtasks: List[SubTask] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)
    decomposition_strategy: str = "rules"
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_request": self.original_request,
            "subtasks": [subtask.to_dict() for subtask in self.subtasks],
            "required_skills": self.required_skills,
            "decomposition_strategy": self.decomposition_strategy,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskDecompositionResult":
        """从字典创建"""
        return cls(
            original_request=data.get("original_request", ""),
            subtasks=[SubTask.from_dict(s) for s in data.get("subtasks", [])],
            required_skills=data.get("required_skills", []),
            decomposition_strategy=data.get("decomposition_strategy", "rules"),
            confidence=data.get("confidence", 0.0),
            metadata=data.get("metadata", {}),
        )

    def get_execution_order(self) -> List[str]:
        """
        获取执行顺序

        Returns:
            List[str]: 按依赖关系排序的任务 ID 列表
        """
        # 拓扑排序
        visited = set()
        order = []

        def visit(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)

            # 先访问依赖
            for subtask in self.subtasks:
                if subtask.id == task_id:
                    for dep in subtask.dependencies:
                        visit(dep)
                    break

            order.append(task_id)

        for subtask in self.subtasks:
            visit(subtask.id)

        return order


class TaskDecomposer:
    """
    任务拆解器

    分析用户请求，将其拆解为可执行的子任务。
    支持 LLM 驱动和规则驱动两种拆解策略。
    """

    # 任务类型关键词映射
    TASK_TYPE_KEYWORDS = {
        "analysis": ["分析", "分析", "研究", "调查", "检查", "评估", "analyze", "research", "investigate"],
        "creation": ["创建", "创建", "生成", "构建", "开发", "编写", "create", "generate", "build", "develop"],
        "modification": ["修改", "更新", "改进", "优化", "重构", "modify", "update", "improve", "optimize"],
        "deletion": ["删除", "移除", "清理", "清除", "delete", "remove", "cleanup"],
        "search": ["搜索", "查找", "寻找", "检索", "search", "find", "lookup"],
        "communication": ["发送", "通知", "联系", "沟通", "send", "notify", "contact"],
        "automation": ["自动化", "定时", "计划", "批量", "automate", "schedule", "batch"],
    }

    # 技能需求关键词映射
    SKILL_KEYWORDS = {
        "web-development": ["网站", "网页", "前端", "后端", "API", "web", "website", "frontend", "backend"],
        "database": ["数据库", "SQL", "查询", "存储", "database", "query", "storage"],
        "ai-ml": ["机器学习", "深度学习", "AI", "模型", "训练", "machine learning", "deep learning", "AI", "model"],
        "data-analysis": ["数据", "统计", "分析", "可视化", "data", "statistics", "analysis", "visualization"],
        "file-management": ["文件", "文档", "图片", "视频", "file", "document", "image", "video"],
        "network": ["网络", "HTTP", "请求", "下载", "network", "HTTP", "request", "download"],
        "security": ["安全", "加密", "认证", "权限", "security", "encryption", "authentication", "permission"],
    }

    def __init__(self, llm_client: Optional[Any] = None, config: Optional[Dict[str, Any]] = None):
        """
        初始化任务拆解器

        Args:
            llm_client: LLM 客户端（可选）
            config: 配置字典
        """
        self.llm_client = llm_client
        self.config = config or {}
        self._use_llm = llm_client is not None
        logger.info("TaskDecomposer initialized")

    def decompose(self, request: str) -> TaskDecompositionResult:
        """
        拆解任务

        Args:
            request: 用户请求

        Returns:
            TaskDecompositionResult: 拆解结果
        """
        # 尝试使用 LLM 拆解
        if self._use_llm:
            try:
                result = self._decompose_with_llm(request)
                if result and result.subtasks:
                    return result
            except Exception as e:
                logger.warning("LLM decomposition failed: %s", e)

        # 回退到规则拆解
        return self._decompose_with_rules(request)

    def _decompose_with_llm(self, request: str) -> Optional[TaskDecompositionResult]:
        """
        使用 LLM 拆解任务

        Args:
            request: 用户请求

        Returns:
            Optional[TaskDecompositionResult]: 拆解结果
        """
        if not self.llm_client:
            return None

        try:
            # 构建提示词
            prompt = self._build_decomposition_prompt(request)

            # 调用 LLM
            response = self.llm_client.generate(prompt)

            # 解析响应
            return self._parse_llm_response(response, request)

        except Exception as e:
            logger.error("LLM decomposition error: %s", e)
            return None

    def _build_decomposition_prompt(self, request: str) -> str:
        """
        构建拆解提示词

        Args:
            request: 用户请求

        Returns:
            str: 提示词
        """
        prompt = f"""请将以下用户请求拆解为可执行的子任务。

用户请求：{request}

请以 JSON 格式返回拆解结果，包含以下字段：
- subtasks: 子任务列表，每个子任务包含 id, description, task_type, required_skills, dependencies
- required_skills: 整体需要的技能列表
- decomposition_strategy: 拆解策略（llm）

任务类型包括：analysis, creation, modification, deletion, search, communication, automation

请确保：
1. 每个子任务都是可独立执行的
2. 依赖关系正确
3. 技能需求准确

返回格式：
```json
{{
  "subtasks": [
    {{
      "id": "task-1",
      "description": "任务描述",
      "task_type": "类型",
      "required_skills": ["技能1", "技能2"],
      "dependencies": []
    }}
  ],
  "required_skills": ["技能1", "技能2"],
  "decomposition_strategy": "llm"
}}
```"""

        return prompt

    def _parse_llm_response(self, response: str, original_request: str) -> Optional[TaskDecompositionResult]:
        """
        解析 LLM 响应

        Args:
            response: LLM 响应
            original_request: 原始请求

        Returns:
            Optional[TaskDecompositionResult]: 拆解结果
        """
        try:
            # 提取 JSON 部分
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return None

            json_str = json_match.group()
            data = json.loads(json_str)

            # 构建子任务
            subtasks = []
            for subtask_data in data.get("subtasks", []):
                subtask = SubTask.from_dict(subtask_data)
                subtasks.append(subtask)

            return TaskDecompositionResult(
                original_request=original_request,
                subtasks=subtasks,
                required_skills=data.get("required_skills", []),
                decomposition_strategy="llm",
                confidence=0.8,
            )

        except Exception as e:
            logger.error("Failed to parse LLM response: %s", e)
            return None

    def _decompose_with_rules(self, request: str) -> TaskDecompositionResult:
        """
        使用规则拆解任务

        Args:
            request: 用户请求

        Returns:
            TaskDecompositionResult: 拆解结果
        """
        # 识别任务类型
        task_types = self._identify_task_types(request)

        # 识别所需技能
        required_skills = self._identify_required_skills(request)

        # 提取步骤
        steps = self._extract_steps(request)

        # 构建子任务
        subtasks = []
        for i, step in enumerate(steps, 1):
            subtask = SubTask(
                id=f"task-{i}",
                description=step,
                task_type=task_types[0] if task_types else "general",
                required_skills=required_skills,
                dependencies=[f"task-{i-1}"] if i > 1 else [],
            )
            subtasks.append(subtask)

        # 如果没有明确的步骤，创建一个通用任务
        if not subtasks:
            subtasks.append(
                SubTask(
                    id="task-1",
                    description=request,
                    task_type=task_types[0] if task_types else "general",
                    required_skills=required_skills,
                )
            )

        return TaskDecompositionResult(
            original_request=request,
            subtasks=subtasks,
            required_skills=required_skills,
            decomposition_strategy="rules",
            confidence=0.6,
        )

    def _identify_task_types(self, request: str) -> List[str]:
        """
        识别任务类型

        Args:
            request: 用户请求

        Returns:
            List[str]: 任务类型列表
        """
        request_lower = request.lower()
        identified_types = []

        for task_type, keywords in self.TASK_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in request_lower:
                    identified_types.append(task_type)
                    break

        return identified_types if identified_types else ["general"]

    def _identify_required_skills(self, request: str) -> List[str]:
        """
        识别所需技能

        Args:
            request: 用户请求

        Returns:
            List[str]: 所需技能列表
        """
        request_lower = request.lower()
        required_skills = []

        for skill, keywords in self.SKILL_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in request_lower:
                    required_skills.append(skill)
                    break

        return required_skills

    def _extract_steps(self, request: str) -> List[str]:
        """
        提取步骤

        Args:
            request: 用户请求

        Returns:
            List[str]: 步骤列表
        """
        steps = []

        # 尝试从请求中提取编号步骤
        numbered_pattern = r"(?:^|\n)\s*(?:\d+[\.\)、]|\-\s*|\*\s*)\s*(.+)"
        matches = re.findall(numbered_pattern, request, re.MULTILINE)

        if matches:
            steps = [match.strip() for match in matches if match.strip()]

        # 如果没有明确的步骤，尝试按句子拆分
        if not steps:
            # 按句号、分号、换行符拆分
            sentences = re.split(r"[。；\n]", request)
            steps = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]

        return steps

    def analyze_skill_needs(self, request: str) -> List[str]:
        """
        分析技能需求

        Args:
            request: 用户请求

        Returns:
            List[str]: 所需技能列表
        """
        # 先拆解任务
        result = self.decompose(request)

        # 收集所有技能需求
        all_skills = set(result.required_skills)
        for subtask in result.subtasks:
            all_skills.update(subtask.required_skills)

        return list(all_skills)

    def get_task_complexity(self, request: str) -> Dict[str, Any]:
        """
        获取任务复杂度信息

        Args:
            request: 用户请求

        Returns:
            Dict[str, Any]: 复杂度信息
        """
        result = self.decompose(request)

        return {
            "num_subtasks": len(result.subtasks),
            "num_dependencies": sum(len(s.dependencies) for s in result.subtasks),
            "num_skills": len(result.required_skills),
            "has_dependencies": any(s.dependencies for s in result.subtasks),
            "task_types": list(set(s.task_type for s in result.subtasks)),
            "confidence": result.confidence,
        }

    async def plan_skill_chain(self, task: str) -> "SkillChain":
        """
        规划技能链

        Args:
            task: 任务描述

        Returns:
            SkillChain: 技能链规划结果
        """
        from .models import SkillChain, SkillChainStep

        # 分解任务
        decomposition = self.decompose(task)

        # 创建技能链步骤
        steps = []
        for i, subtask in enumerate(decomposition.subtasks):
            # 确定技能 ID
            skill_id = self._map_subtask_to_skill(subtask)

            # 创建输入输出映射
            input_mapping = {}
            output_mapping = {}

            # 如果有依赖，设置输入映射
            if subtask.dependencies:
                for dep_id in subtask.dependencies:
                    input_mapping[f"input_from_{dep_id}"] = f"output_of_{dep_id}"

            # 设置输出映射
            output_mapping[f"output_of_{subtask.id}"] = "result"

            step = SkillChainStep(
                step_id=subtask.id,
                skill_id=skill_id,
                input_mapping=input_mapping,
                output_mapping=output_mapping,
                timeout=30.0,
                retry_count=1,
                metadata={
                    "description": subtask.description,
                    "task_type": subtask.task_type,
                    "priority": subtask.priority,
                },
            )
            steps.append(step)

        # 创建技能链
        chain = SkillChain(
            chain_id=f"chain_{hash(task) % 10000:04d}",
            name=f"任务链: {task[:50]}",
            description=f"自动生成的技能链: {task}",
            steps=steps,
            variables={"original_task": task, "required_skills": decomposition.required_skills},
            metadata={"generated_by": "TaskDecomposer", "complexity": self.get_task_complexity(task)},
        )

        return chain

    async def optimize_chain(self, steps: List["SkillChainStep"]) -> List["SkillChainStep"]:
        """
        优化技能链顺序

        Args:
            steps: 技能链步骤列表

        Returns:
            List[SkillChainStep]: 优化后的步骤列表
        """

        # 构建依赖图
        dependency_graph = {}
        step_map = {}

        for step in steps:
            step_map[step.step_id] = step
            dependency_graph[step.step_id] = []

            # 从输入映射中提取依赖
            for input_key in step.input_mapping.values():
                if input_key.startswith("output_of_"):
                    dep_id = input_key[10:]  # 移除 "output_of_" 前缀 (10字符)
                    dependency_graph[step.step_id].append(dep_id)

        # 拓扑排序
        sorted_steps = self._topological_sort(dependency_graph, step_map)

        # 优化：将低优先级任务移到后面
        optimized = self._prioritize_steps(sorted_steps)

        return optimized

    async def estimate_chain_cost(self, chain_plan: "SkillChain") -> Dict[str, Any]:
        """
        估算技能链执行成本

        Args:
            chain_plan: 技能链计划

        Returns:
            Dict[str, Any]: 成本估算结果
        """
        total_time = 0.0
        resource_levels = []

        for step in chain_plan.steps:
            # 估算时间
            estimated_time = step.metadata.get("estimated_time", 1.0)
            total_time += estimated_time

            # 评估资源强度
            resource_intensity = step.metadata.get("resource_intensity", "medium")
            resource_levels.append(resource_intensity)

        # 确定总体资源级别
        resource_mapping = {"low": 1, "medium": 2, "high": 3}
        avg_resource = sum(resource_mapping.get(r, 2) for r in resource_levels) / len(resource_levels)

        if avg_resource < 1.5:
            overall_resource = "low"
        elif avg_resource < 2.5:
            overall_resource = "medium"
        else:
            overall_resource = "high"

        return {
            "total_time": total_time,
            "resource_level": overall_resource,
            "step_count": len(chain_plan.steps),
            "estimated_complexity": self._estimate_chain_complexity(chain_plan),
            "parallelizable": self._check_parallelizable(chain_plan),
        }

    def _map_subtask_to_skill(self, subtask: "SubTask") -> str:
        """将子任务映射到技能 ID"""
        # 基于任务类型和技能需求映射
        task_type = subtask.task_type
        required_skills = subtask.required_skills

        # 映射逻辑
        if "web-development" in required_skills:
            return "web_crawler"
        elif "database" in required_skills:
            return "database_manager"
        elif "ai-ml" in required_skills:
            return "ai_analyzer"
        elif "data-analysis" in required_skills:
            return "data_processor"
        elif "file-management" in required_skills:
            return "file_manager"
        elif "network" in required_skills:
            return "network_requester"
        elif "security" in required_skills:
            return "security_scanner"
        else:
            # 基于任务类型
            type_to_skill = {
                "analysis": "analyzer",
                "creation": "creator",
                "modification": "modifier",
                "deletion": "deleter",
                "search": "searcher",
                "communication": "communicator",
                "automation": "automator",
            }
            return type_to_skill.get(task_type, "general_executor")

    def _topological_sort(
        self, dependency_graph: Dict[str, List[str]], step_map: Dict[str, "SkillChainStep"]
    ) -> List["SkillChainStep"]:
        """拓扑排序"""
        visited = set()
        temp_visited = set()
        order = []

        def dfs(node):
            if node in temp_visited:
                raise ValueError(f"检测到循环依赖: {node}")
            if node in visited:
                return

            temp_visited.add(node)

            for dependency in dependency_graph.get(node, []):
                dfs(dependency)

            temp_visited.remove(node)
            visited.add(node)
            order.append(node)

        for node in dependency_graph:
            if node not in visited:
                dfs(node)

        # order 已经是依赖在前的正确顺序（DFS 后序遍历），无需反转
        return [step_map[node] for node in order if node in step_map]

    def _prioritize_steps(self, steps: List["SkillChainStep"]) -> List["SkillChainStep"]:
        """按优先级排序步骤"""
        # 按优先级排序（高优先级先执行）
        return sorted(steps, key=lambda s: s.metadata.get("priority", 0), reverse=True)

    def _estimate_chain_complexity(self, chain_plan: "SkillChain") -> str:
        """估算技能链复杂度"""
        step_count = len(chain_plan.steps)

        if step_count <= 3:
            return "low"
        elif step_count <= 6:
            return "medium"
        else:
            return "high"

    def _check_parallelizable(self, chain_plan: "SkillChain") -> bool:
        """检查技能链是否可以并行执行"""
        # 检查是否有步骤没有依赖关系
        independent_steps = 0

        for step in chain_plan.steps:
            has_dependencies = False
            for input_key in step.input_mapping.values():
                if input_key.startswith("output_of_"):
                    has_dependencies = True
                    break

            if not has_dependencies:
                independent_steps += 1

        # 如果有多个独立步骤，可以考虑并行执行
        return independent_steps >= 2
