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

### 批三（2026-11-22，R8/R10 完成 + D-R1..D-R5 拍板落定；R9/R11 缓办，本地未推）

| 卡 | 提交 | 内容 | 验证 |
|----|------|------|------|
| R8 | 3b8fbb5d9 | LLM 出站域名策略（routing/egress_policy.py）：NEUROVA_LLM_EGRESS_ALLOWLIST（host/`*.domain` 通配）设置后客户端装配点 fail-closed；默认不设置=行为不变 | 7 单测；全量 llm 1050 passed 零回归；live-verify PASS（名单内放行 / 名单外诚实失败且零出网） |
| R10 | 8e58ce862（评估结论随本记录落档，无生产改动） | 双抽象归一评估结论：**保留分工**——管理面 BaseProvider 管目录/发现/探测，运行面 LLMAbstractProvider/ProviderRegistry 管调用（现仅注册 OpenAIAdapter，消费方=triage 分诊门）；合并需重写全部 provider 适配而收益仅概念统一，不做 | 评估结论经执行记录落档 |
| D-R4 | （模板数据） | config/llm_provider_templates.json 追加 5 家：deepseek/moonshot/zhipu/siliconflow/dashscope-compatible（均 OpenAI 兼容零代码，原 11 家顺序不变，revision 1→2） | 生产装载链路实测 5 家全部接入；契约测试改约（11→16 家）通过 |

拍板结果（2026-11-22 用户交互拍板）：
- **D-R1**：核验判定**渠道配置能力本仓已齐备**——前端 ModelPage（顶栏「模型与工具」）多服务商行增删改（每行独立 base_url/api_key/models+连接测试+模型发现）、后端 provider.py 完整 CRUD+scope 隔离、路由层每行即独立回退候选（R1/R3 live-verify 实证跨服务商同名模型回退可用）。无需新建配置面。
- **D-R2**：加权分流**先观测**（用户要求核验多渠道现状后再定；现状=多服务商行+优先级/健康度排序已可用）→ **2026-11-22 用户确认多渠道配置在位，拍板落地**（执行记录见下节 D-R2）。
- **D-R3**：embedding API 通道（R11）**暂缓**（本地 bge-small-zh 已满足现用场景）→ **2026-11-22 用户重开拍板实施**（按原方案：llm 层通道+可选切换，默认仍本地；见下节收尾批）。
- **D-R4**：**补国产主流+聚合商**（已实施，见上表 D-R4 行）。
- **D-R5**：协议自动选择规则链**暂缓**（随 D-R4 铺量后再评估）。
- **R9**（ollama 运行面原生分支）：**缓办**——兼容端点路径已经三轮 live-verify 实证可用，原生分支收益仅剩管理面已有的拉取能力，避免双轨漂移。→ **2026-11-22 用户重开拍板实施**（兼容优先、/v1 探测 404 才启用原生；见下节收尾批）。
- tests/unit/agent 存量 1 红（身份读方台账未同步，a16ff1c91/ead7506bf/bae2b703c 引入）维持移交。

### D-R2 加权分流（2026-11-22，用户拍板落地，本地未推）

前置：D-R1 核验通过（渠道配置能力已齐备）→ 用户拍板执行加权分流。

| 卡 | 提交 | 内容 | 验证 |
|----|------|------|------|
| D-R2 | fe4deb521 | 同优先级组内加权分流：select_model 组内权重不全相等→按份额加权抽取（模块级 _rng 可注入），全相等保持既有确定性序（零回归）；weight=0=仅兜底（不参与日常分配，failover 链仍可达）；ProviderConfig.weight（默认 1.0，负值钳 0）+ add/update_provider 钳位存取 + provider CRUD API weight 声明位逐键透传 + sync_llm_router→register_provider_from_config 透传进路由表 | 9 用例先红（5F/4P 实测）后绿；routing 目录 73 passed；全量 llm 1059 passed 零回归（基线 1050+9）；live-verify PASS（真 socket 三桩同优先级 3:1:0，agent auto 链 4000 次选型 share=0.743 收敛 3:1，weight=0 桩零选型零流量，4000/4000 真链路 chat 成功） |

语义约定（与既有自动路由的关系）：
- **优先级仍主导**：weight 只在**同优先级组内**分配流量，不越级；
- **确定性兼容**：组内权重全相等（含全部缺省 1.0）时走既有确定性排序，不引入随机性——存量单渠道/等权配置行为逐位不变；
- **weight=0 语义**：该 provider 不参与日常分配，但仍在注册表中，其余候选全故障时经 failover 链可达；
- 与 R3 能力选型正交：能力过滤先裁掉不合格候选，加权只在合格的同优先级组内生效。

遗留清偿：weight 编辑位已进 ModelPage 配置弹窗高级区（7ed9022e2，含 embedding_model 声明位与 i18n×11）；真实流量分布观测已建——usage_history.provider_totals 聚合 + /stats/usage-overview by_provider 段（tokens 降序+份额%）+ Token 活动仪表盘「服务商流量分布」卡（份额条），配置的 weight 份额与实跑分布可对账。

### 收尾批（2026-11-22，R2 取消标定 + R9 + R11 用户拍板实施）

用户问询「R2 的 CANCELLED 结局标定、R9/R11 是不是也可以实施落地」→ 三项按原方案边界当日实施完毕。提交：**c6505ff54**（feat(llm)，含三卡生产码+三组契约测试）。

| 卡 | 内容 | 验证 |
|----|------|------|
| R2 收尾 | 消费方中断/取消标 CANCELLED：chat() 包 CancelledError、chat_stream 增 `except (GeneratorExit, CancelledError)`（重抛交还关闭协议，不 increment 不计 provider 失败）——批一遗留「CANCELLED 已备未标定」清偿 | 3 用例先红（3F 实测）后绿；live-verify：真 socket 挂起桩，流式 aclose→['cancelled']、任务取消→['cancelled']（同步 chat 经 asyncio.to_thread 装配，取消在挂起点立即生效） |
| R9 | ollama 运行面原生分支（兼容优先门控）：providers/ollama_native.py（/api/chat NDJSON 流式+非流式+工具透传）；_create_model_client 对 ollama 先探测 /v1/models——404 才落原生，其余/异常按兼容处理（fail-open），探测按 base_url 缓存 | 行为级红灯（无接线时 mmc 兜底 4 failed 实证）→绿；live-verify：原生桩 chat/stream 通、OllamaNativeClient 装配确认、compat 桩走 /v1 零 /api/chat 触碰、非 ollama 不受染 |
| R11 | embeddings 通道（默认本地）：llm/embeddings_channel.py（OpenAI 兼容 /embeddings，失败抛 EmbeddingChannelError 不回落本地防跨空间污染）+ embedding/remote_engine.py（duck-type 本地引擎消费面）+ 工厂开关（NEUROVA_EMBEDDING_PROVIDER+MODEL 双键齐备才启用） | 红灯（无工厂接线时 factory 切换 failed 实证）→绿；embeddings 消费方回归 641 passed 零失败；live-verify：env 双键→RemoteEmbeddingEngine 取桩向量、缺省→本地 ONNX 引擎不变 |

验证汇总：定向 routing+ollama+embeddings 94 passed；全量 tests/unit/llm **1080 passed 零回归**（基线 1059+21 新约）；embedding 消费方（memory_layer/tool_search/denseCosine）641 passed。

执行注记：
- 红灯形态：模块缺失类红测先收集期 ImportError、再以「有模块无接线」的行为红补证（临时 worktree@HEAD 实测 4 failed）——两段式红据多模态批先例成立。
- 真 LLMClient.chat 为同步 httpx 经 asyncio.to_thread 装配：消费方取消在 to_thread 挂起点立即生效，attempt 标 CANCELLED；被弃 worker 线程照跑至读超时（live-verify 桩需配短 timeout 让进程干净退出）。
- live-verify 观察到 httpx2 流式 asyncgen 收尾期 `aclose(): already running` 噪声（LLMClient 既有收尾竞态，非本批引入；行为与台账正确）→ **已清偿**：chat_stream_async finally 显式关流（见遗留清偿批 832748b0d）。
- 提交由并行会话统合落库（c6505ff54，含三卡全部生产码与测试）；本仓 D-R2 前两笔（fe4deb521/44396334f）仍在主线历史。
- 遗留移交：ollama 无 api_key 仍被运行面 key 门拦截（既有行为，未在本批放宽）；R11 每服务商 embedding_model 配置面未建（env 双键先行）；前端 weight/embedding 配置位后置。→ **均已于遗留清偿批清偿，见下节。**

### 遗留清偿批（2026-11-22，五项遗留当日清偿，本地未推）

用户指令「处理一下遗留问题」→ 收尾批登记的遗留与观察项逐项落地：

| 项 | 提交 | 内容 | 验证 |
|----|------|------|------|
| 身份台账存量红 | 4029a4291 | tests/unit/agent 存量 1 红清偿：按「台账即登记表」契约补登 a16ff1c91/ead7506bf/bae2b703c 批次新增的 4 处合法读方（asr/minutes 纪要归因、cognitive_layers/dreaming 规则审计、computer_use/lane_mutex 并发作用域、core/tool_call_journal 日志 scope） | 修复前 1F/10P 实测 → 11 passed 全绿 |
| ollama 免 key | 61ac1ca7c | 运行面 key 门三处同根因命中点（init 默认服务商门/_create_model_client 门/_resolve_available_fallback 懒建候选过滤）收敛到唯一判据 _providerRequiresKey：ollama 豁免（本地部署免鉴权），其余服务商维持「无 key 不建客户端」 | 红灯实测（No client available）→ 11 passed；全量 llm 1082 passed 零回归 |
| embedding_model 声明面 | f9fe2fe78 | R11 配置面补齐：ProviderConfig.embedding_model 字段（落盘持久化）+ manager 存取（空串=清除）+ CRUD API 逐键透传 + 通道目标解析单源化：env 双键（全局覆盖）> 服务商声明（list_providers 序首个）> 本地 | worktree@HEAD 红灯 4 failed 实证 → 绿；全量 llm 1088 passed 零回归 |
| 流式显式关流 | 832748b0d | chat_stream_async 增 stream 哨兵 + finally：正常/异常/消费方中断全退出路径显式 close 上游流——**清除此前「登记待观测」的 httpx2 asyncgen 竞态噪声根因**（GC 最终化与在途迭代竞态） | 间谍流 2 用例先红（不调 close）后绿；流式回归 39 passed |
| 前端配置位 | 7ed9022e2 | ModelPage 配置弹窗高级区暴露 分流权重（D-R2）与 嵌入模型（R11）输入，openConfigure 回填/saveConfiguration 显式下发（weight 空框不下发防误清、embedding_model 空串=清除）；i18n 五键 × 11 语言 | vue-tsc 0 错；vitest 2855 passed（存量 4 failed 经 stash A/B 实证系并行会话在途工作，非本批引入） |

执行注记：
- 磁盘满事故：C 盘 100% 阻塞 worktree 操作——清理陈旧 worktree（head-ab2，455M）与 pip/uv 缓存（~810M）后恢复；研究用参考克隆（lobehub-src 等）系有意保留未动。
- vitest 存量 4 failed 的 A/B 自证：stash 本笔前端改动后复跑同样失败——归属并行会话在途批（AIGC 子菜单重构 + 同名函数盘点台账未再生），不随本批清偿。
