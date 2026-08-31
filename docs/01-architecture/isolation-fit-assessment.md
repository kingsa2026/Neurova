# 三层隔离匹配性评估（新增模块 + 既有链路复核）

> 三层 = (agent_id, neuser_id, user_id)；机制契约 = ContextVar 请求作用域
> （set_request_scope/request_scope，绑定请求上下文，不改共享单例状态）
> ｜ 2026-08-30 ｜ 全部经代码核实

## 一、总览

| 模块/链路 | 隔离状态 | 结论 |
|---|---|---|
| MemoryManager（记忆主链） | ✅ ContextVar 作用域 + 三元组 WHERE + 复合索引 | 匹配（契约完好） |
| 会话文件（SessionManager） | ⚠️ sessions/{agent_id}/ 单层；user_id 仅 DB 层字段 | 部分匹配（遗留项） |
| 肌肉记忆 MuscleMemory | ⚠️ 按 agent_id 存储目录；**无 user_id 维度** | 部分匹配（见 §3.2） |
| 计划工具 PlanStore | ✅ 已修复（2026-08-30）：归属 (agent_id, user_id) 二维主键，活跃指针按归属隔离，旧库自动迁移 | 匹配 |
| Web Reach（web_reach） | ✅ 无状态读取，不产生用户数据；SSRF 边界 | 匹配（天然无归属） |
| 沙箱执行（exec_sandbox/Docker） | ✅ 无状态；命令经治理预检带 user_id | 匹配 |
| 治理闭环（_governance_precheck） | ✅ user_id 进 evaluate | 匹配 |
| ToolRouter / ToolEngine | ✅ execute 带 agent_id/user_id 透传 | 匹配 |
| 工具执行器（_execute_builtin_tool） | ⚠️ 内置工具多数不感知用户身份（纯函数型可接受） | 部分匹配 |
| console /chat | ✅ JWT user_id 进 session create + metadata | 匹配 |

## 二、匹配良好项（契约未破坏）

1. **ContextVar 机制契约完好**：`set_request_scope`/`request_scope` 是唯一注入入口；`neuser_id/user_id` 只读 property 未被任何新代码触碰；deps.py 的注入点（`get_memory_manager`）在每次请求完整重设两层。
2. **新模块 web_reach 天然无归属问题**：全部是无状态互联网读取（V2EX/RSS/Jina/yt-dlp），不产生需要隔离的持久数据；唯一外呼边界已由 SSRF 网段表把守。
3. **沙箱**：治理 SANDBOX 判定从 `tool_executor._governance_precheck` 进入，user_id 经 `self._agent_identity()[0]` 传入 evaluate——Docker/平台后端切换不改变这条链。
4. **肌肉记忆的消费端**（ToolMemoryIntegration）不直接查询用户身份，其输入是"用户输入文本"，条目按 agent_id 存储目录隔离（见 §3.2 的讨论）。

## 三、缺口与风险（按严重度）

### 3.1 【中】会话文件单层目录（既有遗留，非本轮引入）

`sessions/{agent_id}/session_*.json`——user_id 只在 repository 的 DB 层做 list 过滤，**文件层没有按用户分层**（审计遗留项清单里已记录"会话路径分层未做"）。多用户共享同一 agent 时，会话文件系统层面同权（文件级访问控制缺失）。**本轮新增代码未加剧此问题**（console /chat 的 create_session 正确传了 user_id）。

### 3.2 【中】肌肉记忆无 user 维度——语义上是"特性"而非纯缺陷

`MuscleMemory(agent_id=...)` 按智能体隔离，条目无 user_id。影响：uitest 用户喂出的工具偏好（参数快照/成功率）会被同 agent 的**其他用户**继承匹配。

- 观点 A（当前实现的选择）：肌肉记忆是"智能体的操作技能"，类似肌肉不属于某个对话者——共享合理。
- 观点 B（安全视角）：用户的查询指纹（query_fingerprint 含输入关键词）跨用户可见，有信息泄露面。
- **建议**：短期维持共享（效益优先），但条目 metadata 应记录来源 user_id 以便未来按需过滤；长期若做多租户产品化，把 storage_dir 加 user 层（`workspace/memory/muscle_memory/{user_id}/`）。

### 3.3 【高→已修复】PlanStore 无归属隔离（2026-08-30 完成，TDD 7 测试）

修复内容（tests/unit/planning/test_planning_isolation.py）：
1. plans 表主键改为 (plan_id, agent_id, user_id)；旧 schema 打开时自动迁移，存量行补 default 归属（blog_launch_plan 等已迁移验证）
2. PlanStore 全部方法归属参数化；plan_id 在归属内唯一（双用户同名计划共存）
3. set_active/get_active 活跃指针按归属隔离（用户 A 切换不再踩掉用户 B）
4. PlanningTool.run_command 接受 owner_agent_id/owner_user_id
5. **身份贯通**：console /chat 的 JWT user_id → metadata → _init_agent_state 写 agent._current_user_id → _agent_identity() 优先读请求级身份 → _execute_planning 注入归属。实测：登录用户（sub=7）经 chat 建的计划落库 (default, '7')，与 default 归属同名计划共存互不可见
6. 附带收益：治理预检、审批请求、审计日志的同一条 _agent_identity() 链路也获得了请求级登录用户身份（此前只有 config 静态身份）

### 3.4 【低】_record_tool_failure_lesson 遍历全库

agent_core 的失败降级遍历 `_l1/_l2/_l3` **全部条目**按 tool_name 清零——在肌肉记忆共享（§3.2）的现状下是正确行为（清的是 agent 级技能），若未来按用户分目录则需同步收窄作用域。记录为联动项。

## 四、结论

- **机制层（ContextVar 契约）：完好**——新模块没有一个触碰只读 property 或单例状态。
- **数据层：一个真实缺口**——PlanStore 无归属（本轮 P5 引入，多用户下计划互见+活跃指针互踩），建议下一批修复（方案见 §3.3，TDD 红测试已列）。
- **两个接受项**：会话文件单层（既有遗留，有记录）；肌肉记忆共享 agent 级（语义可辩护，留 metadata 来源以备未来）。

优先级：PlanStore 归属 > 肌肉记忆 metadata 来源标记 > 会话路径分层（与审计遗留合并处理）。
