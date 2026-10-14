"""
Skills System 1.0.0 - 技能系统

实现 Neurova CogArch 1.0.0 的技能系统1.0.0架构：
- builtin/: 内置技能 (只读)
- models.py: 数据模型 (SkillInfo, SkillSource, etc.)
- skill_service.py: Agent 技能服务 (SkillService)——存储引擎单源
- library_service.py: 三库路由（agent 私库 / 用户私库 / 公共库），取法
  `from neurova.skills import library_service`
- registry.py: 技能注册表
- manifest.py: 技能清单
- hub_client.py: 市场侧远端技能取数 (SkillHubClient, RemoteSkill)
- skill_install_gate.py: 安装门（所有安装面共用的唯一咽喉）

本包是技能子系统的统一外观入口：`from neurova.skills import SkillInfo / SkillService /
create_default_skills / get_skill_registry` 都从这里取。

这些导入此前包在 `try/except ImportError` 里，并在 except 分支把 48 个名字赋成 `None`。
现测被包的四个模块（models / hub_client / skill_service / skill_system）都可导入，
且它们顶层除 `__future__` 外没有第三方可选依赖 ⇒ 那条兜底从不触发；而按教义第 1 条，
替"不会发生的失败"在下游补 None 不是降级保护——`agent_core.py` 三处
`from neurova.skills import create_default_skills` 一旦落到那条分支，拿到的是 None
并在下一行调用它。故此处一律顶层直接导入，失败就显式抛。

`SkillSource` 只从 models 导那一份：`hub_client` 里另有一个同名枚举（成员是市场源
GITHUB/CLAWHUB/LOBEHUB/MODELSCOPE/LOCAL，与 models 的 LOCAL/MARKETPLACE/BUILTIN 不同物），
此前两条 import 先后绑同一个名字，门面给出去哪一份取决于书写顺序。两份要不要合并或改名
＝另一次裁定（台账 §6-200），这里先把静默覆盖摘掉，hub 自己仍用它那一份。
"""

from neurova.skills.models import (
    PluginEntryPoints,
    Skill,
    SkillConflict,
    SkillConflictResult,
    SkillConflictStats,
    SkillDependency,
    SkillDependencyResult,
    SkillDependencyStats,
    SkillDisableResult,
    SkillDisableStats,
    SkillEnableResult,
    SkillEnableStats,
    SkillExecutionLog,
    SkillExecutionResult,
    SkillExecutionStats,
    SkillInfo,
    SkillInstallResult,
    SkillInstallStats,
    SkillManifest,
    SkillMarketplaceStats,
    SkillMarketResult,
    SkillMetadata,
    SkillOutput,
    SkillParameter,
    SkillPublishResult,
    SkillPublishStats,
    SkillRecommendation,
    SkillRecommendationResult,
    SkillRecommendationStats,
    SkillRecord,
    SkillRequirement,
    SkillSearchResult,
    SkillSearchStats,
    SkillSource,
    SkillUninstallResult,
    SkillUninstallStats,
    SkillUpdateResult,
    SkillUpdateStats,
    SkillVerifyResult,
    SkillVerifyStats,
    SkillVersion,
)
from neurova.skills.hub_client import RemoteSkill, SkillHubClient
from neurova.skills.skill_service import SkillService
from neurova.skill_system import SkillRegistry, create_default_skills, get_skill_registry
