"""
GitHub Push Skill - Neurova GitHub 推送技能

封装完整的 Git 操作流程，支持：
1. 检查 Git 状态
2. 添加文件
3. 提交更改
4. 推送到 main 分支（支持直接推送而非合并）
"""

from neurova.skills.builtin.github_push.skill import (
    GitHubPushSkill,
    create_github_push_skill,
    push_to_github,
)

__all__ = [
    "GitHubPushSkill",
    "create_github_push_skill", 
    "push_to_github",
]

# 版本信息
__version__ = "1.0.0"
__author__ = "Neurova Team"
__description__ = "GitHub 推送技能 - 封装完整的 Git 操作流程"