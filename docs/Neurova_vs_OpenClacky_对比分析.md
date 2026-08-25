# Neurova vs OpenClacky 源码层对比与评分

> 对比对象：
> - **Neurova**（本地项目，`e:/项目/Neurova`，Python / FastAPI）
> - **OpenClacky**（[clacky-ai/openclacky](https://github.com/clacky-ai/openclacky)，Ruby Gem，1.2k ★ / 105 forks / 1998 commits）

---

## 0. 一句话定位

| 维度 | Neurova | OpenClacky |
|------|---------|------------|
| 产品形态 | 全栈 AI 认知体（后端 + Vue 前端 + 多渠道 + 多模态） | 极简、Token 高效的开源 Coding Agent（CLI + WebUI + 桌面端） |
| 设计哲学 | 「大而全的认知架构」——模拟大脑多层记忆/情感/进化 | 「小而精的 Harness」——用最少工具 + Skill 生态覆盖任务 |
| 主语言 | Python（658 个 .py 文件） | Ruby（Gem，`lib/clacky/*`） |
| 目标 | AGI 式个人认知体 / 本地部署 | 低成本、可自托管的通用编程助手 |

两者**赛道不同**：Neurova 更像「认知操作系统」，OpenClacky 更像「工程化的 Agent 内核」。以下按源码结构逐项对比。

---

## 1. 源码结构对比（模块划分）

### Neurova（真实目录，节选）
```
neurova/
├── agent_core.py (1522 行, 核心循环)        # 仍有 God Object 倾向
├── agent/
│   ├── chat_pipeline.py (1228 行, 6 步管线)  # 已从 chat() 提炼
│   ├── loop_manager.py / loops/ (OpenAI/Anthropic)
│   ├── memory_retrieval_chain.py             # 责任链降级检索
│   └── crystallized_experience_manager.py    # 结晶经验容错
├── cognitive_layers/ (329 文件, 145 .py)     # 最大模块
│   ├── memory_layer/  (273 文件, 117 .py)    # 17 维记忆系统
│   ├── emotion_context_layer/                # 情感闭环
│   ├── growth_layer/                         # 成长日志
│   └── meta_cognition_layer/                 # 元认知
├── llm/ (71 文件)        # 多模型路由 / Provider 管理
├── channels/ (110 文件)  # 14+ 渠道适配器(飞书/钉钉/企微/Telegram…)
├── tts/ asr/ voice_*     # 6 个 TTS 引擎 + 语音管线
├── tool_layers/          # 工具编排 / 市场 / MCP
├── evolution/ skills/ plugins/  # 进化 / 技能 / 插件
└── api/ (301 文件)        # FastAPI 后端, 104 个 endpoint 文件
```

### OpenClacky（GitHub API 树，节选）
```
lib/clacky/
├── agent.rb agent_config.rb agent_profile.rb
├── cli.rb client.rb fanout.rb identity.rb
├── idle_compression_timer.rb          # 空闲压缩（对标 Neurova sleep）
├── agent/
│   ├── cost_tracker.rb                # 成本追踪（Neurova 缺原生）
│   ├── fake_tool_call_detector.rb     # 防幻觉工具调用
│   ├── goal_manager.rb goal_state.rb
│   ├── hook_manager.rb
│   ├── llm_caller.rb
│   ├── memory_updater.rb              # 记忆更新
│   ├── message_compressor.rb (+helper)# 上下文压缩
│   ├── session_serializer.rb
│   ├── skill_auto_creator.rb skill_evolution.rb skill_manager.rb skill_reflector.rb
│   ├── system_prompt_builder.rb
│   ├── time_machine.rb                # 时光机（回滚）
│   ├── tool_executor.rb tool_registry.rb
├── extension/ (loader/dispatcher/packager/scaffold/verifier)  # 扩展框架
├── mcp/ (client/registry/transport/oauth)                    # MCP 一等公民
├── default_extensions/ (advisor/coding/ext-studio/general/git/meeting/time_machine)
├── default_skills/ (browser-setup/channel-manager/code-explorer/deploy/recall-memory…)
└── billing/ locales/
```

**对比结论**：
- Neurova 模块**数量多、粒度细**（658 文件），但 `agent_core.py` 仍 1522 行、存在 God Object；`cognitive_layers/memory_layer` 膨胀到 117 个 .py。
- OpenClacky 结构**更收敛**：核心 harness 在 `lib/clacky/agent/*` 下逻辑平铺，工具只有 16 个核心 + `invoke_skill` 元工具，符合 README「工具数不是指标」理念。

---

## 2. 维度评分（0~10，加权）

| # | 维度 | Neurova | OpenClacky | 说明 |
|---|------|-------:|-----------:|------|
| 1 | 架构清晰度 / 模块边界 | **7** | **8** | N：深度模块理念好，但 God Object + 碎片化；O：极简分层清晰 |
| 2 | AI 能力深度（记忆/推理/进化） | **9** | **7** | N：17 维记忆、睡眠整合、贝叶斯遗忘、情感闭环、经验结晶；O：skill 进化 + time_machine + memory_updater |
| 3 | Token 效率 / 成本控制 | **6** | **9** | N：有 context_cache(724) / compressor(659)，但无原生 cost_tracker；O：~100% 缓存命中、空闲压缩、cost_tracker 一等公民 |
| 4 | 多模态 / 多渠道 | **9** | **6** | N：14 渠道 + 6 TTS + ASR + computer_use；O：IM 以 skill 形式存在，非内核原生 |
| 5 | 工程化（测试 / CI / 锁定） | **8** | **8** | N：~419 测试 + lockfile + linter 修复；O：rspec + rubocop + GH Actions + 1998 commits |
| 6 | 可扩展性 / 插件生态 | **8** | **9** | N：plugin manifest + tool marketplace + MCP；O：Extension 框架 + 可变现 Skill 包 + MCP 原生 |
| 7 | 成熟度 / 社区 / 发布 | **6** | **9** | N：本地项目，无公开星标；O：1.2k★、融资背书、桌面安装器、Docker |
| 8 | 前端 / 用户体验 | **9** | **7** | N：Vue3 82 页富前端；O：json_ui_controller + panels，较轻 |
| 9 | 部署 / 易用性 | **7** | ** - 9** | N：Docker + start 脚本，但依赖复杂；O：一行安装 / gem / 桌面端 / docker |

### 加权汇总（等权）
- **Neurova 综合：≈ 7.7 / 10**
- **OpenClacky 综合：≈ 8.0 / 10**

---

## 3. 源码层关键差异剖析

### 3.1 工具系统：极少 vs 极多
- **OpenClacky**：刻意保持 **16 个核心工具**，能力通过 `invoke_skill` 单一元工具下沉到 Skill 生态（`lib/clacky/agent/skill_*.rb`）。README 明确「Tool count is not the metric — task completion rate is」。`fake_tool_call_detector` 专门防 LLM 幻觉调用——这是成本/可靠性工程亮点，**Neurova 未见对应实现**。
- **Neurova**：`tool_layers/` 自建编排 + 市场 + `builtin_tools.py`(363) + `tool_executor.py`(1176) + MCP，工具集庞大但无原生「防幻觉」层。

### 3.2 上下文 / 成本工程
- **OpenClacky**：`message_compressor` + `idle_compression_timer` + `cost_tracker` + `system_prompt_builder`，设计目标是「会话从不重启、缓存标记、Insert-then-Compress」。README 宣称 ~100% 缓存命中、成本仅为 Claude Code 的 0.8×。
- **Neurova**：`context_cache.py`(724) / `context_compressor.py`(659) / `enhanced_context_builder.py` / `context_pool.py`，具备 16K 统一注入与分层压缩，但**没有独立的 token 成本核算模块**（仅 `performance.py` 粗略计时）。

### 3.3 记忆与认知深度
- **Neurova 压倒性领先**：`memory_layer`(117 .py) 实现了 17 维分类、睡眠整合(`sleep.py`)、贝叶斯遗忘曲线、时序知识图谱、MoE 向量检索、经验结晶(`pattern_crystallizer`)、情感闭环(`emotion_module`)。这是 OpenClacky 的 `memory_updater` + `time_machine` 无法比拟的工程体量。
- OpenClacky 的记忆更偏「会话级」（`session_serializer`、`memory_updater`），`time_machine` 提供回滚能力，认知深度有限。

### 3.4 多模态与渠道
- **Neurova**：`channels/`(110 文件) 原生飞书/钉钉/企微/Telegram/Discord；`tts/`(Edge/Moss/SAPI5/Mock)、`asr/`、`voice_pipeline.py`、`computer_use/`(浏览器自动化)。这是完整产品级集成。
- OpenClacky：IM 通过 `channel-manager` skill 与 `default_extensions`，非内核原生，多模态偏轻。

### 3.5 可扩展性与商业化
- **OpenClacky**：Extension 框架（`extension/loader/dispatcher/packager/verifier`）+ 可加密分发、License 管理、创作者定价——**自带商业化路径**。MCP 是一等公民（`mcp/client/registry/transport/oauth`）。
- **Neurova**：Plugin 系统（`plugin_manifest.py` 语义化版本 + `base_plugin.py`）+ 工具市场 + MCP 客户端，但无内置计费/分发。

---

## 4. 互相借鉴建议

| 来源 | 可借鉴到另一方的能力 |
|------|----------------------|
| ← OpenClacky | Neurova 应补 **cost_tracker / fake_tool_call_detector / idle_compression** 三位一体的「成本与可靠性」内核；收敛工具数量，强化单个 `invoke_skill` 元工具 |
| → Neurova | OpenClacky 可吸收 **多层记忆 + 睡眠整合 + 情感/元认知**，提升长期记忆与自我演进深度；引入富前端参考 |

---

## 5. 结论

- **Neurova 优势**：认知深度、多模态、多渠道、完整前端、本地化/隐私友好。定位「认知操作系统」，工程体量远超一般 Agent。
- **OpenClacky 优势**：架构收敛、Token 成本工程成熟、可扩展 Skill 商业化、开箱即用与社区背书。定位「极致性价比 Coding Agent」。
- **综合评分**：Neurova **7.7** / OpenClacky **8.0**（赛道不同，分数仅反映「源码工程质量与产品完成度」）。

> 若以「AI 认知深度与本地全栈」为目标，Neurova 更优；若以「低成本、可交付、可扩展的编程助手」为目标，OpenClacky 更优。两者并非零和——Neurova 补齐成本/可靠性内核后，可兼具两者之长。
