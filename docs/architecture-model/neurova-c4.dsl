// Neurova — C4 架构模型（现状视图）
// 技能来源: system-modeler + c4model
// 视图状态: current。例外已在 description 内显式标注 proposed / deprecated / inferred。
// 证据: 每条 description 内以 [文件:行号] 直指源码；完整模型见 evidence-model.json
// 预览: Qoder DSL 格式查看器打开本文件即可；无 java/graphviz 依赖
// 生成日期: 2026-09-19

workspace "Neurova" "Neurova 平台 C4 模型 — 证据接地，含置信度与断点标注" "1.0.0" {

    model {

        // ============ 人与外部系统 ============

        operator = person "Agent 开发者 / 运维" "修改 neurova/ 与 NeurUI/ 的工程人员，含 AI coding agent"
        channelUser = person "渠道终端用户" "经由飞书/钉钉/Telegram/Discord/QQ/微信/MQTT/SIP 与 Agent 对话"

        llmProviders = softwareSystem "LLM 服务商集群" "OpenAI / Anthropic / Gemini / Ollama / OpenRouter 等 8 家 [neurova/llm/provider_manager.py:2095]" {
            tags "External"
        }
        msgPlatforms = softwareSystem "外部消息平台" "18 个渠道适配器对端 [neurova/channels/base.py:121]" {
            tags "External"
        }
        mcpServers = softwareSystem "MCP Servers" "启动期挂载的外部工具服务 [neurova/agent_core.py:985-988]" {
            tags "External"
        }
        commercePlatforms = softwareSystem "电商 / 社媒开放平台" "neurflow external_clients 11 家 [neurova/collaboration/neurflow/external_clients]" {
            tags "External"
        }

        // ============ 系统边界 ============

        neurova = softwareSystem "Neurova" "人格化 AI Agent 框架 — 单体 Python 后端 + Vue3 前端" {

            frontend = container "NeurUI" "Vue3 + TS + Pinia + Ant Design Vue，SPA 监听 :8100 [NeurUI/vite.config.ts:17-42]" "Vue 3 / Vite 6 / TypeScript 5.7" {

                apiClient = component "api/index.ts" "唯一 axios 实例，baseURL=/api/v1，401 单飞刷新 [NeurUI/src/api/index.ts:22-46,77]" "Axios"
                stores = component "Pinia stores" "12 个 setup 式 store；3 个 *.optimized.ts 为未接线的并行副本 [NeurUI/src/stores]" "Pinia" {
                    tags "Orphan"
                }
                pages = component "pages/ (72 vue)" "真实视图层 [NeurUI/src/pages]" "Vue SFC"
                deadViews = component "views/ (3 文件, .tsx)" "React 组件但 package.json 无 react 依赖，router 零引用 [NeurUI/src/views]" "TSX" {
                    tags "Orphan"
                }
                sessionSyncFe = component "useSessionSync" "前端唯一 WebSocket 消费者，带 seq 游标与 gap 自愈 [NeurUI/src/composables/useSessionSync.ts:63-70]" "Vue composable"
            }

            backend = container "Neurova Backend" "FastAPI + SQLite，监听 :9527，双检锁单例 app [neurova/api/app.py:1160]" "Python 3.10+ / FastAPI / Uvicorn" {

                // --- 接入层 ---
                apiFace = component "API 面 (88 endpoint 项)" "字符串白名单 + importlib 动态注册 + ImportError 静默降级 [neurova/api/endpoints/__init__.py:182-301,296-297]" "FastAPI" {
                    tags "RiskHotspot"
                }
                httpDeps = component "deps.get_agent_instance" "HTTP 侧真 DI 入口，查 _app_state[agents] [neurova/api/deps.py:108]" "FastAPI Depends"
                wsChannels = component "实时通道 (WS x3 + SSE)" "console / mobile_pairing / session_sync；前二者无前端消费者 [neurova/api/endpoints/console.py:1886]" "WebSocket/SSE" {
                    tags "Orphan"
                }
                middleware = component "中间件栈 (7 层)" "CORS/SecurityHeaders/RequestID/Logging/RateLimit/GlobalAuth/HttpMetrics [neurova/api/middleware.py:197-244]" "ASGI"

                // --- Agent 核心 ---
                agentCore = component "Agent" "agent_core.py 2159 行，类 1122 行 / 57 方法，__init__ 仅两行委派 [neurova/agent_core.py:1038,1061,1071-1075]" "Python" {
                    tags "Core","SizeGuarded"
                }
                subsystem = component "SubSystemContainer" "真正的装配者：12 个 init_* 分组 + 拓扑序依赖图 [neurova/agent_core.py:452,483-496,503]" "Python" {
                    tags "Core"
                }
                turnState = component "TurnState" "轮次状态门面，实存于 core/turn_context 的 ContextVar，硬约束禁止 import agent_core [neurova/agent/turn_state.py:6-10,20,50]" "Python"
                chatPipeline = component "ChatPipeline" "chat_pipeline.py 2626 行；实测 8 个编号步 (0/0.5/0.7/1/2/3/4/5)，AGENTS.md 记为 6 步 [neurova/agent/chat_pipeline.py:392,421-445]" "Python" {
                    tags "Core","DocDrift"
                }
                postChat = component "PostChatPipeline" "3068 行，20+ 步，响应路径两波 asyncio.gather + 后台旁路 [neurova/post_chat_pipeline.py:601,648-680]" "Python" {
                    tags "SizeUnguarded"
                }

                // --- 能力层 ---
                memCore = component "MemCore" "记忆门面；agent 上属性名为 memory_agent [neurova/mem_core.py:19-23; neurova/agent_core.py:562]" "Python"
                memoryLayer = component "cognitive_layers/memory_layer" "118 文件＝认知层 86% 体积；19 个 *Module 由 MemoryManager 组合 [neurova/cognitive_layers/memory_layer/manager.py:195-218]" "Python" {
                    tags "SizeUnguarded"
                }
                memoryCompat = component "memory_agent.py / memory/" "纯兼容重导出与命名空间垫片 [neurova/memory_agent.py:10; neurova/memory/__init__.py:2-5]" "Python" {
                    tags "Deprecated"
                }
                toolExecutor = component "ToolExecutor" "5159 行＝全仓最大文件；四级回退执行链；无行数棘轮 [neurova/tool_executor.py:220,1045]" "Python" {
                    tags "SizeUnguarded","RiskHotspot"
                }
                toolLayers = component "tool_layers" "ToolRouter/UnifiedToolRegistry/Orchestrator/MCP；由 agent 装配而非 executor 下游 [neurova/agent_core.py:881,925,971]" "Python"
                contextOrch = component "ContextOrchestrator" "context/orchestrator.py 2122 行 [neurova/context/orchestrator.py]" "Python"
                emotionLayer = component "emotion_context_layer" "情感上下文注入；memory_layer 中唯一急切装配项 [neurova/cognitive_layers/memory_layer/manager.py:217]" "Python"
                metaCog = component "meta_cognition_layer" "元认知；PostChat 侧 11 处函数级 import [neurova/post_chat_pipeline.py:2570,2658,2698]" "Python"

                // --- LLM 层（含孤岛） ---
                llmClient = component "llm_client.py" "顶层门面（非 llm/ 包）；chat_stream 为伪流式 [neurova/llm_client.py:163; neurova/agent_core.py:1855-1864]" "Python" {
                    tags "DocDrift"
                }
                multiModel = component "llm/multi_model_client" "反向 import 顶层 llm_client [neurova/llm/multi_model_client.py:38,1429]" "Python"
                providerMgr = component "llm/provider_manager" "2161 行；get_/reset_ 单例对 [neurova/llm/provider_manager.py:2095,2140]" "Python"
                llmRouter = component "llm/llm_router" "多模态请求类型路由，32 处消费 [neurova/llm/llm_router.py:1]" "Python"
                llmIsland = component "llm/{adapters,registry,interfaces,sandbox}" "自引闭环并行孤岛，外部消费仅 1-4 处；终态未定（proposed 或残留）[neurova/llm/adapters]" "Python" {
                    tags "Orphan","Proposed"
                }

                // --- 协作 / 扩展面 ---
                channels = component "channels (18 适配器)" "ChannelAdapter(ABC) connect/disconnect/send_message [neurova/channels/base.py:121,153,167]" "Python"
                collaboration = component "collaboration + neurflow" "62 文件；neurflow 48 文件为工作流引擎 [neurova/collaboration/neurflow/builtin.py]" "Python"
                collaborate = component "collaborate/" "模板与工作流定义；与 collaboration 无继承无导入，命名冲突 [neurova/collaborate/__init__.py:8-11]" "Python" {
                    tags "RiskHotspot"
                }
                turnCoordinator = component "turn_coordinator" "get_turn_coordinator 零调用方，未接入 chat_pipeline → 协调层未闭环 [neurova/agent/turn_coordinator.py:324]" "Python" {
                    tags "Orphan"
                }
                crdt = component "crdt (RGA + 文档)" "实现完整但 Python 侧零消费者；前端唯一引用已注释 [neurova/crdt/core.py; NeurUI/src/stores/collaboration.optimized.ts:21,25]" "Python" {
                    tags "Proposed","Orphan"
                }
                skills = component "skills/ (49 文件)" "产品面：manifest 持久化 + SkillExecutor + 市场化 [neurova/skills/skill_service.py:129; neurova/skills/executor.py:36]" "Python"
                skillSystem = component "skill_system/" "兼容垫片包，__getattr__ 用 spec_from_file_location 载入被遮蔽的同名 .py [neurova/skill_system/__init__.py:190-223,264]" "Python" {
                    tags "RiskHotspot"
                }
                skillShadow = component "skill_system.py (32KB)" "规范实现，被同名包永久遮蔽，正常 import 路径不可达 [neurova/skill_system.py:43]" "Python" {
                    tags "RiskHotspot"
                }
                evolution = component "evolution" "eval/rsi/skill_*/顶层；事件+启动触发，无调度器 [neurova/agent/chat_pipeline.py:2548; neurova/api/app.py:774]" "Python"
                costLedger = component "成本账本 models/{cost_tracking,cost_budget,cost_store}" "只记账不拦截（只读报表）：is_over_budget / throttle_if_needed 仅报表路径调用 [neurova/models/cost_tracking.py:445,510; neurova/models/cost_budget.py:276,282]" "Python" {
                    tags "RiskHotspot"
                }
            }

            sqlite = container "SQLite 数据族" "128 个 .db；data/ 1.2GB，最大备份 793MB；路径常量无单一属主，47 文件直连 sqlite3.connect [neurova/core/database.py:19; neurova/models/cost_store.py:29]" "SQLite" {
                tags "DataStore"
            }
            filestore = container "文件态存储" "agent_workspaces 51MB / sessions 16MB(2408 文件) / trajectories 7.6MB / uploads 1.5GB" "Filesystem" {
                tags "DataStore"
            }
            ciGuards = container "CI 守卫" "ci.yml 9 job（受保护子集 + 覆盖率门）；cost-guards.yml 为 node:18 + 依赖未跟踪文件 + continue-on-error [package.json:9-11]" "GitHub Actions" {
                tags "RiskHotspot"
            }
        }

        helm = softwareSystem "Helm / K8s" "唯一真实多服务拓扑：backend+frontend Deployment/Service/hpa/ingress/pvc，replicaCount 均为 1 [helm/neurova/values.yaml:31,112]" {
            tags "External"
        }
        compose = softwareSystem "docker-compose" "默认单容器：frontend service 挂 profiles:development 故不参与默认 up [docker-compose.yml:67-85]" {
            tags "External"
        }
        desktop = softwareSystem "Tauri 桌面壳" "NeurUI/src-tauri + VITE_API_BASE_URL 覆盖 [NeurUI/package.json]" {
            tags "External"
        }
        legacyOps = softwareSystem "web/ + deploy/ 遗留运维" "PHP + nginx + xray，与 Python 主线无关 [deploy]" {
            tags "External","Deprecated"
        }

        // ============ 关系 ============

        operator -> neurova "开发 / 运维 / 配置 Agent"
        channelUser -> msgPlatforms "发起会话"

        frontend -> backend "REST 调用，经 vite proxy /api → :9527" "HTTP"
        sessionSyncFe -> wsChannels "唯一被消费的 WS 通道" "WebSocket"
        apiClient -> apiFace "统一入口；api/computer.ts 绕开实例用裸 axios" "HTTP"

        apiFace -> httpDeps "取 Agent 实例"
        httpDeps -> agentCore "查 _app_state 表"
        middleware -> apiFace "请求前置"

        agentCore -> subsystem "__init__ 仅调 init_all()"
        subsystem -> chatPipeline "装配并持有"
        subsystem -> toolLayers "init_tools 建栈"
        agentCore -> chatPipeline "chat() 薄封装委派 execute()"
        chatPipeline -> turnState "读写轮次状态"
        chatPipeline -> memCore "Step1 检索责任链"
        chatPipeline -> contextOrch "Step1 上下文构建"
        chatPipeline -> llmClient "Step3 LLM 调用"
        chatPipeline -> postChat "Step4 后处理"
        chatPipeline -> wsChannels "Step5 终答广播"
        chatPipeline -> turnCoordinator "设计意图路径，实际未接线 (inferred)" { tags "Unverified" }

        postChat -> metaCog "反思/账本/自我模型/动机"
        postChat -> evolution "模式结晶与技能进化"
        postChat -> memoryLayer "记忆固化"

        memCore -> memoryLayer "函数级 lazy import，单向向下"
        memoryLayer -> sqlite "读写记忆"
        memoryCompat -> memCore "纯 re-export"

        toolExecutor -> toolLayers "非下游：executor 不 import tool_layers，router 反向回手调 _execute_builtin_tool 私有方法"
        toolLayers -> mcpServers "挂载外部工具"
        toolExecutor -> skills "Skill 级回退"
        skillSystem -> skillShadow "按文件路径载入并注入 sys.modules 别名"
        skillSystem -> skills "SkillResult re-export 规范类"

        llmClient -> llmProviders "chat.completions.create 共 12 处，仅 2 处被装饰器覆盖" "HTTPS"
        llmClient -> costLedger "仅 2/12 调用点记账"
        multiModel -> llmClient "包内反向依赖顶层模块"
        multiModel -> providerMgr "服务商解析"
        llmClient -> llmRouter "请求类型分流"
        llmIsland -> llmClient "并行替代实现，终态未定 (inferred)" { tags "Unverified" }

        channels -> msgPlatforms "收发消息"
        channels -> apiFace "入向回调经 channel_router"
        collaboration -> commercePlatforms "工作流节点外呼"
        channels -> filestore "会话与媒体落盘"
        crdt -> stores "唯一前端引用已注释，未接入 (proposed)" { tags "Unverified" }
        collaborate -> collaboration "命名相近但零调用关系" { tags "Unverified" }

        ciGuards -> costLedger "guard:llm-tracked 标 continue-on-error，名义守卫不阻断"

        backend -> sqlite "连接"
        backend -> filestore "读写"

        helm -> backend "部署"
        helm -> frontend "部署"
        compose -> backend "默认唯一被拉起"
        desktop -> frontend "打包"
        operator -> legacyOps "历史遗留（不在主线）"
    }

    // ============ 视图 ============

    views {

        systemLandscape "01-landscape" {
            include *
            exclude "Person"
            autolayout tb
            title "L0 系统景观 — Neurova 与其所处生态"
        }

        systemContext neurova "02-context" {
            include *
            autolayout tb
            title "L1 系统上下文 — 边界、参与者与外部依赖"
        }

        container neurova "03-containers" {
            include *
            autolayout tb
            title "L2 容器视图 — 可部署单元与数据存储"
        }

        component backend "04-agent-core" {
            include *
            autolayout tb
            title "L3 后端组件视图 — Agent 核心与能力层"
        }

        component frontend "05-frontend" {
            include *
            autolayout tb
            title "L3 前端组件视图 — 含未接线并行副本"
        }

        // 样式
        element "External" {
            background #999999
            color #ffffff
            shape Hexagon
        }
        element "Person" {
            background #08427b
            color #ffffff
            shape Box
        }
        element "Core" {
            background #d46a4a
            color #ffffff
            borderColor #8c2f16
            strokeWidth 3
        }
        element "DataStore" {
            shape Cylinder
            background #44682e
            color #ffffff
        }
        element "RiskHotspot" {
            borderColor #c92a2a
            strokeWidth 4
        }
        element "Orphan" {
            border Dashed
            borderColor #e8590c
            background #f1f3f5
            color #495057
        }
        element "Proposed" {
            border Dashed
            borderColor #1c7ed6
        }
        element "Deprecated" {
            background #ced4da
            color #495057
            border Dashed
        }
        element "SizeGuarded" {
            bold true
        }
        element "DocDrift" {
            bold true
            borderColor #e67700
        }

        relationship "Unverified" {
            color #1c7ed6
            style Dashed
            thickness 2
        }
        relationship "Risk" {
            color #c92a2a
            thickness 2
            style Dashed
        }

        styles {
            background #ffffff
            strokeWidth 1
            color #2b2b2b
            fontSize 14
            font SANS_SERIF
            roundness 8
        }
    }
}
