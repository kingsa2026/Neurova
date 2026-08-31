# Bug 修复报告：Provider 端点路由顺序和参数问题

## 问题描述

前端控制台报告两个错误：
1. `GET /api/v1/providers/active-model` 返回 404
2. `POST /api/v1/providers` 返回 500

## 根本原因

### 问题1：路由顺序错误
**症状**：`GET /providers/active-model` 返回 404
**根因**：FastAPI 路由匹配顺序问题
- `/{provider_id}` 定义在 `/active-model` 之前
- FastAPI 将 "active-model" 当作 `provider_id` 参数匹配
- 导致 `/active-model` 路由永远无法到达

**证据**：
- `provider.py` 第116行：`@router.get("/{provider_id}")`
- `provider.py` 第273行：`@router.get("/active-model")`
- 测试显示：`GET /providers/active-model` 返回 404

### 问题2：参数名不匹配
**症状**：`POST /providers` 返回 500
**根因**：`add_provider()` 方法参数名不匹配
- 端点调用：`provider_type=body.provider_type`
- 方法签名：`add_provider(self, name, provider, base_url, ...)`
- 参数名应为 `provider`，不是 `provider_type`

**证据**：
- `provider_manager.py` 第317行：`def add_provider(self, name: str, provider: str, ...)`
- 修复前：`provider_type=body.provider_type`（错误）
- 修复后：`provider=body.provider_type`（正确）

## 修复方案

### 1. 路由顺序修复
将静态路由移动到参数化路由之前：
```python
# 修复后顺序：
@router.post("/activate-model")  # 静态路由在前
@router.get("/active-model")     # 静态路由在前
@router.get("/{provider_id}")    # 参数化路由在后
```

### 2. 参数名修复
```python
# 修复前：
provider = provider_manager.add_provider(
    name=body.name,
    provider_type=body.provider_type,  # 错误
    base_url=body.base_url or "",
    api_key=body.api_key,
)

# 修复后：
provider = provider_manager.add_provider(
    name=body.name,
    provider=body.provider_type,  # 正确
    base_url=body.base_url or "",
    api_key=body.api_key,
)
```

### 3. 增强错误处理和日志
- 添加详细日志记录创建服务商过程
- 区分 `HTTPException` 和其他异常
- 检查 `add_provider` 方法是否存在

## 测试验证

### 新增测试（6个）
1. `test_active_model_get_returns_200` - 验证 GET /active-model 返回 200
2. `test_activate_model_post_returns_200` - 验证 POST /activate-model 返回 200
3. `test_provider_id_still_works` - 验证 /{provider_id} 仍然正常
4. `test_create_provider_calls_add_provider_with_correct_params` - 验证参数正确传递
5. `test_active_model_when_manager_unavailable` - 验证管理器不可用时的优雅降级
6. `test_list_providers_returns_empty_when_no_providers` - 验证空列表返回

### 测试结果
```
tests/unit/test_provider_route_ordering.py::TestRouteOrdering::test_active_model_get_returns_200 PASSED
tests/unit/test_provider_route_ordering.py::TestRouteOrdering::test_activate_model_post_returns_200 PASSED
tests/unit/test_provider_route_ordering.py::TestRouteOrdering::test_provider_id_still_works PASSED
tests/unit/test_provider_route_ordering.py::TestCreateProviderParams::test_create_provider_calls_add_provider_with_correct_params PASSED
tests/unit/test_provider_route_ordering.py::TestEdgeCases::test_active_model_when_manager_unavailable PASSED
tests/unit/test_provider_route_ordering.py::TestEdgeCases::test_list_providers_returns_empty_when_no_providers PASSED
```

所有 6 个测试通过，0 个 linter 错误。

## 修改文件

1. `neurova/api/endpoints/provider.py`
   - 移动路由顺序（第116行 vs 第245-289行）
   - 修复 `add_provider` 参数名（第157行）
   - 添加详细日志和错误处理

2. `tests/unit/test_provider_route_ordering.py`（新建）
   - 6 个测试用例覆盖路由顺序和参数问题

## 部署说明

**重要**：后端需要重启才能生效。旧代码可能还在运行。

1. 停止后端服务
2. 重新启动后端：`python start.py --backend`
3. 测试前端功能：
   - 访问模型管理页面
   - 尝试创建新服务商
   - 检查活跃模型显示

## 预防措施

1. **路由设计原则**：静态路由必须定义在参数化路由之前
2. **参数验证**：确保 API 端点参数与后端方法签名匹配
3. **测试覆盖**：为所有 API 端点添加路由顺序测试
4. **日志记录**：关键操作添加详细日志，便于调试

## 相关文档

- FastAPI 路由文档：https://fastapi.tiangolo.com/tutorial/first-steps/
- 项目架构：CONTEXT.md
- 测试指南：AGENTS.md

---

**修复时间**：2026-06-14 12:05
**修复人员**：AI Assistant
**测试状态**：通过
**部署状态**：待重启后端