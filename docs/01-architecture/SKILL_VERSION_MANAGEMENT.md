# 技能版本管理功能更新说明

## 📋 更新概述

为 Neurova 项目添加了完整的技能版本管理功能，支持技能版本检测、自动更新、通知管理和版本同步。

**更新日期**: 2026-05-14  
**更新人员**: AI Assistant  
**相关文档**: `docs/API_CALLING_SPECIFICATION.md`

---

## 🎯 功能特性

### 1. 版本检测
- 系统重启时自动检测技能市场的新版本
- 支持手动触发版本检查
- 比较当前版本和最新版本

### 2. 通知机制
- **公共技能池** → 提醒管理员手动更新
- **用户专属技能池** → 通知用户手动更新
- **Agent 专属技能池** → 自动更新（无需通知）

### 3. 自动更新
- Agent 专属技能池中的技能自动更新到最新版本
- 支持手动触发 Agent 技能的自动更新

### 4. 版本同步
- 公共池更新后自动同步到用户/Agent 专属技能池
- **补充规则**：Agent 技能在用户专用池中且不包含在公共技能池中 → 用户更新后自动同步 Agent 技能

### 5. 通知管理
- 获取用户的更新通知列表
- 标记通知为已读
- 支持只查看未读通知

---

## 📁 文件变更

### 新增文件

#### 后端

1. **`neurova/skills/version_manager.py`** - 技能版本管理器
   - `VersionInfo` - 版本信息数据类
   - `UpdateNotification` - 更新通知数据类
   - `SkillVersionManager` - 版本管理器类
     - `check_version_updates()` - 检查单个技能版本
     - `check_all_skills_on_startup()` - 系统启动时检查所有技能
     - `auto_update_agent_skills()` - 自动更新 Agent 技能
     - `sync_from_public_pool()` - 从公共池同步更新
     - `get_notifications()` - 获取通知列表
     - `mark_notification_read()` - 标记通知已读
     - `_sync_user_skill_to_agents()` - **补充规则实现**

2. **`neurova/api/endpoints/skill_version_api.py`** - 版本管理 API 路由
   - `POST /api/v1/skill-versions/check` - 检查技能版本
   - `POST /api/v1/skill-versions/check-all-on-startup` - 启动时的批量检查
   - `GET /api/v1/skill-versions/notifications` - 获取通知列表
   - `PUT /api/v1/skill-versions/notifications/{id}/read` - 标记通知已读
   - `POST /api/v1/skill-versions/auto-update-agent-skills` - 自动更新 Agent 技能
   - `POST /api/v1/skill-versions/sync-from-public-pool` - 从公共池同步
   - `POST /api/v1/skill-versions/manual-update` - 手动更新技能

#### 前端

3. **`neurova-ui/src/api/types/SkillVersion.ts`** - 类型定义
   - `VersionInfo` - 版本信息
   - `UpdateNotification` - 更新通知
   - `VersionCheckRequest` - 版本检查请求
   - `UpdateSkillRequest` - 更新技能请求
   - `BatchVersionCheckResult` - 批量检查结果
   - `NotificationsResult` - 通知列表结果
   - `AutoUpdateResult` - 自动更新结果

4. **`neurova-ui/src/api/modules/skillVersion.ts`** - API 模块
   - `checkVersion()` - 检查版本
   - `checkAllOnStartup()` - 批量检查
   - `getNotifications()` - 获取通知
   - `markNotificationRead()` - 标记已读
   - `autoUpdateAgentSkills()` - 自动更新 Agent 技能
   - `syncFromPublicPool()` - 同步公共池
   - `manualUpdate()` - 手动更新

### 修改文件

1. **`neurova/skills/__init__.py`**
   - 添加 `SkillVersionManager`、`VersionInfo`、`UpdateNotification` 的导出

2. **`neurova/api/app.py`**
   - 在 `_initialize_components()` 中初始化 `SkillVersionManager`
   - 在 `_register_routes()` 中注册版本管理路由
   - 在 `_on_startup()` 中调用版本检查

3. **`neurova-ui/src/api/index.ts`**
   - 导出 `skillVersionApi` 模块

---

## 🚀 使用方法

### 后端 API 调用示例

```python
from neurova.skills.version_manager import SkillVersionManager

# 初始化
version_manager = SkillVersionManager(
    data_dir=Path("/data"),
    pool_manager=pool_manager,
    admin_service=admin_service,
)

# 检查版本更新
version_info = version_manager.check_version_updates(
    skill_id="skill-123",
    current_version="1.0.0",
    pool_type="user",
    owner_id="user-123",
)

# 系统启动时检查所有技能
updates = version_manager.check_all_skills_on_startup()

# 自动更新 Agent 技能
updated = version_manager.auto_update_agent_skills("agent-123")

# 获取通知
notifications = version_manager.get_notifications(user_id="user-123")

# 标记通知已读
version_manager.mark_notification_read("notification-123")
```

### 前端 API 调用示例

```typescript
import { skillVersionApi } from '../api';

// 检查版本
const versionInfo = await skillVersionApi.checkVersion({
  skill_id: 'skill-123',
  current_version: '1.0.0',
  pool_type: 'user',
  owner_id: 'user-123',
});

// 获取通知
const result = await skillVersionApi.getNotifications(true);
console.log(`有 ${result.count} 条未读通知`);

// 标记已读
await skillVersionApi.markNotificationRead('notification-123');

// 自动更新 Agent 技能
const updateResult = await skillVersionApi.autoUpdateAgentSkills('agent-123');
console.log(`更新了 ${updateResult.count} 个技能`);
```

### HTTP API 调用示例

```bash
# 检查版本
curl -X POST http://localhost:8000/api/v1/skill-versions/check \
  -H "Content-Type: application/json" \
  -d '{
    "skill_id": "skill-123",
    "current_version": "1.0.0",
    "pool_type": "user",
    "owner_id": "user-123"
  }'

# 获取通知
curl http://localhost:8000/api/v1/skill-versions/notifications?unread_only=true \
  -H "Authorization: Bearer YOUR_TOKEN"

# 标记已读
curl -X PUT http://localhost:8000/api/v1/skill-versions/notifications/notification-123/read \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## 🔄 版本同步规则

### 规则 1：公共技能池更新
- 管理员更新公共技能池中的技能
- 自动同步到所有用户/Agent 专属技能池中相同技能的副本

### 规则 2：用户专属技能更新
- 用户更新自己的专属技能池中的技能
- 如果技能 **不在** 公共池中
- **自动同步** 到该用户的所有 Agent 专属技能池

### 规则 3：Agent 专属技能更新
- Agent 专属技能池中的技能
- 系统自动检测并更新到最新版本
- 无需用户或管理员干预

---

## 📊 数据库变更

版本管理器使用以下文件存储数据：

- **`data/update_notifications.json`** - 更新通知列表
  - 存储所有用户的更新通知
  - 每个通知包含技能 ID、版本信息、读取状态等

---

## ⚙️ 配置说明

### 后端配置

版本管理器在系统启动时自动初始化：

```python
# neurova/api/app.py
app_state.version_manager = SkillVersionManager(
    data_dir=data_dir,
    pool_manager=app_state.skill_manager,
    admin_service=app_state.admin_service,
)
```

### 前端配置

前端 API 模块自动使用配置文件中的基础 URL：

```typescript
// neurova-ui/src/api/config.ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
```

---

## 🧪 测试建议

### 单元测试

1. 测试版本比较逻辑
   - 测试 `_compare_versions()` 方法

2. 测试版本检测
   - 测试 `check_version_updates()` 方法
   - 模拟技能市场 API 返回

3. 测试通知管理
   - 测试 `get_notifications()` 方法
   - 测试 `mark_notification_read()` 方法

4. 测试自动更新
   - 测试 `auto_update_agent_skills()` 方法
   - 测试 `_sync_user_skill_to_agents()` 方法（补充规则）

### 集成测试

1. 启动系统，检查是否自动执行版本检查
2. 模拟技能市场有新版本，检查是否生成通知
3. 测试用户更新技能后，是否自动同步到 Agent
4. 测试公共池更新后，是否自动同步到用户/Agent 池

---

## 📝 待完成工作

### 高优先级

1. **实现技能市场 API 调用**
   - 在 `_fetch_latest_version()` 中实现真正的 API 调用
   - 在 `_fetch_release_notes()` 中实现获取发布说明

2. **实现技能更新逻辑**
   - 在 `_update_skill()` 中实现真正的技能更新
   - 下载新版本的技能内容并更新到技能池

3. **实现获取用户 Agent 列表**
   - 在 `_get_user_agents()` 中实现获取用户所有 Agent 的逻辑
   - 可能需要调用 AgentManager 或类似服务

### 中优先级

1. **添加前端页面组件**
   - 创建版本通知中心组件
   - 创建技能更新管理页面

2. **完善通知功能**
   - 实现邮件通知
   - 实现 WebSocket 实时通知
   - 实现前端弹窗通知

### 低优先级

1. **添加版本历史记录**
   - 记录技能版本更新历史
   - 支持版本回滚

2. **添加版本比较功能**
   - 显示版本间的差异
   - 显示更新内容详情

---

## 🐛 已知问题

1. **技能市场 API 未实现**
   - 当前使用模拟数据
   - 需要对接真正的技能市场 API

2. **技能更新逻辑未实现**
   - 当前模拟更新成功
   - 需要实现真正的技能下载和更新逻辑

3. **获取用户 Agent 列表未实现**
   - 当前返回空列表
   - 需要实现获取用户所有 Agent 的逻辑

---

## 📚 参考资料

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Pydantic 数据验证](https://docs.pydantic.dev/)
- [Semantic Versioning](https://semver.org/)
- `docs/API_CALLING_SPECIFICATION.md` - API 调用规范文档

---

## 📞 联系方式

如有问题或建议，请联系项目维护者。

**项目**: Neurova  
**版本**: 1.0.0  
**更新日期**: 2026-05-14
