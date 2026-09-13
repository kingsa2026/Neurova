# Neurova × PRINTFILM × 火宝短剧：AIGC 对标研究与落地终态

日期：2026-09-13/14 ｜ 任务：研究 `gitcc:muliku/chuangyin-printfilm` 结合 Neurova AIGC 页面现状进行完善，并打通画布工作流。

## 1. 研究对象与可达性

- gitcc 仓库 `muliku/chuangyin-printfilm` 为**私有/受限**（匿名 API 404、git 401、网页 JS 防护），其公开源为 GitHub：
  - `yi1108/printfilm`（**MIT**）：AI 科普视频与漫剧创作平台。FastAPI + PostgreSQL + React 19，生图/生视频走火山方舟 Seedream/Seedance，文本 OpenAI 兼容，配音豆包 TTS/edge-tts。**已克隆全量研究**。
  - `chatfire-AI/huobao-drama`（火宝短剧，**CC BY-NC-SA 4.0 非商用**）：Nuxt3 + Hono + Drizzle + Mastra agents + FFmpeg 的一站式短剧生成平台。**仅借鉴流程思想，零代码抄用**（Neurova 为商业分发项目）。

## 2. 两项目机制与取舍

| 机制 | PRINTFILM | 火宝 | Neurova 采纳 |
|---|---|---|---|
| 统一任务平台 | 租约+调度+轮询+看门狗+事件账（多 worker 向） | 简单进度+批量重试 | 账本全类型落账 + 重启恢复轮询（单进程轻量版）；租约调度**不做**（过度工程） |
| 模板系统 | 模板驱动多视觉风格，启动写库 | 风格/画幅项目锁注入每镜提示词 | 内置「AI 短剧一键成片」模板启动种子 + 风格注入每镜 |
| 生产流水线 | 主题→分镜→图→视频→旁白→FFmpeg | 小说→剧本→资产→分镜→提示词注入→批量→拼接 | **挂 Neurova 自家 NeurFlow 画布引擎**（drama_nodes 升级成真 + scene-gen/voice-over 批量扇出），不做平行 studio 模块 |
| 成片合成 | FFmpeg 全片拼接 | FFmpeg 逐镜头+字幕+拼接 | 有 FFmpeg→concat 真合成；无→**连播清单 manifest + 前端连播播放器**（诚实降级，禁假文件名） |
| 治理 | 计费钱包/管理后台/开放 API | 无 | 计费**不做**；产物鉴权收口（?access_token= + 账本属主） |
| 创作记录 | 个人中心工具创作记录+下载 | 进度导轨+一键重试 | AIGC 页「记录」Tab（消费任务账本，kind 过滤+下载+未决自动刷新） |

## 3. Neurova AIGC 原状核心缺陷（修复前）

1. 三套并行客户栈：REST `protocols.py`（实测矩阵）/ 画布 `external_api.py`（未验目录）/ 渠道僵尸 B 栈（六件虚构端点实现）。
2. 包零导出 → IM 渠道 AIGC 命令恒 ImportError；manager NameError 被吞；`RequestType` 大小写错配。
3. 图像/视频端点不接 auto 路由，`model="auto"` 当真实模型名透传必然 4xx。
4. 音频返回二进制 vs 前端 JSON 取 → 恒空；图像 Tab「模板」错接 Docker 构建模板接口。
5. 图像/音频不落任务账本；`GET /generation/tasks` 前端零消费；账本路径 CWD 相对；`unfinished()` 重启恢复承诺零接线。
6. OPENAI_COMPAT 图生图静默丢参考图；产物匿名可越权读取。
7. 画布 drama 节点半实现：storyboard 非 LLM、voice-over 未接 TTS、video-compose 返回**不存在的假文件名**；节点注册时序导致新进程画布被误拒。

## 4. 落地清单（六提交全部红绿灯 TDD 验证）

| 批次 | 提交 | 内容 |
|---|---|---|
| 0 | `fix(aigc): 僵尸B栈修通` | runtime.py 单源 facade（凭据/落盘搬移+ProtocolGenerator+LegacyBytesAdapter），base 契约字段转正→渠道三 mixin 零改动复活；渠道 `_download_url` 本地分支；删六件假协议（净 **-3235** 行）；账本 source/execution_id |
| 1 | `fix(aigc): P0 契约修复` | image/video auto 路由；音频 JSON+落账；风格模板注入 prompt（删 Docker 错源）；账本绝对路径；图像落账 |
| 2 | `feat(aigc): 历史+恢复` | 「记录」Tab（kind 过滤/下载/未决自动刷新）；recovery.py 收口轮询单源+启动恢复循环；/tasks 补 url/source；generation.ts 全量对齐 |
| 3 | `feat(aigc): 参考图+鉴权` | BearerOrQuery 查询凭证；/files/{name} 鉴权路由替代匿名挂载；ref_images 允许根补 storage；OPENAI edits multipart；前端上传闭环 |
| 4a | `feat(neurflow): 引擎+节点成真` | loop items_from 数组迭代；canvas_bridge sync_all 时序修复；storyboard LLM 分镜+风格注入；voice-over 真 TTS；scene-gen/voice-over 批量扇出；video-compose 禁假文件名（FFmpeg concat / slideshow manifest）；external_api await 修复；短剧模板+启动种子 |
| 4b | `feat(aigc): 创作Tab打通画布` | useWorkflowRun（实例化→run/stream→SSE→产物）；AIGC 创作 Tab + SlideshowPlayer；WorkflowPage 从模板新建；dock video 全链路 |

测试终态：后端生成链/画布链/渠道全量绿（仅 3 条**预存**失败经 worktree 基线甄别：cron trigger dispatch、evolution 节点签名 ×2，与本次改动面不相交）；前端 vue-tsc 0 错、vitest 1428 全绿。

## 5. 缓后台账（登记不修）

1. **@角色/资产一致性注入**（火宝 extractor 资产库 + 参考图映射）——需资产提取 LLM 节点 + 项目资产库，独立排期。
2. **FFmpeg 二进制分发**：成片真合成依赖打包包含 ffmpeg（用户硬约束：打包项须用户决定）。
3. **AIGC 用量计费/统计**：usage_history 无图像/视频维度（PRINTFILM billing 需定价体系，本地场景价值低）。
4. **任务租约调度/看门狗**：多 worker 扩展时再接（PRINTFILM scheduler/poller/watchdog）。
5. **开放 API key 面**（printfilm /api/v1 + X-Api-Key）。
6. **keyframe_to_video / video_to_video**：待 WAN 百炼临时上传与 v2v 实测协议接入（facade 现诚实报错）。
7. **CanvasDesignerPage 改用 useWorkflowRun 内核**（现为同逻辑抽取版，画布页内联实现未迁移——避免大文件行为回归单独做）。
8. **Harmony AIGC 页全 mock**（TODO M5）。
9. **firemux/Huobao 式一键写入三项配置**的引导页（可选）。
10. 上述 3 条预存失败测试（cron/evolution）待其归属线程修复。

## 6. 合规声明

- PRINTFILM 部分机制参考自 MIT 许可仓库（允许商用衍生，未直接复制源码，按 Neurova 架构重写）。
- 火宝短剧为 CC BY-NC-SA 4.0：本项目**未复制其任何代码**，仅借鉴公开文档描述的工作流阶段模型。
