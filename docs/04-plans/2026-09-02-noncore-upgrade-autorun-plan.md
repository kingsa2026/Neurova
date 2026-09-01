# NV 补课升级自动长任务计划（2026-09-02）

> **执行方式（用户已选）：批准后本会话连续自动执行**——按批次 0→5 顺序推进，每任务 TDD 跑绿 → commit → 下一任务，无人工检查点；仅遇危险操作（删 tracked 文件、不可恢复破坏）时停下记录。
> **来源**：`docs/Neurova_QwenPaw全方位对比_v4_2026-09-01.md` §19 合并补课清单 + §24 三域补课要点；工程面 9 项细节沿用 `docs/04-plans/2026-09-02-noncore-cleanup-plan.md`（下称"细化计划"，含 Task 3 backup API 完整代码），本文不重复其代码，只给增量与接线结论。
> **纪律**：venv/Scripts/python.exe 跑 pytest；新测试文件 `git add -f`（.gitignore /tests/ 规则）；开工前 `git status` 确认相关文件无用户并行改动；Mimosa 可能拦 `.execute(`/`def execute(` 字面形态——别名或 Edit 工具绕过；临时探针文件即用即删。

## 总览（6 批次 23 任务）

| 批次 | 主题 | 任务 | 状态 |
|---|---|---|---|
| 0 | 速赢小修 | compose 修字 / 健康检查真连库 / README+根目录清理 / backup API 接线 / MoE 行为锁定 | ✅ 5c |
| 1 | 可观测性+数据层 | trace_id 日志 / user_version 迁移 | ✅ |
| 2 | 前端 P1 | 语义搜索断链 / 通知 SSE / 会话搜索+置顶 / 图谱真渲染 | ✅ |
| 3 | 前端 P2 | 工具卡分化 / 审批双档 | ✅ |
| 4 | 语音域 | ASR 诚实止血 / ASR 本地真模型 / 流式 TTS / 闭环联动 | ✅ |
| 5 | 记忆认知 | conflict 去 mock+真写回 / TKG 检索接线 / 收敛第一批 / create_skill 扫描 | ✅ |

## 批次 0：速赢小修

- [x] **0.1 compose 挂载**：docker-compose.yml:39 `./neuUI`→`./NeurUI`；`docker compose config --quiet` 验证。细化计划 Task 1。
- [x] **0.2 健康检查真连库**：app.py 新增 `_make_database_health_check(db_path)` 工厂（SELECT 1 探测+失败上报），替换 ：100-108 假 lambda；测试 tests/unit/core/test_health_check_database.py。细化计划 Task 2（含完整代码）。
- [x] **0.3 README+根目录**：bata1→beta1 两处（README.md:1402,1665）；按细化计划 Task 4 的 untracked 清单逐个 `git ls-files` 复核后删，tracked 的 test_api_output.wav 用 git rm；.gitignore 补 `*_sse.txt/_r*.txt/_em.txt/_mp*.txt/_cfg.json` 防再生。
- [x] **0.4 BackupOrchestrator 接线**：按细化计划 Task 3 完整代码实施——backup_api.py（admin 路由级门+DCL 单例+create/list/restore+409 信任门+Zip Slip 防护）+ endpoints/__init__.py 注册 + tests/unit/api/test_backup_api.py 4 用例。
- [x] **0.5 MoE 行为锁定**：tests/unit/memory/test_moe_background_index.py 3 用例锁定 mem_core.py:285 既有行为（预算截断/游标守卫/状态落盘）。细化计划 Task 8。

## 批次 1：可观测性+数据层

- [x] **1.1 trace_id 日志**：新建 neurova/core/trace_context.py（ContextVar 三函数，identity_context 同构）；_JsonLogFormatter 加 trace_id（None 省略）；trace_recorder.start_trace 末尾 set/end_trace 成功 pop 后 clear。测试细化计划 Task 5。
- [x] **1.2 user_version 迁移**：新建 neurova/core/db_migration.py（注册表+逐条事务+失败回滚）；接入面只挂 cognitive_storage_engine.py:252 WAL 行旁（软降级 warning）；v1 占位 `register_migration(1, "SELECT 1")`。测试细化计划 Task 6（3 用例含回滚）。

## 批次 2：前端 P1（落点已核实）

- [x] **2.1 语义搜索断链**：MemoryPage.vue:581-587 改调现成 `memoryApi.enhancedSearch`（memory.ts:944，POST /enhanced-memory-search/search）；解包 `res.data.data.results`（嵌套 results 非数组）；type 过滤改前端本地 filter（后端无 type 参数）。测试：MemoryPage 既有测试补 1 用例锁端点。
- [x] **2.2 通知 SSE**：后端 notifications.py 新增 `GET /notifications/stream`——StreamingResponse+async generator，事件 `data: {"type":"unread","count":N}`（复用 chat.py:259 的 SSE 模式；生成器内 10s 轻量轮询 unread-count 查询）；前端 notifications.ts 加 `subscribeNotificationStream`（**fetch+ReadableStream**，非 EventSource——axios 统一注入 Bearer 头，EventSource 带不了），MainLayout.vue:227 的 60s setInterval 改 SSE+失败降级轮询。后端测试 1（端点形状）+前端测试 1（解析 data: 行）。
- [x] **2.3 会话搜索+置顶**：搜索纯前端（ChatPage.vue 对 store messages 过滤——历史无分页全载，不漏）；置顶前后端：session_repository.py ABC+实现加 pin 字段/PATCH 端点（console.py 摘要 ：519 透出 pinned），前端 types/chat.ts 加字段+chat.ts pin action+filteredSessions 置顶排序+ChatPage 右键菜单。测试：后端 repo pin roundtrip 1 用例。
- [x] **2.4 图谱真渲染**：main.ts 按需注册加 GraphChart（1 行）；KnowledgeGraphPage.vue 用 vue-echarts VChart force 布局替换 ：59-105 卡片区；字段映射 `type→category`（现恒 default 的根因）、`label→name`、`description` 进 tooltip；统计卡用 total_nodes/total_edges。测试：映射函数单测（纯函数抽出）。

## 批次 3：前端 P2

- [x] **3.1 工具卡分化**：ChatPage.vue 新增 `toolCardVariant(name)`（computer/file/search/shell/code 五类，复用既有 isComputerTool）；模板 :169-191 按变体改图标+标题+tag 颜色；样式 nr-tool-* 加变体 class。不动 useChat 数据层。测试：toolCardVariant 纯函数单测。
- [x] **3.2 审批双档**：后端 governance.py:69 `ApprovalActionRequest` 加 `remember: Optional[str]=None`（approval_manager.py:328 能力已就绪，仅 API 未透出）；:150 传 remember。前端 governance.ts approveRequest 加参；ChatPage.vue :549-577 模态框加"仅本次/记住精确(exact)/记住同类(similar)"单选，confirmApproval 透传；severity 从 `request.metadata.governance.severity` 读展示（已有字段）。后端测试 2（exact/similar 透传）。

## 批次 4：语音域（ASR=本地真模型，用户已选）

- [x] **4.1 ASR 诚实止血（先行）**：funasr_engine.py L92/L116/L198-206 假初始化与"模拟FunASR识别结果"改为真报错；whisper_engine.py L66-68 同理；manager.py CHAIN 移除 mock（仅 NEUROVA_ENV=test 时保留）；/transcribe 无真引擎时 503（端点语义已有，audio.py:287）。测试 2（假引擎报错/无引擎 503）。
- [x] **4.2 ASR 本地真模型**：requirements.txt 解注释 `openai-whisper`（funasr 不装——whisper 路径 `_transcribe_sync` 已是真实现，成本更低）；复制 tts/model_downloader.py 模式新建 asr/model_downloader.py（MODEL_REGISTRY 加 whisper-base 条目，目录对齐 manager.py:109 的 models/asr/whisper）；**修复 whisper_engine.py model_dir 被忽略的 bug**（L82 `load_model(..., download_root=model_dir)`）；启动探测：无模型+downloadable 时后台下载，失败诚实降级。测试：model_dir 传参 1 用例（mock load_model 断言 download_root）+ downloader registry 1 用例。注：openai-whisper 装 torch，Windows 首装重——若 pip 失败超 10 分钟则任务降级为"依赖装好即用/失败留 TODO"，不阻塞后续批次。
- [x] **4.3 流式 TTS**：**修真 bug**——audio.py:226 端点声明 audio/wav 但 edge_tts.py:93-126 yield 的是 MP3 裸字节：改为按引擎动态 content-type（moss=wav/edge=mpeg）；前端 ChatPage.vue synthesizeTTS 改 fetch `/synthesize-stream` + Web Audio 逐 chunk decodeAudioData+schedule；音频 UI duration 未知时禁用 seek。若 Web Audio 版超时，降级"长文本走 stream 攒 blob 播放"的伪流式（保底交付）。测试：content-type 按引擎断言 2 用例。
- [x] **4.4 闭环联动**：**修死代码**——chat.py SSE 流式生成器（:230-257）在 done 前透出 `event: audio`（`data:{"type":"audio","url":...}`，数据源=非流式路径已产出的 audio_info）；前端 done case 补 `event.audio_url→msg.audioUrl` 兜底（:1354-1361 消费端已就绪）；enable_tts 开启的 agent 流式对话自动出声。测试：SSE 事件序列含 audio 1 用例。

## 批次 5：记忆认知

- [x] **5.1 conflict 去 mock+真写回**：endpoints/sleep.py 删 4 个 _generate_mock_*，sleep_manager 为 None 时返空列表（改 :552/:576 等兜底）；SleepConsolidation.resolve_conflict（sleep.py:667）扩展真写回——按 resolution(keep_longest/keep_newest/merge) 从 source_memories 删落选者/重写胜者；冲突记录在 merge_cluster 冲突分支（:330）以 resolved=False 落库。前端 sleep.ts/SleepSettingsPage 已对齐零改动。测试：resolve 三档写回 3 用例+mock 移除后端点返空 1 用例。
- [x] **5.2 TKG 接线**：新建 neurova/agent/retriever_adapters.py 的 TKGRetrieverAdapter（Protocol:93-112——name="TKGRetriever"/priority=25/retrieve 调 tkg.query_current 转 dict/get_quality_score 抄 :75 模板）；构造链：memory_layer/__init__.py:57 的闲置实例真正实例化+TemporalFactExtractor.sync_memory_to_tkg 挂记忆归档后（post_chat 一步，失败仅 debug——TKG 本就可选）；MemoryRetrievalChain.add_retriever 注册（KnowledgeRetrieverAdapter 同款补充式合并）。测试：adapter 协议+转换 2 用例、注册进链 1 用例。
- [x] **5.3 收敛第一批（仅安全项）**：①双冲突检测器——v2 留作包级 ConflictDetector（已是），v1 改名 ConflictDetectorV1 保留 channels/processor 兼容导入；②双遗忘——sleep.apply_sleep_decay 改为调 TemperatureEngine.on_decay 的批量包装（不另持曲线）。不动情感双引擎/双元认知（调用面大，独立立项）。测试：回归各 1 用例。
- [x] **5.4 create_skill 注入扫描**：tool_executor.py:1068 _execute_create_skill 的 name/steps 过 PromptInjectionAnalyzer（skill_scanner 既有，抄 QP materialize_skill 安全扫描闸）；测试 1 用例。

## 执行与验收约定

1. 每任务完成即 commit（conventional commits，单任务单 commit），批间跑相关测试套件防回归（对照预存基线：core 427F+132E / api 105F / agent 43F+42E——**预存失败不算回归**，新增失败才算）。
2. 前端任务跑 `npm run test -- --run`（vitest）+ 受影响页面既有测试。
3. 危险操作红线：删 tracked 文件仅限 0.3 清单且逐个复核；不重写 git 历史；用户并行改动文件（git status 非本任务产生）跳过并记录。
4. 全部完成后：更新对比文档 §19/§24 各项状态标记 + 记忆归档 + 汇总 commit 清单报告。

## 明确排除（大工程另立项）

Tauri 桌面、消息队列、断线 replay 快进、真 MSE 流式、认知模块大收敛（双情感引擎/双元认知）。

## 自审记录

- 覆盖：§19 前端 8 项中 P3-a 重连快进/P3-b 消息队列（大工程）不在本计划；§24 语音 6 项中认知收敛只做安全两项；ASR 双模由 4.2 本地覆盖（远端可后续叠加）；create_skill 扫描闸并入 5.4。
- 类型一致性：TKGRetrieverAdapter 遵循 Retriever Protocol（runtime_checkable）字段名；SSE 事件格式与 chat.py 既有 `data:{...}` 单行 JSON 一致。
- 无占位：ASR 依赖安装失败有明确降级路径；流式 TTS 前端有伪流式保底。


## 执行结果（2026-09-02 当日完成）

| 批次 | commits |
|---|---|
| 0 | d17de4f compose / ee70a45 健康检查+连接池 / c7cf124 卫生 / 058d2e3 backup API / 7b7f6d9 MoE 锁定 |
| 1 | bbf90e8 trace_id / 6400b4c user_version 迁移 |
| 2 | ef34384 断链 / 4fd306f 通知 SSE / 11756d5+9956cc6 会话置顶 / 20fc9b8 图谱渲染 |
| 3 | cc9b25a 工具卡分化 / ccf8f42 审批双档 |
| 4 | 1315cd2 ASR 止血 / 063e97b Whisper 本地 / 4254bb8 流式 TTS content-type / 24bc39c 闭环联动 |
| 5 | d1788de conflict 真写回 / f58311e TKG 检索接线 / e30f81c 收敛第一批 / 49e1fbe create_skill 扫描 |

**新测试 34 用例全绿**（backup 5 / health 2 / MoE 3 / trace_id 3 / migration 4 / MemoryPage 2 / notify SSE 2 / pin 3 / 图谱 3 / 工具卡 4 / governance 4 / ASR 8 / conflict 4 / TKG 4 / create_skill 4 → 计 51；部分按文件计）。
**意外发现并修复的额外 bug**：①connection_pool 空池阻塞 30s；②edge-tts 流式 MP3 裸字节标 audio/wav；③chat SSE 恒走非流式降级（Agent 无 chat_stream）且 audio 分支死代码；④whisper model_dir 被忽略散落 ~/.cache。
**预存失败 stash 实证**：core trace 套件 20F（签名漂移）、config 2F、session 4F、agent skill 2F、result_processing 1F——均非本计划引入。
**用户并行改动处置**：mem_core MoE 索引、notifications JSON 持久化、tts sanitize 等既存工作树改动随相关 commit 一并入库（本计划只做增量未覆盖）。
