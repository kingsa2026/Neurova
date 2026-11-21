# 参照系 ad（LobeHub）LLM 接入与自适应路由追平实施方案

- 日期：2026-11-22
- 来源：《reference_ad_llm_access_and_adaptive_routing_teardown_2026-11-22.md》（十轴专项细拆：LobeHub 86.0 vs Neurova 70.0 /100）与总报告 D7 维（L 9.5 / N 5.5 /10）
- 目标：把专项暴露的落后轴补到"结构对齐、策略自主"，重点攻**路由决策（轴 4，5.5→8+）**与**协议/计量短板（轴 2/7）**；容错轴（5）本仓已反超，只做语义表补全不重构
- 范围：`neurova/llm/`（providers/multi_model_client/llm_router/error_mapping/rate_limiter）与 `agent_core` 接线点；不动活水池/记忆/编排域
- 状态：**备稿待拍板**（D-R1…D-R5 五项）；未拍板不动码
- 复评机制：每批完成按专项十轴同卡复测；三批全完后总复评目标=专项总分 70.0→80.0+，轴 4 ≥8.0

## 0. 总原则

1. **策略自主，框架可借**：对方路由策略在云侧闭源（OSS `routers=[]`），只借其结构与语义（attempt 生命周期/错误分类/hold 换路），实现全部本仓自主写，不引其命名与代码。
2. **新逻辑落新模块**：`multi_model_client.py` 已是热点文件，attempt/错误语义/能力选型一律落独立模块（建议 `neurova/llm/routing/`），旧文件只做接线，避免重演巨型文件债。
3. **主链路灰度**：能力选型与 attempt 化先在"未显式指定模型"的请求上生效（与现 auto_failover 同边界），显式钉死 provider/model 的行为不变——保证存量 agent 零迁移。
4. **治理不绕行**：任何自动执行/切换路径仍过既有治理、审批、配额闸。

## 1. 批一 P0：路由与容错核心（对齐专项轴 4/5）

### R1 错误分类路由语义表（轴 5 补全）

- 现状：`is_fallback_eligible` 已有雏形（`multi_model_client.py:837-840`），错误归一五类在 `providers/error_mapping.py`；但"哪些错误该切/该停"未成封闭集（如上下文超限不该切、限流该切、鉴权该切、内容审查该停）。
- 改法：新建 `neurova/llm/routing/error_policy.py`，声明式 specs：错误类别/HTTP 状态/错误码/文案特征 → `FALLBACK | STOP | RETRY_SAME`；`auto_failover` 与流式切换都改读该单源；覆盖对方已验证的语义（401/403/404/408/409/423/425/429→切；context_length_exceeded/invalid_request/content_filter→停）并按本仓五类错误归一对齐。
- 红绿判据：先写失败测试——逐错误样本断言决策（红灯：现逻辑对 context_window_exceeded 误切/对 429 不切等）；实现后全绿。
- 验收：live-verify 用假 LLM 桩依次返回各错误类，断言切换/停止行为与语义表一致。
- 影响面：`multi_model_client.py` chat/stream 两处切换判定改读新模块；无 API 面变化。

### R2 attempt 级 fallback 生命周期 + 流式 hold 换路（轴 4 核心）

- 现状：`auto_failover` 为顺序尝试（`multi_model_client.py:778-847`），流式 max_switches=5（:1144-1157）但无 attempt 概念、无"首可见输出前可换路"语义——半截输出可能已外泄才失败。
- 改法：新建 `neurova/llm/routing/attempt.py`：`AttemptState`（prepare→should_continue→on_success/on_error；outcome ∈ completed|empty|interrupted|cancelled|failed）；流式侧引入 **hold 缓冲**——首段可见 token 落地前，provider 异常/空响应/静默看门狗触发都允许无声换下一个候选；首段已外泄后仅能标记 interrupted 走上层续跑协议。非流式同步获得 attempt 语义。
- 红绿判据：红灯=桩 provider 首字前挂断/返回空，现实现把错误或空串给了消费方；绿灯=换路后消费方拿到完整输出且 attempt 轨迹可查（每次尝试的 provider/model/outcome 落台账）。
- 验收：live-verify 真后端挂两个桩 provider（一坏一好），全链路断言输出正确、台账含两次 attempt。
- 影响面：`multi_model_client.py` chat/chat_stream；attempt 轨迹进现有 usage/运行台账（不新造第二套账）。

### R3 能力驱动选型进主聊天链路（轴 4）

- 现状：`llm_router.select_model` 已有 10 种 RequestType+能力过滤+(-priority, response_time, -weight) 排序+429 暂停过滤（`llm_router.py:189-277`），但主聊天链路静态钉死，能力匹配只在视觉旁路生效（`llm_routing_overlay.py:91`）。
- 改法：`_resolve_call_model`/`_get_client_for_request` 在**未显式指定模型（auto）**时改走 llm_router：按本轮需求能力（vision 轮 ContextVar、工具调用、长上下文估算、结构化输出）过滤候选，再按优先级/响应时间/健康度排序；显式钉死行为不变。健康度数据源用既有 `_mark_provider_health` 回写。
- 红绿判据：红灯=auto 请求遇主模型无 vision 能力时视觉轮失败；绿灯=自动改选 vision 可用模型且显式配置请求不受影响。
- 验收：live-verify 桩目录内一家有 vision 一家没有，视觉轮自动落到有的一方。
- 影响面：agent_core 接线点 + llm_router（补健康度输入）；无配置迁移。

## 2. 批二 P1：目录、流式与计量（对齐专项轴 2/3/6/7）

### R4 流事件内部归一（轴 6）

- 现状：流式回调只有内容 chunk + stream_status（silence/retry_status），reasoning/tool_calls/usage 各散在字段。
- 改法：新建 `neurova/llm/routing/stream_events.py` 定义最小事件集（text/reasoning/tool_calls/usage/stop/error/status），内部生成器统一产出，SSE 出口与台账消费改读事件流；**不追求对方 15 类全量**，按本仓消费方实际需要扩。
- 红绿判据：三 provider 桩（openai 兼容/anthropic/gemini）流式输出归一后事件序列一致。
- 验收：live-verify 真后端流式对话，前端无感（SSE 外部契约不变）。

### R5 定价单元体系 + providerReportedCost 透传（轴 7）

- 现状：静态 `PRICE_TABLES`（含 cache 单价），未计价记 0 并告警；聚合商上报成本未消费。
- 改法：价目结构升级支持 tiered 阶梯与 cache_read/cache_write 细分；OpenRouter 等聚合商 usage.cost 透传优先于本地计算；成本落账口径不变（user_id+agent_id）。
- 红绿判据：阶梯价样例单测（低/高段分别计价）；透传优先级单测。
- 验收：live-verify 用 OpenRouter 桩返回 usage.cost，台账成本与上报值一致。

### R6 usage 缺失诊断（轴 7）

- 现状：网关缺 usage 时 tiktoken 估值标 estimated（不造假），但无缺失定位信息。
- 改法：estimated 记录附 diagnostics（哪个阶段发现缺失/末次收到 usage 的 chunk 序号），进运行台账。
- 红绿判据：缺 usage 桩→台账含 diagnostics；正常桩→无。

### R7 能力位显式化进目录与路由（轴 3）

- 现状：capability_detector 真实探测 8 项并缓存，但目录展示与路由过滤未统一消费同一能力位。
- 改法：ModelInfo.capabilities 与 llm_router 候选过滤共用同一来源（探测值>预埋档案>名称推断），管理端模型列表透出能力位。
- 红绿判据：探测结果变更后路由过滤与目录展示同步变化（同源断言）。

## 3. 批三 P2：边界收口（对齐专项轴 1/8/9/10）

### R8 base_url 出站 allowlist（轴 9 待核实项收口）

- 现状：用户可控 base_url 无出站白名单（专项轴 9 标注待核实）。
- 改法：管理端可选启用出站域名策略（默认关，admin 可配 allowlist/仅私网禁用策略），复用 ssrf 思路作用于 llm 出站客户端构造点。
- 红绿判据：allowlist 开启时非名单 base_url 建客户端即拒；默认关时行为不变。

### R9 ollama 运行面原生分支（轴 8，可选）

- 现状：管理面原生（/api/tags、/api/pull），运行面走 /v1 兼容端点。
- 改法：运行面对 ollama 增原生分支（流式/拉取），仅当兼容端点探测失败时启用——以兼容优先，避免双轨漂移。
- 红绿判据：桩 ollama 兼容端点 404 时回落原生路径成功。

### R10 运行面注册表归一评估（轴 10）

- 现状：管理面 BaseProvider 与运行面 LLMAbstractProvider/ProviderRegistry 双抽象并存，后者仅注册 OpenAIAdapter。
- 改法：先评估后动手——产出归一结论（合并/保留分工），若保留则补注册表消费面文档；不在本批强行合并。

### R11 embedding API 通道（轴 2，待拍板）

- 现状：全仓无 /embeddings HTTP 调用；向量用本地 bge-small-zh（UnifiedVectorStore）。
- 改法（若拍板做）：llm 层加 embeddings 通道 + provider 适配，供活水池/记忆可选切换；默认仍本地。

## 4. 待拍板项

| 项 | 问题 | 选项与影响 | 建议 |
|----|------|-----------|------|
| D-R1 | 是否引入 channel/多渠道配置面（同 provider 多 key/多 base_url/多区域） | 建=路由能力上限高但动 provider 管理模型与前端；不建=fallback 只在既有 provider 间 | 本期以"同 provider 多渠道"最小形态试点，完整配置面后置 |
| D-R2 | 加权分流（weight 份额）是否本期做 | 依赖 D-R1；无配置面则无意义 | 后置到 D-R1 落地后 |
| D-R3 | embedding API 通道（R11）是否需要 | 本地 bge 已满足现用场景；API 通道增加凭据/成本面 | 暂缓，出现云向量需求再立项 |
| D-R4 | provider 铺量优先级 | 对方 91 家；本仓按需扩 | 优先补国产主流与聚合商（DeepSeek/Moonshot/Volcengine 等 OpenAI 兼容系，零代码成本） |
| D-R5 | 协议自动选择规则链是否需要 | 本仓 provider 少、协议分派已够 | 暂缓，随 provider 铺量再评估 |

## 5. 不照搬清单

1. 云侧闭源路由策略依赖——策略全部本仓自主实现；
2. 91 家 provider 全量铺量——按 D-R4 优先级按需扩；
3. "框架在 OSS、策略在云"的空壳模式——本仓所有落地的路由语义必须在主链路真实生效；
4. realtime 等有卡片无运行时实现的形态。

## 6. 多租户与安全影响

- provider 作用域隔离（admin 全局 / 普通用户 `providers.user-<id>.json` + agent 侧 `scope_for_owner`）在 R1–R3 全程保持：attempt/能力选型只在同 scope 候选内切换，不跨 scope 回落。
- R5 成本口径仍按 user_id+agent_id 归因；不新增租户维度（如需租户记账另立项）。
- R8 属安全收口：默认关、admin 可配，开启后拒绝点在客户端构造期（fail-closed）。
- 自动执行/切换路径不新增审批绕行：R2 换路发生在同一请求内部，审批闸在工具/治理层不受影响。

## 7. 验收门与复评

- 每卡：红灯（对现状失败的断言）→ 绿灯（最小实现）→ live-verify（真后端 9527 + 假 LLM 桩；多 provider 桩目录置于测试数据根）。
- 批验收：批一=轴 4 复测（选型链路+attempt 轨迹+hold 换路三场景）；批二=计量/流式桩全链路；批三=安全开关两态。
- 总验收：三批后按专项十轴同口径复评，目标总分 70.0→80.0+、轴 4 ≥8.0、容错轴保持 ≥9.0；复评结论回写专项文档与总报告 D7。

## 8. 执行记录

### 批一（2026-11-22，三卡全部完成，本地未推）

| 卡 | 提交 | 内容 | 验证 |
|----|------|------|------|
| R1 | f89d965dc | 错误路由语义表封闭集（neurova/llm/routing/error_policy.py）；chat/stream 双路径改读单源；auth/408/409/423/425 纳入回退（契约变更已在提交说明与改约测试中声明） | 单测 14 用例；全量 llm 946 passed 零回归；live-verify PASS（真 socket 桩 401→跨服务商切换） |
| R2 | 1f48b853a | attempt 生命周期账本（routing/attempt.py，结局五态）+ 流式空响应换路 + chat() 接线 | 单测 5 用例；全量 llm 933 passed 零回归；live-verify PASS（空流桩→切好服务商，台账 ['empty','completed']） |
| R3 | d9d5b6a20 | 能力驱动选型进主聊天链路（routing/auto_selector.py + agent_core 接线，仅 auto 请求生效）+ register_provider_from_config/sync_llm_router 透传 provider 优先级 | 单测 10 用例；全量 llm 941 passed 零回归；live-verify PASS（带工具→tool 服务商，无工具→text 服务商，真 socket 双向） |

执行中实测发现并当场修复的额外缺陷（均在对应卡提交内）：
1. **跨服务商回退候选解析断链**（R1 live-verify 暴露）：候选只在已初始化 `_clients` 里找、按模型名排除（同名模型跨服务商互顶）——改为 provider/model 复合键 + 按优先级懒建候选 + chat() 可尝试次数以已配置模型数托底。
2. **provider 优先级进不了路由表**（R3 live-verify 暴露）：`register_provider_from_config` 把 priority 硬编码为 1，选型排序退化为插入序——补 priority 透传（sync_llm_router → register_provider_from_config）。
3. 首块耗时毫秒数对瞬时桩会截断为 0——空响应判据改用「内容/推理/工具调用任一实际到达」，不以 `first_token_ms == 0` 判空。

执行中的偏离与遗留：
- R2 的「静默看门狗触发换路」**未实施**：长思考模型合法静默可达数分钟，误切风险大于收益；看门狗维持告警面，是否换路留批二结合实测数据评估。
- R2 的 CANCELLED 结局枚举已备但消费方中断路径未单独标定（GeneratorExit 经 finally 收尾，记录保持 started 态）。
- 批一验证期间发现并行会话已提交批次新增了 4 处身份读方未同步 `test_turnIdentitySingleSource` 台账（asr/minutes、cognitive_layers/dreaming、computer_use/lane_mutex、core/tool_call_journal），致 tests/unit/agent 存量 1 红——非本批引入（git log 归属已核：a16ff1c91/ead7506bf/bae2b703c），移交台账处置。
- 待拍板 D-R1…D-R5 仍开放；批二/批三未启动。

### 批二（2026-11-22，四卡全部完成，本地未推）

| 卡 | 提交 | 内容 | 验证 |
|----|------|------|------|
| R4 | 5fee4fc47 | 流分片载荷归一（routing/stream_events.py：StreamEventKind 最小词表 + chunkField 双形态取值 + chunkPayloadKinds 判类）；chat_stream 计数/空响应判定改读单源 | 12 单测；全量 llm 965 passed 零回归 |
| R5 | d6c020070 | 定价 tiers 阶梯（按 prompt_tokens 取档、超出取最高档）+ 聚合商上报成本透传（llm_client 四处 usage 构造点经 _providerReportedCost 提取 → provider_reported_cost_usd，记账优先采信、上报 0 亦尊重） | 6 单测；全量 llm 965 passed 零回归 |
| R6 | 702e11788（链重写后随 5fee4fc47 定稿） | usage 缺失诊断（reason=stream_usage_missing + chunks_seen/usage_chunks_seen，随请求归档 + _lastUsageDiagnostics 可查；真值回传时为 None） | 2 单测 |
| R7 | dd4904e75 | 端点/路由能力位同源锁约测试（三组能力位实证已同源，契约锁，无生产代码改动） | 2 单测 |

执行记录注记：
- R4 与 R6 因同文件（multi_model_client.py）交叠合并为一笔提交（原 702e11788）。
- 702e11788 首版提交信息净 LOC 声明笔误（写成 +77/−24，实为 +84/−16）——趁未推送经链重写修正（702e11788..HEAD 共 6 笔原样重建，树/作者/信息不变，CAS 落 ref）；期间并行会话在本工作区遗留的陈旧合并冲突（两份 docs）按 HEAD 侧收口（取最新已提交内容，无工作丢失）。
- tests/unit/agent 存量 1 红（身份读方台账未同步）维持移交。
- 批三（R8-R11）与 D-R1..D-R5 待拍板仍开放。
