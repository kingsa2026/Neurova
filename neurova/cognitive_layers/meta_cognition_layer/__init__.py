"""
Meta Cognition Layer - 元认知层

实现 Neurova CogArch 1.0.0 的元认知层架构：
- 自我反思 (Self Reflection)
- 自我优化 (Self Optimization)
- 技能进化 (Skills Evolution)
- 成长日志 (Growth Log)
- 问题队列 (Question Queue)
- 自治系统 (Autonomy System)
- 宪法/基本指令 (Constitution)
...
"""

from neurova.agent_core import Agent
from neurova.agent_core import Agent
from neurova.skills.models import Skill

# cognitive_layers imports
import neurova.cognitive_layers.meta_cognition_layer.autonomy_system
import neurova.cognitive_layers.meta_cognition_layer.constitution
import neurova.cognitive_layers.meta_cognition_layer.growth_log
import neurova.cognitive_layers.meta_cognition_layer.meta_cognition
import neurova.cognitive_layers.meta_cognition_layer.personality
import neurova.cognitive_layers.meta_cognition_layer.question_queue
import neurova.cognitive_layers.meta_cognition_layer.self_optimization
import neurova.cognitive_layers.meta_cognition_layer.self_reflection
import neurova.cognitive_layers.meta_cognition_layer.skills_manager

pass