# reference_ad 专项：多模态能力十轴细拆（Neurova vs LobeHub）

- 日期：2026-11-22
- 性质：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D8 维的**专项细拆**（竞品/外部对标，研究参考，不作产品事实源）
- 对象：lobehub/lobehub（canary@2026-11-21 快照）vs 本仓主干了；证据来自两路只读深读（本仓 `chat_pipeline`/`llm/generators`/`tts`/`asr`/`channels`/`computer_use`/`knowledge` vs 对方 `builtin-tool-image-generation`/`video-generation`/`model-runtime` 多模态面/`context-engine` MessageContent/创作页路由），全部结论带 file:line
- 评分口径：本专项 10 轴 ×10 分 = 100 分（与总报告 D8 的 8 分维互相独立，粒度更细）

## 0. 结论摘要

**专项总分：LobeHub 68.5/100 vs Neurova 69.0/100**——总体接近，画像互补。

- LobeHub 最强：**生成侧广度与工程化**（图像 41 家/视频 24 家 provider，工具链状态机+client/server 双执行器+独立创作页）与**多模态契约测试矩阵**（MessageContent 全矩阵 950+ 行）。
- Neurova 最强：**语音双栈全线接线**（TTS 3+ 引擎/ASR 4 引擎/流式 WS/语音纪要/渠道出入站契约/SIP+Twilio 电话）、**桌面屏幕视觉**（截图+UIA+SOM+感知三闸）、**OCR 三引擎同契约**、**AIGC 端点实测纪律**（拒绝虚构预置）与 aigc_studio 分镜→图→视频生产管线。
- 双方共同缺口：realtime 语音模型都是占位/无运行时；音乐生成一边全缺、一边单 provider。
- 一句话：对方是"**生成广度 + 前端创作面**"，本仓是"**语音/屏幕/文档理解 + 生产管线**"——首版 D8 粗评（6.5 vs 3.5）低估了本仓，细化后接近持平、本仓反超。

## 1. 十轴评分表

| # | 轴 | 满分 | LobeHub | Neurova | 判定 |
|---|----|-----:|--------:|--------:|------|
| 1 | 视觉理解输入 | 10 | 9.0 | 8.0 | L 胜 |
| 2 | 图像生成 | 10 | 9.5 | 7.0 | L 胜 |
| 3 | 视频生成 | 10 | 9.0 | 7.0 | L 胜 |
| 4 | 语音合成 TTS | 10 | 6.5 | **8.5** | **N 胜** |
| 5 | 语音识别 ASR/听写 | 10 | 8.0 | **8.5** | **N 小胜** |
| 6 | 实时语音交互 | 10 | 1.0 | **5.0** | **N 胜** |
| 7 | 音乐生成 | 10 | 5.0 | 0 | L 胜 |
| 8 | 屏幕与设备视觉操作 | 10 | 4.0 | **9.0** | **N 大胜** |
| 9 | 文档/文件多模态解析 | 10 | 7.5 | **8.0** | **N 小胜** |
| 10 | 多模态测试与契约纪律 | 10 | 9.0 | 8.0 | L 胜 |
| | **合计** | **100** | **68.5** | **69.0** | |

## 2. 逐轴详拆

### 轴1 视觉理解输入（L 9 / N 8）

**LobeHub**：消息 parts 协议原生（text/image_url/video_url/audio_url/thinking，`packages/context-engine/src/processors/MessageContent.ts:132-151`）；MessageContentProcessor 把 imageList/videoList/audioList/fileList 结构化，无视觉模型注入 `VISION_DOWNGRADE_PLACEHOLDER` 不静默丢图，SVG 拒发、AVIF 媒体引用兜底、桌面本地图转 base64、工具消息 pluginState.images → image_url parts 供视觉模型复查（:31-65,672-693,552-626）；三协议转换齐（Anthropic image→base64 source/URL 预取 `anthropicMessages/messages.ts:66-141`、Google inlineData/fileData 含 m4a 容器纠偏 `contextBuilders/google.ts:58-184`、OpenAI Responses input_image/input_video `openaiResponses/inputs.ts:197-283`）。
**Neurova**：管线完整——附件注入（`chat_pipeline.py:1746`）→ visionImagePart 归一化 base64 data URL 单源（`agent/attachment_turn_injection.py:35`，视频帧与静图共用）→ 图像轮 vision 路由覆盖（`:1840`，llm_routing_overlay.py:43,91）→ 图像保留 keep_last=4（`agent/image_retention.py`）→ 双协议切片（`context/converter.py:60-92` OpenAI image_url / Anthropic image 块；`llm/providers/anthropic_client.py:55-97`）；7 provider 中 6 个声明 vision（opencode 仅 TEXT+TOOL_USE），openai 走 `multimodal_prober.py` 真图探测不作名称推断；上传入口 /v1/files/upload（files_api.py:423）与 /attachment（chat.py:884）。**差距点**：协议转换仅 OpenAI/Anthropic 两形态（无 Gemini 原生转换，gemini 走 langchain 端到端待核实）。
**判定**：对方协议面更宽、降级策略更细；本仓单源归一+真探测扎实。L 9 / N 8。

### 轴2 图像生成（L 9.5 / N 7）

**LobeHub**：41 家 provider 实现 createImage；工具 manifest 4 API（listImageModels/getImageModelParameters/generateImage/getImageGenerationStatus，`builtin-tool-image-generation/src/manifest.ts:6-151`）；ExecutionRuntime 状态机 resolveImageModel→createGenerationTopic→createImage→waitForGenerations 轮询（3s/默认 120s/上限 175s/AbortSignal，`ExecutionRuntime/index.ts:441-587`）；结果以 markdown 图片语法回对话（asset.url 非 base64，:208-237）+ /create/image 独立创作页；client/server 双执行器。扣分：画布/artboard 未承接生成物。
**Neurova**：/generation/image 端点（`api/endpoints/generation.py:291`）+ 协议矩阵实测核验（openai-images/ark/dashscope-wan 等，`llm/generators/protocols.py:55-236`，单源 facade `runtime.py`）+ aigc_studio 分镜→图生产管线（`aigc_studio/services.py:440,528`）+ 前端 ImageGenPage 走本仓端点（非旁路直连）+ 模型管理预置纪律（拒绝虚构端点，见《AIGC生成端点矩阵_2026-09-14.md》）。扣分：provider/协议广度小于对方；无独立"生成物回灌对话"的工具化形态（生成在独立页完成）。
**判定**：对方广度与工具化领先；本仓实测纪律与生产管线（分镜）是特色。L 9.5 / N 7。

### 轴3 视频生成（L 9 / N 7）

**LobeHub**：24 家 provider；工具链同构（首尾帧 imageUrl/endImageUrl、estimatedDurationMs 禁止模型自估，`builtin-tool-video-generation/src/manifest.ts:52-122`）；双层轮询（工具侧 3s + 服务端 processBackgroundVideoPolling 兜底：扣费/完成通知，`apps/server/src/services/generation/videoBackgroundPolling.ts:43-60`）；MessageVideo 播放器回对话 + /create/video 创作页。扣分：视频未用 webhook（仅音乐用），长任务 175s 上限可能频繁转后台。
**Neurova**：/generation/video 端点（generation.py:547）+ /video/status 轮询（:649）+ 协议矩阵含 Veo/SEEDANCE2/dashscope-wan（`generators/protocols.py`）+ aigc_studio 分镜→视频（首帧连续性，services.py:528）。扣分：video_to_video 无实测协议（facade 诚实报错不虚构）；无后台兜底轮询形态。
**判定**：对方工程化（双轮询+兜底+禁自估）领先；本仓协议真实但覆盖窄。L 9 / N 7。

### 轴4 语音合成 TTS（L 6.5 / N 8.5）——本仓反超

**LobeHub**：runtime 5 家专属（doubaospeech/elevenlabs/fishaudio/google/minimax）+ openaiCompatible 兼容工厂默认 TTS（`core/openaiCompatible/index.ts:528`）；服务端 tts.synthesize 路由齐全（`apps/server/src/routers/lambda/tts.ts:52-90`）。**产品面断裂**：仓内唯一消费者是 CLI（`apps/cli/src/commands/generate/tts.ts:105-107`），Web 端 useBusinessTTSProvider 是空桩（`src/business/client/hooks/useBusinessTTSProvider.ts:1-2`），聊天消息无朗读——有实现无产品面。
**Neurova**：TTS 3+ 引擎（edge_tts/sapi5/moss_nano + manager + download_service，`neurova/tts/`）+ 统一 voice_engine（voice_engine.py:36-127）；出口 /synthesize 与 /synthesize-stream 流式（`api/endpoints/audio.py:152,293`）+ 聊天流式播报接线（NeurUI ChatPage useStreamTTS/useAutoVoice，ChatPage.vue:505,923-926）+ 渠道出站三形态契约（none/audio_file/voice_bubble，`channels/voice_egress.py`，AST 守卫声明必有真出口）。
**判定**：对方实现多但产品断裂；本仓实现→端点→前端→渠道全链真实消费。N 8.5 / L 6.5。

### 轴5 语音识别 ASR/听写（L 8 / N 8.5）——本仓小胜

**LobeHub**：语音条上传转写（transcribeVoiceMessage → tRPC asr.transcribe，fileId 或 ≤3MB base64，`apps/server/src/routers/lambda/asr.ts:55-140`）；RealtimeDictationClient 产品级听写（WebSocket 协议/预取/断线重连/性能打点，`src/features/ChatInput/Dictation/client.ts:44-60`），接线于 agent/群聊/Portal/Goal 四处输入框；能力门控按"模型音频能力 vs 异构 agent 转写"分流（voiceMessageCapability.ts:23-45）。**扣分**：实时听写会话端点 `/webapi/asr/realtime/session` 不在仓内（疑似云侧网关，自托管不可用，待核实）。
**Neurova**：ASR 4 引擎（whisper 本地/remote、funasr、streaming，`neurova/asr/`）；出口 /transcribe、WS /asr/stream 流式、/minutes 语音纪要（audio.py:383,685,502）+ 前端 VoiceMinutesPage；渠道入站转写（voice_precheck.py 企业微信语音→转写→回合）+ 统一管线 voice_pipeline.py（ASR→上下文→记忆）。
**判定**：双方都产品级；对方听写交互更精细但依赖云端点，本仓全栈自托管+纪要+渠道入站。N 8.5 / L 8。

### 轴6 实时语音交互（L 1 / N 5）——本仓反超

**LobeHub**：realtime 模型仅 model-bank 类型枚举+OpenAI 三张卡（`model-bank/src/aiModels/openai/nonChat.ts:330-400`），无任何会话/WebRTC/信令实现；无语音通话功能（全仓无 RTCPeerConnection 通话代码）。
**Neurova**：SIP 话机通道（pyVoIP 本地 SIP/RTP、接听/挂断、通话内 DashScope TTS/STT，`channels/sip.py:433,208,49`）+ Twilio 语音适配器（`channels/voice.py:24`，可选依赖诚实降级）+ voice_context_module 语音上下文（置信度/情感/引擎）注入回合单源。扣分：无 DTMF/转接/会议，深度中等。
**判定**：对方占位；本仓有真实电话通道（深度中等）。N 5 / L 1。

### 轴7 音乐生成（L 5 / N 0）

**LobeHub**：createMusic 仅 fal 一家（`providers/fal/createMusic.ts`）+ RouterRuntime 路由 + 服务端 lambda/async music（预检/配额/5s 轮询上限 10min/webhook 回调，`routers/async/music.ts:132-266`）+ /create/music 完整创作页。广度窄但产品面完整。
**Neurova**：无端点、无 provider、无页面（仅 multimodal_prober.py:71 musicgen 关键词与 neurflow 背景乐模板字段）。
**判定**：L 5 / N 0。

### 轴8 屏幕与设备视觉操作（L 4 / N 9）——本仓大胜

**LobeHub**：browser 工具（设备 webview/无头 agent-browser 经 gateway 回环，`builtin-tool-browser`）+ remote-device/local-system 文件操作；无独立的"屏幕截图→视觉理解→定位操作"管线（浏览器 DOM/无障碍树为主，无 UIA/SOM 桌面视觉）。
**Neurova**：computer_use 全栈——ComputerUseManager（screenshot/click，`computer_use/__init__.py:161,391,417`）+ UIA（desktop_uia.py）+ SOM 编号标注（som.py，无 UIA 桌面降级 VLM 看图点击）+ browser_manager/frame_registry/rdp_provider/ssh_runner + **perception_gate 三闸**（感知缺口+vision 可用+每轮限额，把截图 base64 挂进 OpenAI/Anthropic 双环请求，`agent/loops/perception_gate.py`）；消费方 tool_executor.py:1422,2863、api/endpoints/computer.py、builtin_tools.py:2725；测试 30 文件。
**判定**：本仓把"屏幕"作为一等视觉模态接入理解与操作闭环，对方无对应物。N 9 / L 4。

### 轴9 文档/文件多模态解析（L 7.5 / N 8）——本仓小胜

**LobeHub**：file-loaders 覆盖 txt/csv/md/json/xml/yaml/html/代码/pdf/docx/xlsx/pptx/ipynb + 服务端切片加载器另含 epub/latex（`loaderType.ts:12-58`），解析在共享 worker 隔离；**未见 OCR 引擎接入**（图片扫描件理解待核实）。
**Neurova**：attachment_parser（PDF:174/docx:48/xlsx:82/pptx:141/html/rtf/odf/图片归一化:405）+ knowledge/document_pipeline（格式分流→文字层/OCR→分块）+ **OCR 三引擎单源契约**（RapidOCR 缺省/PaddleOCR/Tesseract，`knowledge/ocr_engines.py:67,114`，不可用如实报 ocr_unavailable）+ 知识摄入 OCR 回执（knowledge_ingestion.py:61-63,184-186）。
**判定**：对方格式广度略宽；本仓 OCR 是实打实的多模态理解增量。N 8 / L 7.5。

### 轴10 多模态测试与契约纪律（L 9 / N 8）

**LobeHub**：MessageContent.test.ts 全矩阵（视觉降级/多图/数组 parts/本地 base64/工具图片/AVIF/视频/音频，:38-989）+ unsupportedImageFormat 专项；三协议 messages/stream 测试 + inlineImageBudget；image/video ExecutionRuntime 测试 + 服务端 asr/tts/music/videoBackgroundPolling 测试。
**Neurova**：perception 双协议 parity/单次进入测试（test_perception_image_anthropic_parity.py、test_perception_image_enters_request_once.py）、视频/音频附件进回合测试、tts 10 文件+asr 9 文件+voice 17 文件、aigc 协议/预置/端点测试、computer_use 30 文件、sip 诚实测试（no_fakesuccess）。
**判定**：对方矩阵更系统（尤其协议层归一测试）；本仓覆盖广但归一化程度稍低。L 9 / N 8。

## 3. 对追平计划的指向

- 本仓可自主补、收益直接：音乐生成最小闭环（轴 7，0→有）、视频 video_to_video 协议（轴 3）、Gemini 原生视觉链路核实/补齐（轴 1 待核实项）、SIP DTMF/转写闭环（轴 6 深度）。
- 本仓特色应保持不被稀释：语音全栈自托管、屏幕视觉、AIGC 实测纪律（不照搬对方"有服务端无产品面"与"占位卡片"形态）。
- 详见同日《docs/04-plans/2026-11-22-reference-ad-multimodal-catchup-implementation-plan.md》。

## 4. 复评（2026-11-22 追平三批实施后）

| # | 轴 | 满分 | 评前 LobeHub | 评前 Neurova | 复评 Neurova | 依据 |
|---|----|-----:|--------:|--------:|--------:|------|
| 1 | 视觉理解输入 | 10 | 9.0 | 8.0 | **8.5** | Gemini 原生图片装配补齐+converter 第三形态（6ae012c91），parity/单次进入测试钉住 |
| 2 | 图像生成 | 10 | 9.5 | 7.0 | 7.0 | 本批未动图像生成 |
| 3 | 视频生成 | 10 | 9.0 | 7.0 | **7.5** | 三家 video_to_video+首尾帧落地、用户可选分派（0b1a63fd3）；真 key 实测待做 |
| 4 | 语音合成 TTS | 10 | 6.5 | 8.5 | 8.5 | 本批未动 |
| 5 | 语音识别 ASR/听写 | 10 | 8.0 | 8.5 | 8.5 | 本批未动（ASRManager 装配缺口连带修复 5282b18e9 属可用性而非能力） |
| 6 | 实时语音交互 | 10 | 1.0 | 5.0 | **6.5** | SIP DTMF 捕获进回合+通话转写闭环（49b88fcf6）；仍无转接/会议 |
| 7 | 音乐生成 | 10 | 5.0 | 0 | **3.5** | fal 闭环后端+端点+轮询取回全通（0b1a63fd3）；前端页未接、单 provider，故低于对方 |
| 8 | 屏幕与设备视觉操作 | 10 | 4.0 | 9.0 | 9.0 | 本批未动 |
| 9 | 文档/文件多模态解析 | 10 | 7.5 | 8.0 | 8.0 | 本批未动 |
| 10 | 多模态测试与契约纪律 | 10 | 9.0 | 8.0 | **8.5** | 契约棘轮四类+探测矩阵+Gemini parity（fe447b536/0a4dbe78d） |
| | **合计** | **100** | **68.5** | **69.0** | **74.5** | 复评目标 75.0 未全达：音乐前端页与 v2v 真 key 实测移交后续 |

复评口径：仅对本仓侧已实施卡对应轴调分，逐项依据见上表；对方分数不因本仓实施变化。总报告 D8 维同步 7.0→7.5（总分 94.0→95.0）。
