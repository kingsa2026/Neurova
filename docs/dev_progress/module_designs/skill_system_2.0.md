# 技能系统2.0 设计文档

> **模块ID**: Task3-SkillSystem2.0
> **创建时间**: 2026-05-12 21:00
> **最后更新**: 2026-05-12 22:00
> **负责人**: skill-system-dev
> **状态**: 进行中

---

## 1. 模块概述

### 1.1 功能描述

实现 Neurova CogArch 2.0 的技能系统2.0架构，融合 QwenPaw 的成熟设计（公共池 + Agent 专属池）与 Neurova 特色功能（自主进化、经验调用、自主打包）。

主要功能：
- **公共技能池管理**：所有 Agent 共享的技能池，支持从 Hub 安装、同步内置技能
- **Agent 专属技能管理**：每个 Agent 独立的技能空间，支持创建、编辑、删除
- **技能进化引擎**：根据使用反馈自动优化技能（Neurova 核心特色）
- **经验调用系统**：检索相似场景下的使用经验（Neurova 特色）
- **自主打包工具**：打包技能 + 使用经验 + 进化历史（Neurova 特色）
- **技能安全扫描**：静态代码分析、危险函数检测

### 1.2 设计依据

- **NEUROVA_CogArch_2.0.md 第3章**：技能系统2.0完整设计
- **借鉴 QwenPaw**：SkillPoolService、SkillService 基础架构
- **Neurova 特色**：SkillsEvolutionEngine、ExperienceCaller、SkillPackager

### 1.3 与其他模块的关系

- **依赖模块**:
  - `neurova.core`（基础设施：EventBus、Config、ServiceManager）
  - `neurova.cognitive_layers`（认知层：记忆系统，用于经验学习）

- **被依赖模块**:
  - `neurova.execution`（执行引擎：调用技能）
  - Web Console（UI 接口：技能管理界面）

---

## 2. 架构设计

### 2.1 类/函数设计

#### 2.1.1 数据模型 (`models.py`)

```python
class SkillSource(Enum):
    """技能来源"""
    BUILTIN = "builtin"         # 内置技能
    POOL = "pool"               # 公共池
    AGENT_PRIVATE = "agent"     # Agent 专属
    HUB = "hub"                 # 从 Hub 安装
    AUTO_GENERATED = "auto"     # 自动生成

@dataclass
class SkillInfo:
    """技能信息模型（借鉴 QwenPaw + Neurova 扩展）"""
    name: str
    description: str = ""
    version_text: str = "0.1.0"
    content: str = ""
    source: SkillSource = SkillSource.AGENT_PRIVATE
    references: Dict[str, Any] = None
    scripts: Dict[str, Any] = None
    emoji: str = ""
    tags: List[str] = None
    config: Dict[str, Any] = None
    enabled: bool = True

    # Neurova 特色字段
    evolution_history: List[Dict] = None  # 进化历史
    usage_statistics: Dict = None         # 使用统计
    experience_records: List[Dict] = None # 经验记录

@dataclass
class SkillEvolutionRecord:
    """技能进化记录"""
    version: str
    timestamp: str
    change_description: str
    performance_improvement: float
    feedback_source: str

@dataclass
class ExperienceRecord:
    """经验记录"""
    skill_name: str
    context: Dict
    result: Any
    success: bool
    timestamp: str
    feedback: str = ""
```

#### 2.1.2 `SkillPoolService` (`pool_service.py`)

```python
class SkillPoolService:
    """公共技能池服务（借鉴 QwenPaw）"""

    def __init__(self, pool_dir: Path, registry: Optional[SkillRegistry] = None):
        """初始化公共池服务"""

    def list_skills(self) -> List[SkillInfo]:
        """列出公共池所有技能"""

    def add_skill(self, skill: SkillInfo, overwrite: bool = False) -> bool:
        """添加技能到公共池"""

    def delete_skill(self, skill_name: str) -> bool:
        """从公共池删除技能"""

    def sync_builtin_skills(self) -> None:
        """同步内置技能到公共池"""

    def import_from_hub(self, hub_url: str, skill_name: str, version: str = "") -> SkillInfo:
        """从 Hub 导入技能"""

    def export_skill(self, skill_name: str, output_path: Path) -> bool:
        """导出技能为 ZIP"""

    def import_from_zip(self, zip_path: Path, overwrite: bool = False) -> List[SkillInfo]:
        """从 ZIP 文件导入技能"""
```

**属性/参数说明**:
- `pool_dir`: 公共池目录路径
- `manifest_path`: 技能清单文件 (`skill.json`)
- `skill`: SkillInfo 对象
- `overwrite`: 是否覆盖已存在的技能

**返回值**: 详见各方法 docstring

**异常**: `ValueError`, `ConnectionError`, `FileNotFoundError`

#### 2.1.3 `SkillService` (`skill_service.py`)

```python
class SkillService:
    """Agent 技能服务（借鉴 QwenPaw + Neurova 特色）"""

    # ============ QwenPaw 风格的基础功能 ============

    def __init__(self, workspace_dir: Path, agent_id: str, registry: Optional[SkillRegistry] = None):
        """初始化 Agent 技能服务"""

    def list_skills(self) -> List[SkillInfo]:
        """列出 Agent 的所有技能"""

    def create_skill(self, name: str, content: str, enable: bool = True) -> Optional[SkillInfo]:
        """创建新技能"""

    def save_skill(self, skill_name: str, content: str, target_name: str = None) -> bool:
        """保存技能"""

    def enable_skill(self, skill_name: str) -> bool:
        """启用技能"""

    def disable_skill(self, skill_name: str) -> bool:
        """禁用技能"""

    def delete_skill(self, skill_name: str) -> bool:
        """删除技能"""

    def import_from_pool(self, skill_name: str, overwrite: bool = False) -> bool:
        """从公共池导入技能"""

    def export_to_pool(self, skill_name: str, overwrite: bool = False) -> bool:
        """导出技能到公共池"""

    def import_from_zip(self, zip_path: Path, enable: bool = True) -> List[SkillInfo]:
        """从 ZIP 导入技能"""

    # ============ Neurova 特色功能 ============

    def evolve_skill(self, skill_name: str, feedback: Dict) -> SkillInfo:
        """自主进化技能（Neurova 核心特色！）"""

    def package_skill(self, skill_name: str, output_path: Optional[Path] = None) -> Path:
        """自主打包技能（Neurova 特色！）"""

    def call_experience(self, skill_name: str, context: Dict) -> Optional[ExperienceRecord]:
        """经验调用（Neurova 特色！）"""

    def get_skill_stats(self, skill_name: str) -> Dict:
        """获取技能使用统计"""

    def record_usage(self, skill_name: str, context: Dict, result: Any, success: bool) -> None:
        """记录技能使用"""
```

#### 2.1.4 `SkillsEvolutionEngine` (`evolution_engine.py`)

```python
class SkillsEvolutionEngine:
    """技能进化引擎（Neurova 核心特色！）"""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        """初始化技能进化引擎"""

    def analyze_skill_performance(self, skill: SkillInfo) -> Dict[str, float]:
        """分析技能性能"""

    def generate_improvement_suggestions(self, skill: SkillInfo) -> List[str]:
        """生成改进建议"""

    def evolve_skill(self, skill: SkillInfo, feedback: Dict) -> SkillInfo:
        """进化技能"""

    def auto_patch_skill(self, skill: SkillInfo, error_log: str) -> SkillInfo:
        """自动修补技能"""

    def get_evolution_history(self, skill: SkillInfo) -> List[Dict]:
        """获取技能的进化历史"""

    def rollback_to_version(self, skill: SkillInfo, target_version: str) -> Optional[SkillInfo]:
        """回滚到指定版本"""
```

#### 2.1.5 `ExperienceCaller` (`experience_caller.py`)

```python
class ExperienceCaller:
    """经验调用系统（Neurova 特色！）"""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        """初始化经验调用系统"""

    def find_similar_experiences(
        self, skill_name: str, context: Dict, limit: int = 5
    ) -> List[ExperienceRecord]:
        """找到相似的经验记录"""

    def extract_lessons_learned(self, experiences: List[ExperienceRecord]) -> List[str]:
        """从经验中提取教训"""

    def recommend_best_practices(self, skill_name: str) -> List[str]:
        """推荐最佳实践"""

    def save_experience_record(self, skill_name: str, exp: ExperienceRecord) -> bool:
        """保存经验记录"""

    def get_experience_stats(self, skill_name: str) -> Dict[str, Any]:
        """获取经验统计"""
```

#### 2.1.6 `SkillPackager` (`skill_packager.py`)

```python
class SkillPackager:
    """自主打包工具（Neurova 特色！）"""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        """初始化技能打包工具"""

    def package_for_sharing(
        self,
        skill: SkillInfo,
        output_path: Optional[Path] = None,
        include_history: bool = True,
        include_stats: bool = True,
    ) -> Path:
        """打包用于分享"""

    def package_for_evolution(self, skill: SkillInfo) -> Path:
        """打包用于进化"""

    def unpack_package(self, package_path: Path) -> SkillInfo:
        """解包"""

    def package_to_file(
        self,
        skill: SkillInfo,
        output_path: Path,
        format: str = "zip",
    ) -> Path:
        """打包技能到指定文件"""

    def get_package_info(self, package_path: Path) -> Dict[str, Any]:
        """获取打包文件信息（不解压）"""
```

### 2.2 数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                    技能系统2.0 数据流                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐│
│  │ 内置技能    │       │ 公共技能池  │       │ Agent 专属  ││
│  │ (builtin/)  │──────>│ (pool/)     │──────>│ (workspace/ ││
│  │ 只读        │ 同步   │ 所有Agent  │ 导入   │  skills/)   ││
│  └──────────────┘       └──────────────┘       └──────────────┘│
│                            │                            │          │
│                            │ 导入/导出                  │ 进化     │
│                            ▼                            │          │
│                       ┌──────────────┐       ┌──────────────┐│
│                       │ Hub         │       │ 进化引擎    ││
│                       │ (远程安装)  │       │ (自主优化)  ││
│                       └──────────────┘       └──────────────┘│
│                                                     │          │
│                                      经验调用      │          │
│                                      ┌──────────────┐│
│                                      │ 经验系统    ││
│                                      │ (记录/检索) ││
│                                      └──────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 状态机

无状态机设计。所有状态保存在文件系统（`skill.json` manifest 文件）。

---

## 3. 接口设计

### 3.1 API接口（规划中，待实现）

| 接口路径 | 方法 | 说明 | 请求参数 | 返回格式 |
|---------|------|------|---------|----------|
| `/api/skills` | GET | 列出 Agent 的技能 | `agent_id` | JSON |
| `/api/skills` | POST | 创建新技能 | `name`, `content` | JSON |
| `/api/skills/{name}` | PUT | 保存技能 | `content` | JSON |
| `/api/skills/{name}` | DELETE | 删除技能 | - | JSON |
| `/api/skills/pool` | GET | 列出公共池技能 | - | JSON |
| `/api/skills/pool/{name}` | POST | 从公共池导入 | `overwrite` | JSON |
| `/api/skills/{name}/evolve` | POST | 触发进化 | `feedback` | JSON |
| `/api/skills/{name}/package` | POST | 打包技能 | `output_path` | ZIP |

### 3.2 类接口

| 方法名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `SkillPoolService.list_skills()` | - | `List[SkillInfo]` | 列出公共池所有技能 |
| `SkillPoolService.add_skill()` | `skill`, `overwrite` | `bool` | 添加技能到公共池 |
| `SkillService.evolve_skill()` | `skill_name`, `feedback` | `SkillInfo` | 自主进化技能 |
| `SkillService.call_experience()` | `skill_name`, `context` | `Optional[ExperienceRecord]` | 经验调用 |
| `SkillsEvolutionEngine.analyze_skill_performance()` | `skill` | `Dict` | 分析技能性能 |
| `ExperienceCaller.find_similar_experiences()` | `skill_name`, `context` | `List[ExperienceRecord]` | 找到相似经验 |

---

## 4. 实现细节

### 4.1 已完成的子任务

- [x] 创建数据模型 (`models.py`)：SkillInfo, SkillSource, SkillEvolutionRecord, ExperienceRecord
- [x] 实现 SkillPoolService (`pool_service.py`)：所有方法已实现
- [x] 实现 SkillService (`skill_service.py`)：所有方法已实现（含 Neurova 特色功能）
- [x] 实现 SkillSelector (`skill_selector.py`)：从原 `skill_service.py` 移出
- [x] 更新 SkillRegistry (`registry.py`)：代码移到正确位置
- [x] 实现 SkillsEvolutionEngine (`evolution_engine.py`)：所有方法已实现
- [x] 实现 ExperienceCaller (`experience_caller.py`)：所有方法已实现
- [x] 实现 SkillPackager (`skill_packager.py`)：所有方法已实现
- [x] 创建内置技能同步脚本 (`scripts/sync_builtin_skills.py`)
- [x] 更新 `__init__.py`：正确的模块导入和导出

### 4.2 进行中的子任务

- [ ] 创建模块设计文档（本文件）
- [ ] 创建每日进度报告
- [ ] 更新 progress_tracker.md

### 4.3 待完成的子任务

- [ ] 添加单元测试（目标通过率 > 80%）
- [ ] 与 Web Console 集成（API 接口实现）
- [ ] 性能优化（大型技能池的加载速度）

### 4.4 关键代码片段

见各文件实现。

---

## 5. 测试计划

### 5.1 单元测试

| 测试用例 | 测试内容 | 状态 | 通过率 |
|---------|---------|------|--------|
| `test_models.py` | 数据模型测试 | 未开始 | - |
| `test_pool_service.py` | SkillPoolService 测试 | 未开始 | - |
| `test_skill_service.py` | SkillService 测试 | 未开始 | - |
| `test_evolution_engine.py` | SkillsEvolutionEngine 测试 | 未开始 | - |
| `test_experience_caller.py` | ExperienceCaller 测试 | 未开始 | - |
| `test_skill_packager.py` | SkillPackager 测试 | 未开始 | - |

### 5.2 集成测试

- 与 `neurova.execution` 集成：技能调用流程
- 与 Web Console 集成：技能管理 UI
- 与 MultiAgentManager 集成：多 Agent 技能隔离

### 5.3 性能测试

- 大型技能池（1000+ 技能）的加载速度
- 技能进化 engine 的处理速度
- 经验调用系统的检索速度

---

## 6. 已知问题

| 问题描述 | 严重程度 | 发现时间 | 解决方案 | 状态 |
|---------|---------|----------|--------|------|
| `SkillPackager.package_for_evolution()` 中进化历史保存路径未确定 | 低 | 2026-05-12 | 使用 `skills/<name>/evolution_history.json` | 未解决 |
| `SkillsEvolutionEngine._apply_improvements()` 是模拟实现 | 中 | 2026-05-12 | 需要集成 LLM 来生成真实改进 | 未解决 |
| Hub 客户端 (`import_from_hub`) 是模拟实现 | 中 | 2026-05-12 | 需要实现完整的 HTTP 客户端 | 未解决 |

---

## 7. 变更记录

| 时间 | 变更内容 | 变更原因 | 影响范围 |
|------|---------|---------|---------|
| 2026-05-12 21:00 | 初始创建模块设计文档 | 团队要求 | 无 |
| 2026-05-12 21:30 | 完成 `models.py` 数据模型 | 任务需求 | 所有模块 |
| 2026-05-12 21:45 | 完成 `pool_service.py` 和 `skill_service.py` | 任务需求 | Agent 技能管理 |
| 2026-05-12 22:00 | 完成 `evolution_engine.py`, `experience_caller.py`, `skill_packager.py` | 任务需求 | Neurova 特色功能 |

---

## 8. 附录

### 8.1 参考资料

- `docs/NEUROVA_CogArch_2.0.md` 第3章：技能系统2.0设计
- QwenPaw 官方文档：Plugin 架构设计
- Python dataclasses 官方文档

### 8.2 相关文件

- `neurova/skills/models.py`
- `neurova/skills/pool_service.py`
- `neurova/skills/skill_service.py`
- `neurova/skills/skill_selector.py`
- `neurova/skills/evolution_engine.py`
- `neurova/skills/experience_caller.py`
- `neurova/skills/skill_packager.py`
- `neurova/skills/registry.py`
- `neurova/skills/security_scanner.py`
- `scripts/sync_builtin_skills.py`

---

**最后更新**: 2026-05-12 22:00 | **更新人**: skill-system-dev
