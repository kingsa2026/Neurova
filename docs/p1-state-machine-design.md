# P1 升级方案：Agent 执行状态机（设计文档）

> 状态：设计评审稿（未实施）｜ 上游：docs/openmanus-comparison.md P1 ｜ 2026-08-29

## 一、为什么需要（实测驱动的三个痛点）

1. **异常穿透无兜底**：`ChatPipeline.execute`（chat_pipeline.py:247-268）7 步线性执行、**无 try/except**——任何一步抛异常直接穿透到 console 的 `run_chat` except。流式路径的兜底只返回 `{"text": "Error: ..."}`，**不产生 chunk 事件 → 用户看到空回复**（2026-08-29 限流事故的完整链路）。
2. **错误处理重复且不一致**：console.py 有两处 `Console chat error` 兜底（326 非流式 / 384 流式），各自维护。
3. **stop 是纯占位**：`/console/chat/stop`（console.py:432-435）直接返回 "Chat stopped"，什么都不停——没有取消语义的承载结构。

## 二、现状关键事实（设计依据，均已代码核实）

| 事实 | 位置 | 对设计的约束 |
|---|---|---|
| Agent 是**进程级共享单例**（`app_state["agents"]`），多会话并发共享 | api/deps.py:97 | **状态机不能挂 Agent**——并发请求会互相踩状态 |
| ChatPipeline 同样共享 | agent.chat_pipeline | 同上 |
| ChatContext 每请求新建，已有 13 个中间状态字段 | chat_pipeline.py:64-84 | 状态机的天然落点 |
| `execute()` 7 步线性、无异常包裹 | chat_pipeline.py:247 | 状态包裹的插入点 |
| `_init_agent_state` 每请求重置 agent 级临时状态（`_tool_messages_list` 等） | chat_pipeline.py:333-341 | **既有并发隐患**（两请求互覆），阶段 4 处理 |
| `_sync_event` 广播基建现成（AGENT_THINKING 已在发） | chat_pipeline.py:287 | 状态广播零新增基建 |
| event_emitter 已贯通到 SSE | console.py | 前端展示状态变化的通道 |
| stop 端点占位 | console.py:432 | 阶段 3 的实装目标 |

**与 OpenManus 最本质的差异**：OpenManus 是"每任务一个 Agent 实例"，`self.state` 挂实例没问题；Neurova 是"单 Agent 服务多请求"——**照搬实例状态机是并发 bug**。这是本方案的核心决策点。

## 三、目标设计

### 3.1 状态归属与形态

```python
# neurova/agent/pipeline_state.py（新模块，~120 行）
class PipelineState(str, Enum):
    PENDING = "PENDING"      # 已接收未开始
    RUNNING = "RUNNING"      # 执行中（stage 字段细分阶段）
    FINISHED = "FINISHED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"  # 阶段 3 实装取消时启用

class PipelineStage(str, Enum):   # RUNNING 下的细粒度阶段
    ACTIVITY = "activity"
    PRE_CHECKS = "pre_checks"
    RETRIEVAL = "retrieval"
    EVOCATE = "evocate"
    LLM_CALL = "llm_call"
    POST_PROCESSING = "post_processing"
    SYNC = "sync"

class PipelineRun:                # 挂 ctx（请求级），非 Agent
    state: PipelineState
    stage: PipelineStage
    transitions: List[Transition]   # 转移日志（含 fallback 原因、错误分类）
    error: Optional[ErrorInfo]      # 分类错误（对接 P2 的 LLMError 族）
    cancel_event: asyncio.Event     # 阶段 3 的取消令牌

    def stage_context(self, stage) -> AsyncContextManager
    # 进入：state=RUNNING, stage=X, 记录转移
    # 异常：state=ERROR + error 分类 + 广播 + 上抛（OpenManus state_context 语义）
    # 正常退出：恢复并进入下一 stage
```

### 3.2 状态转移图

```
PENDING → RUNNING ─┬→ FINISHED（正常）
     │             ├→ ERROR（异常上抛，携带分类错误）
     │             └→ CANCELLED（阶段 3：cancel_event 置位）
     └→（repeat 请求到达同一 ctx？不存在——ctx 每请求新建）
```

RUNNING 内 stage 切换不改变 state，只更新 stage + transition_log（区别于 OpenManus 的粗粒度状态，Neurova 的管线步骤天然提供更细的可观测性）。

### 3.3 execute 的目标形态

```python
async def execute(self, ctx: ChatContext) -> Dict[str, Any]:
    run = ctx.pipeline_run = PipelineRun()
    try:
        async with run.stage_context(PipelineStage.ACTIVITY):
            await self._step_activity_tracking(ctx)
        async with run.stage_context(PipelineStage.PRE_CHECKS):
            await self._step_pre_llm_checks(ctx)
        # ... 其余 5 步同理
    except LLMError as e:                      # P2 分类错误
        run.fail(e)                            # ERROR 态 + 分类信息
        ctx.result = {"text": ..., "error": run.error.to_dict()}  # 结构化错误进结果
        return ctx.result                      # 不再裸抛——由状态机决定收尾
    except Exception as e:
        run.fail(e)
        raise                                  # 非分类错误仍上抛
    finally:
        await run.finalize(ctx)                # 广播终态
```

console 的两处重复 except 收敛为信任 `ctx.result["error"]`（流式路径补一个 error chunk——空回复问题根治）。

### 3.4 fallback 的结构化（P2 的收口）

`_call_agent_loop` 的 fallback 决策（现在只有 logger.warning）记录进 `run.transitions`：`{stage: "llm_call", action: "fallback_to_legacy", reason: str}`。P2 已保证供应商错误不 fallback；状态机把"何时降级、为何降级"变成可查询的转移日志而非日志文件里的行。

## 四、分阶段实施（每阶段独立可交付）

| 阶段 | 内容 | 工作量 | 行为变化 |
|---|---|---|---|
| **1. 纯加法** | pipeline_state.py 新模块；ctx 挂 PipelineRun；6 步 stage_context 包裹；execute 顶层兜底 + 结构化错误；transition_log | ~1 天 | **零行为变化**（158 测试全绿为证） |
| 2. 可观测 | 状态/阶段变化经 _sync_event 广播（新 EventType.PIPELINE_STATE）；console SSE 透出；前端可展示管线进度 | ~半天 | 新增事件，无破坏 |
| 3. 取消实装 | cancel_event 贯穿：loop 轮次间、检索步后检查；stop 端点置位并返回真实结果；CANCELLED 收尾 | ~半天 | stop 从占位变真实 |
| 4. 并发隐患修复 | `_init_agent_state` 的 agent 级临时状态（_tool_messages_list/_current_reasoning）迁移到 ctx（触碰蜂群/tool_executor 多处消费方） | 1-2 天，单独评估 | 有行为面，需独立回归 |

## 五、风险清单

1. **包裹侵入面**：6 步全包 → 阶段 1 必须纯加法（不改任何 step 内部逻辑），158 个既有测试全绿是行为不变的验收线。
2. **事件重复**：PIPELINE_STATE 与既有 AGENT_THINKING/AGENT_TOOL_RESULT 语义重叠 → 阶段 2 做事件映射而非叠加。
3. **蜂群子 Agent**：SwarmManager 复用 ChatPipeline——ctx 级状态天然按请求隔离 ✓，但子 Agent 的事件可能穿透父 ctx 的 emitter（已有行为），状态广播需带 agent 维度区分。
4. **取消的原子性**：阶段 3 的 cancel 只能在"安全点"生效（工具执行中不可中断，sqlite 写入不可中断）——语义是"软取消"，文档必须明示。
5. **LLMError 收尾路径**：execute 捕获 LLMError 后返回结构化错误而非上抛——console 侧 run_chat 的 except 变死代码，需同步清理（两处重复兜底的收敛正是目标）。

## 六、测试策略

- 阶段 1 新增：状态机单测（转移/异常转 ERROR/恢复）；execute 注入异常 → ERROR 态 + ctx.result["error"] 断言；全量 158 回归全绿
- 阶段 2：广播事件断言（fake sync_manager 收到 PIPELINE_STATE 序列）
- 阶段 3：loop 轮次间取消（FakeLLM 两轮间置位 cancel_event → CANCELLED 收尾）；stop 端点集成测试
- 阶段 4：并发双请求 → _tool_messages_list 互不污染（当前会失败，作为修复的验收测试）

## 七、结论与建议

P1 的价值在**结构收口**：把散落在 console/pipeline/loop 三层的异常兜底、降级决策、未来取消，统一到一张请求级状态转移图上。核心决策是**状态挂 ctx 不挂 Agent**（并发安全），这与 OpenManus 的差异是本质性的，也是不能照搬其实现的根本原因。

建议顺序：先做阶段 1（纯加法，零风险收口错误路径），阶段 2 顺手（前端可见收益明显），阶段 3 前先确认用户对 stop 的实际需求，阶段 4 单独立项。
