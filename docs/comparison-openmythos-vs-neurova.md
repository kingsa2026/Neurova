# OpenMythos vs Neurova — 代码级架构对比

**对比时间**: 2026-06-28
**对比对象**:
- [OpenMythos](https://github.com/kyegomez/OpenMythos) v0.x(2026-05-23 main 分支)
- [Neurova](file:///e:/项目/Neurova) v4.0 (CogArch 2.0)

---

## 1. 项目定位对比

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| **本质** | PyTorch **底层模型架构**实现 | **应用层 Agent 框架**(调外部 LLM) |
| **核心问题** | "如何用更少参数实现更深推理" | "如何让 Agent 有人格、记忆、自主成长" |
| **抽象层级** | 模型权重层(nn.Module) | 业务逻辑层(Pipeline + 深度模块) |
| **是否训练** | 是(自带训练脚本 FSDP) | 否(消费已训练好的 LLM) |
| **代码规模** | ~1300 行核心代码(4 文件) | 550+ Python 文件 + 82 前端页面 |
| **依赖外部 LLM** | 否(自己就是 LLM) | 是(OpenAI/Anthropic/DeepSeek/通义) |
| **目标用户** | 模型研究员 | 终端用户(部署对话 Agent) |

**结论**:两者处于**完全不同的抽象层级**,无可替代性。OpenMythos 是"造大脑",Neurova 是"造人格"。理论上 Neurova 可以接入 OpenMythos 训练出的模型作为底层 LLM。

---

## 2. 架构核心理念对比

### OpenMythos — Recurrent-Depth Transformer (RDT)

```
Input → [Prelude P] → [Recurrent Block R × T] → [Coda C] → Output
                       ↑____________↓
                       权重共享 + 输入注入
```

**核心方程**:`h_{t+1} = A·h_t + B·e + Transformer(h_t, e)`

**四大支柱**:
1. **LTI 注入** — `A = exp(-exp(log_dt + log_A))`,谱半径构造性 < 1,保证循环稳定
2. **ACT 自适应停机** — 简单 token 提前 halt,难 token 多循环
3. **Loop-index 嵌入** — 正弦信号注入前 `loop_dim` 通道,让共享权重区分循环深度
4. **深度方向 LoRA** — 共享 down 矩阵 + 每 loop 一个 scale 向量,支持推理时深度外推

### Neurova — CogArch 2.0 认知架构

```
User Input → [ChatPipeline 6 步] → LLM → [PostChatPipeline 10+ 步] → Response
             ↑                                  ↑
             ContextOrchestrator               MemoryAgent
             (soul+memory+tools)               (17 维记忆)
```

**核心方程**:`response = LLM(system_prompt + context + user_input)`

**四大支柱**:
1. **深度模块化** — Agent 拆分为 MemCore/ContextOrchestrator/ToolExecutor 等,通过 `agent_ref` 依赖注入
2. **17 维记忆系统** — L1 肌肉记忆 → L2 热缓存 → L3 工具记忆 → 向量/结晶/时序/Hebb
3. **人格 + 认知层** — emotion/growth/memory/meta-cognition 四层认知
4. **6 步 ChatPipeline** — activity_tracking → pre_llm_checks → retrieve_context → evocate_injection → llm_call → post_processing

**对比**:
| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 深度来源 | **权重循环**(同一层跑 T 次) | **流程管线**(6 步串行) |
| 状态更新 | 线性时不变系统 `h = A·h + B·e + f` | 残差式 `context = soul + memory + tools` |
| 稳定性保证 | LTI 谱半径构造性 < 1 | 无(依赖 LLM 自身稳定性) |
| 自适应计算 | ACT per-token halting | 无(每条消息固定 6 步) |
| 参数共享 | 循环块权重共享 | 无(每步独立模块) |

---

## 3. 关键组件代码级对比

### 3.1 注意力机制

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 实现 | 自研 `GQAttention` + `MLAttention` (main.py:144-380) | 无(委托给外部 LLM API) |
| GQA | 支持,Flash-Attn 2 + 手动 fallback | 不涉及 |
| MLA | DeepSeek-V2 风格,KV 潜空间压缩 10-20× | 不涉及 |
| RoPE | 自实现 `precompute_rope_freqs` + `apply_rope` | 不涉及 |
| KV cache | dict 存储,支持 GQA/MLA 两种格式 | 不涉及 |

### 3.2 前馈网络

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| FFN 类型 | `Expert` (SwiGLU) + `MoEFFN` (DeepSeekMoE) | 无 |
| MoE | 路由专家 + 共享专家,aux-loss-free 负载均衡 | 无 |
| 稀疏性 | top-K 路由,激活比例 1.56%-6.25% | 无 |
| 共享专家 | 始终激活,吸收跨域通用知识 | 无 |

### 3.3 上下文构建

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 入口 | `OpenMythos.forward()` (main.py) | `ContextOrchestrator.build_context()` ([orchestrator.py:136](file:///e:/项目/Neurova/neurova/context/orchestrator.py#L136)) |
| 输入 | token ids → embedding | user_input + memory + tools + emotion + reflection |
| 上下文池 | 无(单次前向) | `ContextPool` 多源优先级池(SYSTEM/MEMORY/EXPERIENCE/CONVERSATION) |
| 压缩 | 无(固定 seq_len) | `compress_if_needed` 超预算时压缩 |
| 时间注入 | 无(模型不知道当前时间) | **有**([orchestrator.py:555](file:///e:/项目/Neurova/neurova/context/orchestrator.py#L555) `_build_current_time_section`,Bug T-1 修复) |
| 系统提示 | 无(纯 LM) | soul + personality + constitution + behavior_rules + tools + time |

### 3.4 记忆系统

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 记忆类型 | **权重即记忆**(训练写入参数) | **17 维外显记忆**(运行时读写) |
| 持久化 | 模型权重文件(.pt) | SQLite + 向量库 + 文件 + 时序图 |
| 检索 | 无(全量前向) | `UnifiedRetriever` 多通道语义检索(BM25 + 向量 + RRF 融合) |
| 温度 | 无 | 记忆温度 0-100(冷热分级) |
| 结晶 | 无 | `PatternCrystallizer` 经验模式固化 |
| 时序 | 无 | `TemporalKnowledgeGraph` 时序事实管理 |
| Hebb | 无 | `NeuHebbManager` 结构化推理记忆 |
| 肌肉记忆 | 无 | 工具使用模式自动执行(L1) |

### 3.5 推理生成

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 生成方式 | `model.generate()` 自回归 | 调用外部 LLM API(chat completion) |
| 循环深度 | **可变**(n_loops 参数,支持外推) | 固定(由 LLM 自身决定) |
| ACT 停机 | 有(per-token halting) | 无 |
| KV cache | 有(dict 累积) | 由 LLM 服务商管理 |
| 流式输出 | 支持 | 支持(SSE) |
| 工具调用 | 无(纯 LM) | 有([tool_executor.py](file:///e:/项目/Neurova/neurova/tool_executor.py),支持 OpenAI native + 文本解析) |

### 3.6 训练与优化

| 维度 | OpenMythos | Neurova |
|------|------------|---------|
| 训练脚本 | `training/3b_fine_web_edu.py` (551 行) | 无(不训练) |
| 并行策略 | FSDP FULL_SHARD + `ModuleWrapPolicy` | 不适用 |
| 数据集 | FineWeb-Edu 流式 | 不适用 |
| 优化器 | AdamW fused (0.9, 0.95) | 不适用 |
| 梯度裁剪 | `FSDP.clip_grad_norm_`(跨 shard) | 不适用 |
| 检查点 | 原子写入 + 自动剪枝 | 不适用 |
| 目标 tokens | 30B(3B 模型) | 不适用 |

---

## 4. 设计哲学对比

### OpenMythos — "少即是多"

- **参数效率**:1B 参数 + 16 loops ≈ 传统 16B 模型质量
- **权重共享**:循环块同一组权重跑 T 次,内存不随深度增长
- **构造性稳定**:LTI 谱半径数学保证 < 1,不依赖训练学习
- **可外推**:推理时 n_loops 可超过训练值,深度自适应
- **工程严谨**:FSDP 单上下文 state_dict、原子 ckpt、no_sync 累积,每处都有注释

### Neurova — "有温度的智能体"

- **人格驱动**:每个 Agent 有 soul + personality + constitution + behavior_rules
- **记忆即自我**:17 维记忆构成 Agent 的"经历"和"成长"
- **认知分层**:emotion/growth/memory/meta-cognition 四层认知
- **深度模块**:小接口深实现,通过 `agent_ref` 解耦
- **多渠道触达**:14 种通信渠道(Feishu/DingTalk/Telegram/Discord 等)

---

## 5. Neurova 可借鉴的设计

### 5.1 高价值借鉴

| OpenMythos 设计 | Neurova 适用场景 | 借鉴难度 |
|-----------------|------------------|----------|
| **LTI 谱半径构造** | 无直接对应(Neurova 不训练) | 低(纯数学启发) |
| **ACT 自适应停机** | ChatPipeline 步骤自适应(简单消息跳过记忆检索) | 中(需设计 halt 信号) |
| **Loop-index 嵌入** | 对话轮次嵌入(让 LLM 区分"第 N 轮对话") | 中(注入 system prompt) |
| **深度方向 LoRA** | 无直接对应(Neurova 不微调) | 低 |
| **MoE 路由思想** | 工具/技能路由(已有 ToolRouter,可借鉴 aux-loss-free) | 中 |
| **原子检查点** | 会话持久化(已有 SessionRepository,可借鉴 .tmp + os.replace) | 低 |
| **FSDP no_sync** | 无直接对应(无分布式训练) | 低 |

### 5.2 最值得借鉴的 3 项

#### ① ACT 自适应停机 → ChatPipeline 步骤跳过

**OpenMythos**:简单 token 提前 halt,难 token 多循环。
**Neurova 现状**:每条消息固定 6 步,简单问候也要跑完整管线。
**借鉴方案**:在 `_step_pre_llm_checks` 增加 `act_threshold`,简单消息(如"你好")跳过记忆检索/evocate 注入,直接进 LLM。

#### ② Loop-index 嵌入 → 对话轮次感知

**OpenMythos**:正弦信号注入隐藏状态前 `loop_dim` 通道,让共享权重区分循环深度。
**Neurova 现状**:LLM 不知道当前是第几轮对话(除非读 conversation_history 推断)。
**借鉴方案**:在 `_build_current_time_section` 旁新增 `_build_session_depth_section`,注入"当前是第 N 轮对话,深度等级:浅/中/深"。

#### ③ MoE aux-loss-free 负载均衡 → 工具路由优化

**OpenMythos**:`router_bias` 是 buffer 非 Parameter,只移动 topk 选择不进入梯度。
**Neurova 现状**:ToolRouter 路由均衡靠人工配置,无自适应。
**借鉴方案**:在 ToolRouter 增加 `router_bias` buffer,根据工具使用频率动态调整 bias,常用工具优先级提升但不影响 LLM 决策。

---

## 6. Neurova 相对 OpenMythos 的优势

| 维度 | OpenMythos 缺失 | Neurova 已实现 |
|------|-----------------|----------------|
| 人格 | 无(纯 LM) | soul + personality + constitution |
| 长期记忆 | 无(仅权重) | 17 维外显记忆 + 持久化 |
| 工具调用 | 无 | 完整工具执行 + 技能系统 |
| 多渠道 | 无 | 14 种通信渠道适配器 |
| 前端 UI | 无 | Vue 3 + 82 页面 |
| 时间感知 | 无 | Bug T-1 修复后注入当前时间 |
| 情感 | 无 | EmotionAnalyzer + 情感上下文 |
| 自主成长 | 无 | PatternCrystallizer + 进化层 |

---

## 7. 整合可能性

理论上 Neurova 可以接入 OpenMythos 训练出的模型作为底层 LLM:

```
Neurova ChatPipeline
  └─ ContextOrchestrator.build_context()
       └─ system_prompt = soul + personality + time + ...
       └─ messages = [system, memory, conversation, user]
  └─ LLMRouter.call(messages)
       └─ ★ 替换为 OpenMythos.generate(token_ids, n_loops=16)
            └─ Prelude → Recurrent(T) → Coda → logits
```

**整合挑战**:
1. OpenMythos 当前是 3B 研究规模,生产可用性未知
2. Neurova 依赖 OpenAI/Anthropic API 的高级能力(function calling、long context),OpenMythos 需补全
3. OpenMythos 无 RLHF/DPO,输出风格不可控
4. 部署成本:OpenMythos 需自建 GPU 集群,Neurova 现有云 API 模式更轻

**整合价值**:在数据敏感/离线/低延迟场景,OpenMythos + Neurova 可形成"本地化人格 Agent"方案。

---

## 8. 结论

| 评估 | 结论 |
|------|------|
| 是否同类 | **否**,处于不同抽象层级 |
| 是否可替代 | **否**,OpenMythos 造模型,Neurova 造应用 |
| 是否可整合 | **是**,Neurova 可接入 OpenMythos 作为底层 LLM |
| 核心差异 | OpenMythos 解决"参数效率",Neurova 解决"人格与记忆" |
| 互学价值 | OpenMythos 的 ACT/Loop-index/MoE 思想可启发 Neurova 流程优化 |

**一句话总结**:OpenMythos 是"会深度思考的大脑",Neurova 是"有温度有记忆的灵魂",两者结合才是完整的"智能体"。

---

## 附录:OpenMythos 文件清单

| 文件 | 行数 | 核心内容 |
|------|------|----------|
| `open_mythos/__init__.py` | 47 | 导出 18 个公开符号 |
| `open_mythos/main.py` | 1085 | 全部模型实现(Config/RMSNorm/RoPE/GQA/MLA/Expert/MoEFFN/LoRA/LTI/ACT/RecurrentBlock/OpenMythos) |
| `open_mythos/variants.py` | 155 | 7 个规模变体(1B-1T) |
| `open_mythos/tokenizer.py` | 60 | HF AutoTokenizer 薄封装 |
| `training/3b_fine_web_edu.py` | 551 | FSDP 预训练脚本 |

**总核心代码**:~1900 行(OpenMythos) vs 550+ 文件(Neurova)
