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

本包是技能子系统的统一外观入口：`from neurova.skills import create_default_skills /
get_skill_registry` 都从这里取。

**这里只挂"确实有人经门面取用"的名字**（现算 2 个，出处 `agent_core.py:861,1257,1523`
与 `api/endpoints/skill.py:121,399,487`）。此前门面再导出 47 个名字，其余 45 个在
生产与测试两侧都零消费者——要用 `SkillInfo`/`SkillService` 的人都直取
`from neurova.skills.models import ...`，门面因此是同一词汇表的第二份抄本
（AGENTS.md §6）。子模块取法（`from neurova.skills import library_service /
market_sources / _lib`）不受影响：那是 import 语句自己解析子模块，不靠再导出。

批 42 之前这些导入包在 `try/except ImportError` 里并把 48 个名字赋成 `None`；那条兜底
永不可达（被包的模块顶层没有第三方可选依赖），而 `agent_core` 一旦落到那条分支拿到的是
None 并在下一行调用它——故改顶层直连，失败就显式抛。

`SkillSource` 全仓只有一份定义，在 `neurova/skills/models.py`：`hub_client` 里那份同名
枚举（市场源 GITHUB/CLAWHUB/LOBEHUB/MODELSCOPE/LOCAL）已于批 46 并入它，值逐字保留，
两段词汇改由 `installSources()` / `marketSources()` 与 `RemoteSkill.__post_init__`
显式承担。判据见 `tests/unit/skills/test_skillsFacadeAndSourceEnumAreSingleSourced.py`。
"""

from neurova.skill_system import create_default_skills, get_skill_registry

__all__ = [
    "create_default_skills",
    "get_skill_registry",
]
