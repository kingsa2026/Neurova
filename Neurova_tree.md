# Neurova 项目文件树说明

> 最后更新：2026-06-10 | 负一屏推送通知中心集成

---

## 通知中心模块 (neurova/notifications/)

```
neurova/notifications/
├── __init__.py               # 模块导出入口
├── negative_screen.py        # 负一屏推送核心模块
│   ├── PushResult            # 推送结果数据类
│   ├── NegativeScreenConfig  # 用户级配置数据类（含 authCode 脱敏）
│   ├── NegativeScreenConfigManager  # 配置管理器（文件隔离、线程安全）
│   ├── NegativeScreenPusher  # 推送执行器（async aiohttp）
│   └── create_*() 工厂函数
└── manager.py                # 通知管理器（集成负一屏推送）
    ├── Notification          # 通知数据类（含推送状态追踪）
    ├── NotificationManager   # 通知管理器（任务完成自动推送）
    └── get_notification_manager() 全局单例
```

**功能说明：**
- 用户级 authCode 隔离：每个用户独立配置，存储在 `data/negative_screen/{user_id}.json`
- 任务完成自动推送：`notification_type == "task_completed"` 时自动触发
- 推送统计：追踪成功/失败/推送率
- 线程安全：使用 `threading.RLock` 保护共享状态

---

## 负一屏设置 API (neurova/api/endpoints/negative_screen_settings.py)

```
neurova/api/endpoints/negative_screen_settings.py
├── GET  /api/v1/negative-screen        # 获取用户配置
├── PUT  /api/v1/negative-screen        # 更新用户配置
├── POST /api/v1/negative-screen/test   # 测试推送
└── DELETE /api/v1/negative-screen      # 删除配置
```

**路由前缀：** `/api/v1/negative-screen`（独立于 `/api/v1/settings/`，避免 `/{key}` 通配冲突）

---

## 前端组件 (NeurUI/src/components/NegativeScreenSettings.vue)

```
NeurUI/src/components/NegativeScreenSettings.vue
├── Auth Code 输入（密码字段 + 获取步骤说明）
├── 启用/禁用开关
├── 推送 URL 配置
├── 测试推送按钮（含成功/失败反馈）
├── 推送统计展示（总数/已推送/失败/成功率）
└── 保存/删除配置按钮
```

**集成位置：** `NeurUI/src/pages/SettingPage.vue` → 负一屏推送 tab

---

## API 端点注册 (neurova/api/endpoints/__init__.py)

```python
("neurova.api.endpoints.negative_screen_settings", "/v1/negative-screen", "Negative Screen Settings API")
```

---

## 通知 API 扩展 (neurova/api/endpoints/notifications.py)

```python
@router.get("/push-statistics")  # 获取推送统计
```

---

## 测试文件 (tests/unit/test_negative_screen_integration.py)

```
tests/unit/test_negative_screen_integration.py (24 tests)
├── TestNegativeScreenConfig (6 tests)         # 配置数据结构
├── TestNegativeScreenConfigManager (7 tests)   # 配置管理器（用户隔离、线程安全）
├── TestNegativeScreenPusher (4 tests)          # 推送器（初始化、成功、无authCode、禁用、网络错误）
├── TestNotificationManagerIntegration (2 tests) # 通知管理器集成
├── TestNegativeScreenSettingsAPI (3 tests)     # 设置 API 端点
└── TestPostChatPipelineIntegration (1 test)    # RSI 结果推送
```

---

## 数据流

```
用户设置 authCode → NegativeScreenConfigManager.save_config()
→ 添加任务完成通知 → NotificationManager.add_notification()
→ _schedule_negative_screen_push() → daemon thread
→ NegativeScreenPusher.push_task() → aiohttp POST
→ 华为负一屏 API → 推送结果 → 更新通知状态
```

---

## 关键设计决策

1. **路由隔离**：使用 `/v1/negative-screen` 独立前缀，避免与 `/v1/settings/{key}` 通配冲突
2. **用户隔离**：每个用户独立 JSON 文件，文件名使用 `user_id` 安全化处理
3. **异步推送**：daemon 线程中运行 asyncio event loop，不阻塞主流程
4. **容错处理**：aiohttp 未安装时优雅降级，返回错误信息
5. **测试策略**：mock `_execute_push` 而非 `aiohttp.ClientSession.post`，避免依赖安装
