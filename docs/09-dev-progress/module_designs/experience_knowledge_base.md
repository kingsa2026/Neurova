# Experience Knowledge Base - 经验知识库

## 模块概述

经验知识库是 Neurova CogArch 2.0 四层存储架构的第四层，负责存储和管理技能使用经验，提供效果评估和智能推荐功能。

## 设计目标

根据设计文档 [NEUROVA_CogArch_2.0.md](E:/项目/Neurova/docs/NEUROVA_CogArch_2.0.md) 第269行和297行的描述，经验知识库应满足以下需求：

1. **统一存储**：将经验记录统一存储到数据库（而非文件）
2. **效果评估**：提供系统化的技能效果评估功能
3. **智能推荐**：基于经验和上下文提供智能推荐
4. **API 接口**：提供完整的 RESTful API 接口

## 实现内容

### 1. 核心类：ExperienceKnowledgeBase

**文件**：`neurova/skills/experience_knowledge_base.py`

**主要功能**：

- `add_experience_record()` - 添加经验记录
- `get_experience_records()` - 获取经验记录（支持过滤和分页）
- `find_similar_experiences()` - 查找相似经验
- `evaluate_skill_effectiveness()` - 评估技能效果
- `recommend_best_practices()` - 推荐最佳实践
- `get_experience_stats()` - 获取经验统计
- `get_skill_ranking()` - 获取技能排名

**数据库存储**：

- 使用 SQLite 数据库（`data/experience_knowledge.db`）
- 三张表：`experience_records`、`skill_evaluations`、`recommendations`
- 支持索引优化，提高查询性能

### 2. API 端点

**文件**：`neurova/api/endpoints/experience_knowledge_api.py`

**提供的 API**：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/experience-knowledge/records` | 添加经验记录 |
| GET | `/api/v1/experience-knowledge/records/{skill_name}` | 获取经验记录 |
| POST | `/api/v1/experience-knowledge/similar` | 查找相似经验 |
| GET | `/api/v1/experience-knowledge/evaluate/{skill_name}` | 评估技能效果 |
| GET | `/api/v1/experience-knowledge/recommendations/{skill_name}` | 获取推荐 |
| GET | `/api/v1/experience-knowledge/stats` | 获取统计信息 |
| GET | `/api/v1/experience-knowledge/ranking` | 获取技能排名 |
| GET | `/api/v1/experience-knowledge/health` | 健康检查 |

### 3. 单元测试

**文件**：`tests/test_experience_knowledge_base.py`

**测试覆盖**：

- 添加经验记录
- 获取经验记录（含过滤条件）
- 查找相似经验
- 技能效果评估
- 最佳实践推荐
- 经验统计
- 技能排名
- 空技能统计

**测试结果**：11 个测试全部通过

## 使用方法

### 1. 基本使用

```python
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
from neurova.skills.models import ExperienceRecord
from datetime import datetime

# 创建经验知识库实例
ekb = ExperienceKnowledgeBase()

# 创建经验记录
exp = ExperienceRecord(
    skill_name="my-skill",
    context={"user_input": "分析代码", "topic": "code-analysis"},
    result={"output": "分析完成"},
    success=True,
    timestamp=datetime.now().isoformat(),
    feedback="效果好"
)

# 添加经验记录
record_id = ekb.add_experience_record("my-skill", exp)

# 获取经验记录
records = ekb.get_experience_records("my-skill", limit=10)

# 评估技能效果
evaluation = ekb.evaluate_skill_effectiveness("my-skill")

# 获取推荐
recommendations = ekb.recommend_best_practices("my-skill")

# 关闭连接
ekb.close()
```

### 2. API 调用示例

```bash
# 添加经验记录
curl -X POST <http://localhost:8000/api/v1/experience-knowledge/records> \
  -H "Content-Type: application/json" \
  -d '{
    "skill_name": "my-skill",
    "context": {"user_input": "分析代码"},
    "result": {"output": "分析完成"},
    "success": true,
    "timestamp": "2026-05-13T22:00:00"
  }'

# 获取经验记录
curl <http://localhost:8000/api/v1/experience-knowledge/records/my-skill?limit=10>

# 评估技能效果
curl <http://localhost:8000/api/v1/experience-knowledge/evaluate/my-skill>

# 获取推荐
curl <http://localhost:8000/api/v1/experience-knowledge/recommendations/my-skill>
```

## 技术要点

### 1. 数据库设计

- **experience_records** 表：存储所有经验记录，包含上下文、结果、成功标志、时间戳等
- **skill_evaluations** 表：存储技能评估结果，支持多种评估类型
- **recommendations** 表：存储生成的推荐，支持上下文哈希索引

### 2. 效果评估算法

效果评估基于以下指标：

- **成功率**：成功记录数 / 总记录数（权重 50%）
- **执行时间**：平均执行时间，越低越好（权重 30%）
- **趋势**：最近表现 vs 历史表现（权重 20%）

综合评分转换为评价：`excellent` (>0.8)、`good` (>0.6)、`average` (>0.4)、`poor` (≤0.4)

### 3. 相似度计算

相似度计算考虑以下因素：

- **用户输入重叠**：关键词重叠率（权重 60%）
- **话题匹配**：话题是否相同（权重 30%）
- **成功率加权**：成功记录优先级更高（权重 10%）

### 4. 智能推荐

推荐系统基于以下逻辑：

- **评估结果推荐**：根据效果评估结果提供使用建议
- **成功模式推荐**：提取成功经验中的常见模式
- **上下文相关推荐**：基于当前上下文推荐相似经验

## 与现有代码的集成

### 1. 与 ExperienceCaller 的关系

现有的 `ExperienceCaller` 类（经验调用系统）是一个基础实现，使用文件存储经验记录。

新的 `ExperienceKnowledgeBase` 类是一个增强实现，使用数据库存储，并提供更强大的功能。

**建议**：逐步迁移现有代码，使用 `ExperienceKnowledgeBase` 替代 `ExperienceCaller`。

### 2. 与 SkillService 的集成

`SkillService` 可以在技能执行后，调用 `ExperienceKnowledgeBase` 添加经验记录，实现经验的自动积累。

### 3. 与 API 的集成

已在 `neurova/api/app.py` 中注册路由，所有 API 端点可直接访问。

## 后续优化方向

1. **性能优化**：
   - 添加更多索引
   - 实现缓存机制
   - 支持批量操作

2. **功能增强**：
   - 实现更复杂的相似度算法（如向量相似度）
   - 添加机器学习模型进行效果预测
   - 支持经验记录的标签和分类

3. **API 增强**：
   - 支持更复杂的查询条件
   - 添加批量操作接口
   - 实现实时推送（WebSocket）

## 总结

经验知识库模块已完整实现，包括：

✅ ExperienceKnowledgeBase 核心类  
✅ 数据库存储（SQLite）  
✅ 效果评估系统  
✅ 智能推荐功能  
✅ RESTful API 接口  
✅ 单元测试（11 个测试，100% 通过）

该模块为 Neurova 提供了统一的经验管理功能，是四层存储架构的重要组成分。
