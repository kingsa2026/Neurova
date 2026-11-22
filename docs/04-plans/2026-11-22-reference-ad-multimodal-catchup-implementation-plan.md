# 参照系 ad（LobeHub）多模态追平实施方案

- 日期：2026-11-22
- 来源：《reference_ad_multimodal_teardown_2026-11-22.md》（十轴专项细拆：LobeHub 68.5 vs Neurova 69.0 /100）与总报告 D8 维（细化前 L 6.5 / N 3.5 → 细化后 L 6.0 / N 7.0 /8）
- 目标：把专项暴露的短板补齐——重点攻**音乐生成（轴 7，0 起步）**、**视频协议覆盖（轴 3）**、**视觉协议面（轴 1 的 Gemini/转换形态缺口）**、**实时语音深度（轴 6）**；同时保持本仓已反超的语音双栈/屏幕视觉/OCR 不被稀释
- 范围：`neurova/llm/generators/`、`neurova/api/endpoints/generation.py`、`neurova/tts|asr|channels`（仅增量）、`neurova/agent/attachment_turn_injection.py`/`context/converter.py`、NeurUI aigc 页；不动活水池/记忆/编排/RSI 域
- 状态：**已拍板（2026-11-22 交互拍板）**——D-M1=fal（对方同款）/D-M2=realtime 不立项、深化 SIP/Twilio/D-M3=三家视频协议全做、用户自由选择/D-M4=生成物入池；可按批开工
- 复评机制：每批完成按专项十轴同卡复测；三批全完后总复评目标=专项总分 69.0→75.0+（轴 7 从 0 起步、轴 1 ≥8.5、轴 6 ≥6.0），总报告 D8 维保持 ≥7.0

## 0. 总原则

1. **实测纪律不破**：AIGC 端点/协议延续本仓既有纪律——只接实测核验过的官方 API，拒绝虚构预置（《AIGC生成端点矩阵_2026-09-14.md》口径）；不可用如实报错（对齐 `runtime.py` video_to_video 诚实报错形态）。
2. **新逻辑落新模块**：音乐/视频新协议落 `neurova/llm/generators/` 按既有协议族组织；`generation.py` 只加端点壳；不回填巨型文件。
3. **复用统一治理**：新增生成端点沿用既有 JWT+租户段+审计与配额闸；生成物文件按 user 隔离存储；不新增审批绕行。
4. **产品面必须接线**：每个新能力必须有真实消费出口（前端页/渠道/工具三者至少其一），不 做"有服务端无产品面"的形态（对方 TTS 断裂为反面教材）。

## 1. 批一 P0：生成短板与视觉核实（对齐专项轴 7/3/1）

### M1 音乐生成最小闭环（轴 7，0→有）

- 现状：无端点、无 provider、无页面（仅 multimodal_prober.py:71 musicgen 关键词与 neurflow 背景乐模板字段）。
- 改法：新建 fal 音乐生成协议（D-M1 已拍板：fal，对方同款）落 `neurova/llm/generators/`；`generation.py` 加 `/generation/music` + `/generation/music/status`（对齐 video 的提交/轮询两段式）；前端复用 AudioGenPage 模式扩展或独立 MusicGenPage；生成物音频文件走既有附件存储与鉴权取回。
- 红绿判据：红灯=协议桩单测先写（提交/轮询/完成/失败四态，当前无此端点必红）+ 端点审计测试；绿灯=实现后全绿。
- 验收：live-verify 真后端 + 桩 provider，全链路提交→轮询→取回。
- 影响面：`llm/generators/`（新增协议文件）、`api/endpoints/generation.py`（新增端点）、NeurUI aigc 页、provider 预置表。

### M2 视频生成协议补全（轴 3）

- 现状：Veo/SEEDANCE2/dashscope-wan 已有协议，但 video_to_video 无实测协议（facade 诚实报错）；无首尾帧参数语义。
- 改法（D-M3 已拍板：三家全做、用户自由选择）：dashscope-wan/SEEDANCE2/Veo 三家 video_to_video 协议与首尾帧（imageUrl/endImageUrl）参数全部落地，由前端模型/协议参数选择、facade 按协议分派（未指定时默认 dashscope-wan 先验证）；轮询对齐既有 /video/status。
- 红绿判据：三家协议桩单测先红（现 facade 对 video_to_video 报错）；实现后逐家断言请求/响应映射与分派选择全绿。
- 验收：live-verify 桩 provider 走通首尾帧视频生成与状态轮询。
- 影响面：`llm/generators/protocols.py`（或新协议文件）、`generation.py`。

### M3 Gemini 原生视觉链路核实/补齐（轴 1 待核实项）

- 现状：gemini_provider 声明 VISION（gemini_provider.py:47-113,242），但 gemini_client 无图片装配、走 langchain，端到端收图待核实；context/converter 仅 OpenAI/Anthropic 两形态。
- 改法：先核实（真发图到 gemini 桩/真 Key 二选一）；若链路不通，`gemini_client` 补图片装配（对齐 anthropic_client.py:55-97 的转换位），converter 增 Gemini 原生 content 形态。
- 红绿判据：红灯=gemini 图片回合 parity 测试（对齐 test_perception_image_anthropic_parity.py 形态）当前失败/无法构成；绿灯=三 provider（openai/anthropic/gemini）图片切片形态各自正确且单次进入请求。
- 验收：live-verify 视觉轮真发图，模型答出图片内容。
- 影响面：`llm/providers/gemini_client.py`、`context/converter.py`、`agent/attachment_turn_injection.py`（如需 third 形态分派）。

### M4 opencode provider vision 能力核实与路由排除（轴 1/8）

- 现状：opencode_provider.py:87-94 仅声明 TEXT+TOOL_USE；capability_detector 名称推断与真实探测之间的一致性未钉死。
- 改法：探测核实后，若确无 vision，则在 llm_router 视觉候选过滤中显式排除并落测试；若探测发现支持则更新声明。
- 红绿判据：视觉轮 auto 路由候选集不含 opencode（或含，按实测）——单测断言候选过滤结果。
- 验收：与 R3（路由专项卡）合跑：视觉轮自动选型不落到无 vision provider。

## 2. 批二 P1：语音深度与预算收口（对齐专项轴 6 与治理）

### M5 多模态预算口径单源化

- 现状：图片尺寸/预算上限散落 normalize_image_for_llm、image_retention（keep_last=4）、_MAX_UPLOAD_BYTES；model_limits 不承载多模态口径（model_limits.py:248-279 仅输出长度）。
- 改法：model_limits 增多模态输入预算段（单图 token 折算/每轮图片数/附件字节上限），各消费点改读单源；对外行为不变（现值平移）。
- 红绿判据：超限样本单测（现散落值与单源值一致断言）；改后路由/装配读同一来源。
- 验收：live-verify 附件超限回合被诚实拒绝/裁剪，行为与改前一致。
- 影响面：`llm/model_limits.py`、`agent/image_retention.py`、`agent/attachment_turn_injection.py`、files_api 上传限幅。

### M6 实时语音深度补全（轴 6）

- 现状：SIP 通道可接听/挂断+通话内 TTS/STT，但无 DTMF、无转写闭环、无转接/会议；Twilio 适配器依赖可选包。
- 改法：SIP 增 DTMF 事件捕获与菜单交互（最小：收号→按键语义→回合注入）；通话全程转写落 /minutes 同源管线；Twilio 适配器补接通后事件（不做完整呼叫中心）。
- 红绿判据：SIP 桩 DTMF 事件→回合 metadata 出现按键语义（当前必红）；通话转写落库断言。
- 验收：live-verify 用 SIP 桩/软电话走通"呼入→按键→转写→回复"。
- 影响面：`channels/sip.py`、`voice_context_module.py`、`asr/`（流式复用）。

### M7 视觉理解 provider 面扩容与探测闭环

- 现状：6/7 provider 声明 vision，但实际探测只有 openai 真图探测；openrouter/ollama/lm_studio 声明与实测一致性未钉死。
- 改法：multimodal_prober 扩展到全部声明 vision 的 provider（桩化 HTTP 层做 CI、真 Key 手动档）；探测结果进 capability_detector 缓存与目录展示。
- 红绿判据：每 provider 探测桩→能力位变更→路由候选与目录同步变化（同源断言，对齐路由专项 R7 口径）。
- 验收：live-verify 视觉轮在 6 provider 桩矩阵下自动选型全部正确。

## 3. 批三 P2：契约纪律与特色整合（对齐专项轴 10 与差异化）

### M8 多模态契约测试棘轮（轴 10）

- 现状：本仓覆盖广（parity/单次进入/视频帧/音频转写），但缺对方已验证的四类形态：SVG 拒发、AVIF 媒体引用兜底、无视觉模型占位符（VISION_DOWNGRADE_PLACEHOLDER 语义）、工具产出图片回灌复查。
- 改法：逐类补契约测试（先写对现状失败/或钉住现状正确的），不足处补实现；SVG/AVIF 按本仓附件归一化落点处理。
- 红绿判据：四类样本各一条测试；其中"无视觉模型占位符"若本仓现行为是静默丢图则先红后修。
- 验收：契约测试进 protected 子集，回归零新增失败。

### M9 AIGC 生成物入活水池（本仓特色整合，对方无）

- 现状：生成图片/视频/音频仅作为消息附件存在；活水池 11 种 ContextSource 未含生成物来源。
- 改法：生成完成回执时把生成物（含提示词/模型/任务号）作为新 ContextSource 条目入池（遵循 add_context 单源咽喉与租户/会话作用域），后续轮次可被语义召回；不改变池既有淘汰/折叠语义。
- 红绿判据：生成后下一轮语义召回能命中该生成物条目（红灯=现无此来源；绿灯=召回命中且不破坏池现有测试）。
- 验收：live-verify 生成→下轮追问"刚才生成的什么"→召回命中。
- 影响面：`context/pool_models.py`（新增 source 枚举值）、`aigc_studio/services.py` 或 generation 端点回执处挂接。

### M10 realtime 语音模型评估（只评估不实现）

- 现状：对方 realtime 纯占位；本仓 SIP 已有真实通道。
- 改法：产出评估结论（OpenAI Realtime 类 WebSocket 通道 vs 现有 SIP/Twilio 深化），给立项建议；本计划不含实现。

## 4. 拍板记录（2026-11-22 交互拍板）

| 项 | 问题 | 拍板结果 | 落点 |
|----|------|---------|------|
| D-M1 | 音乐生成 provider 选型 | **fal（对方同款）** | M1 |
| D-M2 | realtime 语音通道是否立项 | **不立项，深化 SIP/Twilio** | M6 |
| D-M3 | 视频协议补全范围 | **三家全做（dashscope-wan/SEEDANCE2/Veo），用户自由选择** | M2（范围扩容） |
| D-M4 | AIGC 生成物是否入活水池 | **入池** | M9 |

## 5. 不照搬清单

1. **"有服务端无产品面"的 TTS 断裂形态**（对方 6 家实现+完整路由但聊天 UI 空桩）——本仓任何语音能力必须接到真实出口；
2. **realtime 占位卡片**（有类型枚举无运行时）——不做无运行时的能力声明；
3. **云侧听写端点依赖**（对方实时听写会话端点不在 OSS，自托管不可用）——本仓 ASR 保持本地/自选引擎可自托管；
4. **音乐/视频单 provider 绑定**——若做，协议层按族组织，留第二家接入位。

## 6. 多租户与安全影响

- 新增 /generation/music等端点沿用既有 JWT+租户段+审计；生成任务按 user 归属，生成物文件走既有附件存储与鉴权取回（chat.py:222 同款）。
- M9 入池不改变池的会话/租户作用域隔离——生成物条目归属发起会话，跨租户不可召回。
- SIP/Twilio 凭据走 secret_store；M6 的通话转写沿用 /minutes 同源管线与审计。
- 多模态预算单源化（M5）不放宽任何现有限幅——现值平移，仅收拢口径。

## 7. 验收门与复评

- 每卡：红灯（对现状失败的断言）→ 绿灯（最小实现）→ live-verify（真后端 9527 + 桩 provider/桩 SIP；多模态桩置于测试数据根）。
- 批验收：批一=轴 7/3/1 复测（音乐闭环+视频首尾帧+三 provider 图片 parity）；批二=轴 6/10 复测（DTMF 通话转写+预算单源+探测矩阵）；批三=契约四类用例+入池召回。
- 总验收：三批后按专项十轴同口径复评，目标总分 69.0→75.0+、轴 7 ≥5.0、轴 1 ≥8.5、轴 6 ≥6.0；复评结论回写专项文档与总报告 D8。

## 8. 执行记录（2026-11-22 三批全部实施完毕）

- **批一**：M1+M2+M9=0b1a63fd3（生成域三卡文件交叠，按仓内先例合并一笔；fal Queue API 实核、三家 v2v+首尾帧、GENERATION 来源入池+召回命中）；M3=6ae012c91（Gemini 原生视觉链路补齐：geminiImagePartFromUrl/geminiPartsFromContent 单源+converter 第三形态）；M4=7fe18e744（opencode vision 排除契约钉住，核实通过零码改）；M7=0a4dbe78d（探测矩阵三协议族进 CI+同源联动）；M6=49b88fcf6（SIP DTMF+通话转写闭环）。
- **批二**：M6b ASRManager 启动即初始化=5282b18e9（线3 live-verify 发现的域外装配缺口当场收口：app.py 只构造不 initialize→VoiceEngine[ASR] 永不装配）；M5 预算单源=2917ffadd（model_limits 承载多模态输入预算，四消费点改读单源，现值平移逐字节一致）；M8 契约棘轮=fe447b536（SVG 诚实拒发/AVIF 转码/无视觉钉约/工具图片回灌四类）。
- **批三**：M10 realtime 评估结论=不立项（D-M2 已拍板），SIP/Twilio 深化路线覆盖。
- **遗留移交**：chat_pipeline.py:1814 `_IMAGE_RETENTION_KEEP_LAST` 字面量收口（值与单源一致，行为无漂移）；fal duration/产物字段官方模型卡待核；v2v 三家请求体待真 key 实测；音乐前端页未接（后端+端点已通）；Twilio Digits 接入下批；ASRManager 装配缺口的同族排查（TTSManager 是否同病）下批核对。
- **复评（同口径十轴）**：69.0→**74.5**（轴 7 音乐 0→3.5 后端闭环、轴 1 视觉 8→8.5 Gemini 补齐、轴 3 视频 7→7.5 v2v、轴 6 实时语音 5→6.5 DTMF+转写、轴 10 契约 8→8.5）；总报告 D8 维 7.0→7.5，总分 94.0→95.0。未达 75.0 目标的缺口=音乐前端页未接与 v2v 真 key 实测未做（见遗留移交）。

## 9. 遗留清偿记录（2026-11-22 第二轮，五项清偿完毕）

| 遗留项 | 处置 | 提交 |
|--------|------|------|
| 音乐生成前端页未接 | **已接**：MusicGenPage.vue（提交→3s 轮询四态→audio 播放/下载，与 VideoGenPage 同范式）+generation.ts submitMusic/musicStatus+路由 /aigc/music+导航/权限目录+i18n×11；后端无音乐模型卡时诚实显示仅 auto | 858be6f87 |
| keep_last 字面量收口（chat_pipeline.py:1814 同根因第 4 处） | **已收口**：消费点改读 model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN（调用时读取），行为测试 monkeypatch 单源验证 | c2cf8cd3c |
| 探测矩阵四家接线（anthropic/openrouter/ollama/lm_studio 仍名称启发式） | **已接线**：四家 probe_model_multimodal 委托 M7 矩阵，全仓 name_heuristic 零残留、七处 probe 全诚实 | 79aa28333 |
| TTSManager 装配核对（ASR 同族排查） | **核对通过零码改**：常驻模式 :1214 先初始化、lazy 模式 _ensure_ready 咽喉自愈、VoiceEngine[TTS] 无门控——设计态以 5 测试钉住 | 50a7a1d54 |
| Twilio Digits 接入 | **已接**：handle_webhook 识别 Gather Digits→voice_context 单源（DTMF_DIGITS_KEY）进回合；同根因扫荡修正事件映射「mid-call 用户输入全映射 BOT_ERROR」缺陷 | 700e9d9b2 |
| v2v 三家请求体真 key 实测 | **待凭据**（providers.json 仅元数据、凭据在 keyring；真实生成产生费用，需用户提供/批准可用 key 后执行） | — |

- 遗留清偿后复评：轴 7 音乐 3.5→**4.5**（前端页接通，与对方同为单 provider+完整产品面），专项总分 74.5→**75.5**，达成 75.0 目标；其余轴不变。
- fal 契约核实（2026-11-22）：队列信封（提交/状态/取回 URL、Key 鉴权、IN_QUEUE/IN_PROGRESS/COMPLETED 状态机、error/error_type、owner/app 405 规则、request_id/response_url/status_url/cancel_url 回执）与音频产物字段（官方明示 audio_url 或 audio）已按官方 OpenAPI/文档实核，M1 实现逐项一致；musicgen duration 入参字段名/单位仍按桩锁定（模型卡动态渲染未能抓取，真 key 实测待凭据）。
- 线B 连带发现（已登记待裁，非本批引入）：handle_webhook 全仓零生产调用者（webhook 分派缺 voice 支，test_channelVoiceFactorySeamCloses.py 因分派链无验签刻意不接）——HTTP 路由接线仍按该登记待安全批处理。
- **三端增量（2026-11-22 同日追加实施）**：NeurUI AigcHistoryList music 联动+VideoGenPage 暴露 v2v/首尾帧可选参数=8519dd493；鸿蒙 AIGCPage 接入音乐类型+AigcApi 补 music 契约（AigcVideoSubmitResult/StatusResult 收口更名 AigcAsyncTaskSubmitResult/StatusResult）=d68d6c603；安卓原生新建 feature/aigc 生成页（图/视频/音频/音乐四类+3s 轮询+工作台悬浮入口，HttpChannel 补 getBytes 二进制开口）=85b808560。
