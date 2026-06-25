"""
Agent Builder v1.0.0 — 声明式 Agent 构建器

隔离层级: 工具全局 + 产物用户层
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .templates.personality_templates import PersonalityTemplate

logger = get_logger(__name__)


@dataclass
class AgentBuildConfig:
    """Agent 构建配置"""

    name: str
    user_id: str = ""
    personality: Dict = field(default_factory=dict)
    skills: List[str] = field(default_factory=list)
    memory_types: List[str] = field(
        default_factory=lambda: ["conversation", "emotional", "experience", "skill", "tool_usage"]
    )
    emotion_baseline: str = "joy"
    emotion_sensitivity: float = 0.8
    constitution: List[str] = field(default_factory=list)
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    enable_memory: bool = True
    enable_evolution: bool = True
    enable_cognitive: bool = True


class AgentBuilder:
    """声明式 Agent 构建器 v1.0.0

    使用方式:
        agent = (AgentBuilder("alice")
            .personality(PersonalityTemplate.WARM_COMPANION)
            .skill("code_review")
            .memory(types=["conversation", "emotional"])
            .emotion(baseline="joy")
            .constitution(rules=["永远保持善意"])
            .model("deepseek-v4-flash")
            .build(user_id="user_42")
    """

    def __init__(self, name: str):
        self._config = AgentBuildConfig(name=name)
        logger.debug("AgentBuilder: 开始构建 %s", name)

    def personality(self, template_or_dict):
        """设置人格 — 接受模板或自定义字典"""
        if isinstance(template_or_dict, dict):
            self._config.personality = template_or_dict
        else:
            # 尝试从 PersonalityTemplate 获取
            attr_name = [k for k in dir(PersonalityTemplate) if getattr(PersonalityTemplate, k) == template_or_dict]
            if attr_name:
                self._config.personality = getattr(PersonalityTemplate, attr_name[0])
            else:
                self._config.personality = template_or_dict
        return self

    def skill(self, skill_name: str):
        """添加一个技能"""
        if skill_name not in self._config.skills:
            self._config.skills.append(skill_name)
        return self

    def skills(self, skill_list: List[str]):
        """批量添加技能"""
        for s in skill_list:
            self.skill(s)
        return self

    def memory(self, types: List[str] = None, temperature_base: float = 60.0):
        """设置记忆配置"""
        if types:
            self._config.memory_types = types
        self._memory_temp_base = temperature_base
        return self

    def emotion(self, baseline: str = "joy", sensitivity: float = 0.8):
        """设置情感配置"""
        self._config.emotion_baseline = baseline
        self._config.emotion_sensitivity = sensitivity
        return self

    def constitution(self, rules: List[str]):
        """设置宪法规则"""
        self._config.constitution = rules
        return self

    def model(self, model_name: str, temperature: float = 0.7):
        """设置模型"""
        self._config.model = model_name
        self._config.temperature = temperature
        return self

    def enable_all(self, memory: bool = True, evolution: bool = True, cognitive: bool = True):
        """批量设置功能开关"""
        self._config.enable_memory = memory
        self._config.enable_evolution = evolution
        self._config.enable_cognitive = cognitive
        return self

    def build(self, user_id: str) -> Dict[str, Any]:
        """构建 Agent — 产物绑定 user_id（用户层隔离）

        Returns:
            Agent 配置字典（可直接传入 Agent.__init__）
        """
        self._config.user_id = user_id

        # 生成 agent_id = user_id:name
        agent_id = f"{user_id}:{self._config.name}"

        # 构建配置字典
        config = {
            "agent_id": agent_id,
            "name": self._config.name,
            "user_id": user_id,
            "personality": self._config.personality,
            "skills": self._config.skills,
            "memory": {
                "types": self._config.memory_types,
                "temperature_base": getattr(self, "_memory_temp_base", 60.0),
            },
            "emotion": {
                "baseline": self._config.emotion_baseline,
                "sensitivity": self._config.emotion_sensitivity,
            },
            "constitution": self._config.constitution,
            "llm_config": {
                "model": self._config.model,
                "temperature": self._config.temperature,
            },
            "enable_memory": self._config.enable_memory,
            "enable_evolution": self._config.enable_evolution,
            "enable_cognitive": self._config.enable_cognitive,
        }

        logger.info(
            f"AgentBuilder: 构建完成 {agent_id} "
            f"(人格: {self._config.personality.get('name', '自定义')}, "
            f"模型: {self._config.model})"
        )

        return config

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "AgentBuilder":
        """从字典配置构建"""
        builder = cls(config.get("name", "unnamed"))

        if "personality" in config:
            builder.personality(config["personality"])
        if "skills" in config:
            builder.skills(config["skills"])
        if "emotion" in config:
            em = config["emotion"]
            builder.emotion(
                baseline=em.get("baseline", "joy"),
                sensitivity=em.get("sensitivity", 0.8),
            )
        if "constitution" in config:
            builder.constitution(config["constitution"])
        if "llm_config" in config:
            llm = config["llm_config"]
            builder.model(
                model_name=llm.get("model", "deepseek-v4-flash"),
                temperature=llm.get("temperature", 0.7),
            )

        return builder
