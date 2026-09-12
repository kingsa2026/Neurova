# CUA 能力台账（证据驱动）

> R2-3（CUA 升级方案）：按"后端 × 投递路径 × 验证 oracle"登记能力边界。
> 原则（Cua action-support ledger）：**delivered 必须有 fixture 拥有的状态变化证据；
> refused 必须是精确拒绝码；gap 只表示"未证明"，不代表不可能。**
> 机械契约：`action_result.REFUSAL_CODES` / `ROUTES` 的每一项都必须以反引号登记在本文件（test_capability_ledger.py 强制）。

## 投递路径（route 词表）

| route | 语义 | 投递模式 | 后端 |
|---|---|---|---|
| `accessibility` | AX/语义动作（预留） | background | 桌面（macOS 预留） |
| `uia` | Windows UIA 语义动作（Invoke/Toggle/Expand/Legacy/Value） | background | desktop_uia |
| `app_post` | PostMessage 消息直投目标窗口（不抢焦点） | background | desktop_uia |
| `global_input` | 全局指针/键盘（**移动真实光标、抢前台**） | foreground | pyautogui 路径 |
| `playwright_role` | Playwright get_by_role 定位交互 | background | browser: playwright |
| `camofox_ref` | camofox [eN] ref 定位交互 | background | browser: camofox |
| `dom` | DOM 层导航/求值 | background | browser: 全部 |
| `remote` | 远程会话平面（RS 批次预留） | background | RS-2+ |

## 拒绝码（refusal_code 词表）

| 拒绝码 | 语义 | 触发场景 |
|---|---|---|
| `stale_generation` | 快照事实过期 | browser generation 不符；桌面快照不存在/已失效 |
| `ref_not_found` | 目标元素不存在 | (role,name) 未命中；快照 index 越界；窗口未找到 |
| `ambiguous_ref` | 匹配不唯一 | camofox 同 (role,name) 多元素——拒绝猜测，返回候选 |
| `background_unavailable` | 后台路径不可投递 | 桌面五级递降链全失败；ValuePattern 不可用且门控未开 |
| `background_occluded` | 目标被遮挡（预留） | 后台点击命中遮挡（PSR 接入后启用） |
| `permission_required` | 权限门控拒绝 | 治理 deny / 审批未通过 |
| `unsupported_method` | 平台/后端不支持 | 非 Windows 调 UIA；scrapling 调 role 交互 |
| `not_initialized` | 后端未初始化 | 浏览器/桌面后端 launch 失败 |
| `element_not_clickable` | 元素无可投递交互 | 元素无任何可用 pattern/矩形（预留） |
| `missing_params` | 必要参数缺失 | 工具参数校验失败 |
| `backend_error` | 后端执行错误 | 未分类异常（兜底，需逐步收敛到精确码） |

## 已证明矩阵（delivered = 测试断言过状态变化）

| 后端 | 动作 | 路线 | 证据 | 证明 |
|---|---|---|---|---|
| browser: playwright | dom_snapshot（预算裁剪） | dom | 行数上限断言 | tests/e2e/cua_sim/test_cua_sim_tasks.py::snapshot-budget |
| browser: playwright | click_role（button） | playwright_role | 页面状态 `__confirmed` | 同上 ::click-button |
| browser: playwright | fill_role + click_role | playwright_role | `__submitted`+值回读 | 同上 ::form-fill |
| browser: camofox | click_role ref 解析 | camofox_ref | — | gap（camofox 服务未在 CI 常驻） |
| desktop: pyautogui | click/type/scroll | global_input | — | gap（只读探测，无注入测试） |
| desktop: uia | snapshot/click_element/set_value | uia/app_post | — | gap（单测用 Fake 后端；真 UIA 冒烟待 fixture） |
