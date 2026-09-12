"""技能评审闸（C10 治理收紧，2026-09-12）。

对齐 jiuwenswarm auto_save 默认 false 的哲学：改行为的进化产物默认先进
待审，经审批面激活后才生效。NEUROVA_SKILL_REVIEW_GATE=0 显式关闭
（回退旧行为：产物直接生效）。

覆盖产物（同一开关统一裁决）：
- AutoSkillBuilder 自动封装技能（is_active=False pending，原有审批面）
- SkillPacker 打包技能（metadata.review_pending，待审不入工具记忆）
- ToolGeneticEngine 遗传技能 / NLToolSynthesizer 合成技能（注册即禁用）
- SkillExperienceStore 自动化来源的 applied 经验（improver/attribution，
  pending 审批后注入描述；重建只消费已批准记录）

历史注记：原实现默认关的依据是"闸开必须有审批面，否则为断点"——
审批面（skill_pool_api pending-skills list/approve/reject + 技能启停）
现已齐备，默认收紧的前提成立。
"""

import os

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def skill_review_gate_enabled() -> bool:
    """C10 评审闸：默认开（改行为的产物强制审批）。

    NEUROVA_SKILL_REVIEW_GATE=0 显式关闭恢复旧行为；其余值（含未设置）
    均视为开启。
    """
    return os.environ.get("NEUROVA_SKILL_REVIEW_GATE", "1") != "0"
