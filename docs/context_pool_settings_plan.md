# 上下文池设置API集成计划

## 目标
将上下文池参数（max_size、ttl_seconds、token_budget）封装为前端UI可调用的API，并整合进系统设置页面。

## 设计原则
1. **TDD方法**：先写测试，再实现功能
2. **深度模块**：小接口，深实现
3. **向后兼容**：不破坏现有功能
4. **用户友好**：前端UI直观易用

## API设计

### 1. 获取上下文池设置
```
GET /api/v1/context/pool-settings
```
**响应**:
```json
{
  "code": 0,
  "data": {
    "max_size": 100,
    "ttl_seconds": 3600,
    "default_token_budget": 16000,
    "model_budgets": {
      "gpt-4": 32000,
      "claude-3-opus": 200000,
      "deepseek-chat": 32000
    }
  }
}
```

### 2. 更新上下文池设置
```
PUT /api/v1/context/pool-settings
```
**请求**:
```json
{
  "max_size": 150,
  "ttl_seconds": 7200,
  "default_token_budget": 32000
}
```
**响应**:
```json
{
  "code": 0,
  "message": "上下文池设置已更新",
  "data": {
    "max_size": 150,
    "ttl_seconds": 7200,
    "default_token_budget": 32000
  }
}
```

### 3. 获取特定模型的Token预算
```
GET /api/v1/context/pool-settings/token-budget/{model_name}
```
**响应**:
```json
{
  "code": 0,
  "data": {
    "model_name": "gpt-4",
    "token_budget": 32000
  }
}
```

### 4. 测试Token预算计算
```
POST /api/v1/context/pool-settings/test-budget
```
**请求**:
```json
{
  "model_name": "gpt-4",
  "capabilities": ["TEXT", "VISION"]
}
```
**响应**:
```json
{
  "code": 0,
  "data": {
    "model_name": "gpt-4",
    "capabilities": ["TEXT", "VISION"],
    "calculated_budget": 32000,
    "explanation": "基于模型名称匹配"
  }
}
```

## 前端UI设计

### 位置
在系统设置页面添加新的标签页："上下文池设置"

### 组件
1. **基本设置卡片**：
   - 最大池大小（max_size）：滑块或数字输入框
   - TTL过期时间（ttl_seconds）：时间选择器
   - 默认Token预算：数字输入框

2. **模型预算配置卡片**：
   - 模型列表表格（模型名称、Token预算）
   - 添加/编辑/删除模型预算
   - 测试预算计算按钮

3. **实时预览卡片**：
   - 当前池状态（上下文数量、过期数量）
   - 内存使用情况
   - 缓存命中率

## 实现步骤

### Phase 1: 后端API实现（TDD）
1. 编写API测试
2. 实现API端点
3. 集成到上下文池核心

### Phase 2: 前端UI实现
1. 创建设置组件
2. 集成到系统设置页面
3. 添加实时预览

### Phase 3: 集成测试
1. 端到端测试
2. 性能测试
3. 用户验收测试

## 文件清单

### 后端文件
1. `neurova/api/endpoints/context_pool_settings.py` - 新API端点
2. `neurova/context_pool.py` - 修改以支持动态配置
3. `tests/unit/test_context_pool_settings_api.py` - API测试

### 前端文件
1. `neuUI/src/components/ContextPoolSettings.vue` - 设置组件
2. `neuUI/src/api/modules/context-pool.ts` - API模块
3. `neuUI/src/pages/SettingPage.vue` - 集成到设置页面

## 风险与缓解

### 风险1：性能影响
- **缓解**：添加缓存，异步更新

### 风险2：配置冲突
- **缓解**：版本控制，冲突检测

### 风险3：用户体验
- **缓解**：实时预览，撤销功能

## 成功标准
1. 所有API测试通过
2. 前端UI直观易用
3. 性能无显著下降
4. 向后兼容性保持