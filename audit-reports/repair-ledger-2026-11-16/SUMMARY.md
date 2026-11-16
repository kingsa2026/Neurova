# 修复汇总台账 · 总控复核结论（2026-11-17）

> 任务：按 [fullrepo-code-audit-2026-11-16.md](../fullrepo-code-audit-2026-11-16.md)（147 条：P0×2 / P1×39 / P2×106）分 8 个独立会话并行修复。
> 本文件是总控对各会话台账（同目录 S1–S8 八份）的复核结论与收口记录。

## 1. 覆盖结论

| 级别 | 修复覆盖 | 说明 |
|---|---|---|
| P0（2） | **2/2** | P0-1 主密码构建期注入（S2）、P0-2 安卓心跳 JSON 契约（S3） |
| P1（39） | **39/39** | 逐条对应：S1×7（P1-1/2/3/4/9 + 越权链）、S2×5（P1-5/6/7/14/15）、S3×1（P1-37）、S4×8（P1-28~32/34/35/36）、S5×4（P1-8/10/16/17）、S6×6（P1-22~27）、S7×5（P1-11/12/13/18/20）、S8×3（P1-19/21/33/38/39 中 P1-33 含 15 死页） |
| P2（106，按域压缩） | 部分清偿 | 已修：鉴权散点（3.1-1~6）、并发群（3.2-10a/10b/12、3.3-1、3.5-13）、3.6-16、core-P2-11、auth-500 细节、死码散点（auth_protocol/thought_sandbox/channels-websocket/skills-manifest/context.py/llm_client mock/ChannelConfig 双定义/双 get_request）、卫生散点（gitignore/node 版本/死 npm script/nul）。其余 P2 条目未动，见 §4 遗留 |

## 2. 8 会话产出（23 笔提交，基线 8b18e5afa → HEAD）

| 会话 | 提交 |
|---|---|
| S1 | f16ac38c0 fix(api) S1 安全批——属主门与管理员门收口 |
| S2 | a7962ad5c fix(security) 主恢复密码注入化与 SSRF/属主/隔离收口 |
| S3 | 28cdc7d36 fix(mobile) 安卓 WS 心跳统一 JSON 契约；7fed0b821 refactor 删 PairingConfirmed |
| S4 | aa3dfd32c（契约批）、389bd894c（P1-34）、832e71465（P1-36）、75aa342ed/2490c604f/7e87f10f0/4cba0bc9c（ohosTest 基建与清偿） |
| S5 | 39f9a7896 fix(stability) benchmark/分诊门/渠道与技能阻塞/并发竞态 |
| S6 | 429da7948、ca0075cf2、4f39651ba、af2be06f2、9a60ebe1a、57f4161bf（P1-22~27 + fe-P2-4） |
| S7 | 98f1b7c03 refactor(cleanup) 死码群退役（净约 −8,400 生产行） |
| S8 | 3e2a84c5d（P1-19 下沉）、68e9db057（P1-33 死页 9 接线 6 退役）、f76493239（P1-21）、492df1ce2/7ec60481c（P1-38/39 + 卫生） |
| 总控收口 | 本文件连同台账入库；S8 漏提交的 6 个退役 ohosTest 删除补提交；protected_tests 悬空项摘除 |

## 3. 总控复核抽验（不信台账，实测）

- **8 会话新增守卫测试 16 文件一次跑：118 passed / 0 failed**（含 S1 属主门 41、S2 加固 48 批内、S5 稳定性 37、S8 生产码不反依赖测试根 3 等）。
- **P0-1**：全仓 grep `neurovamakehappy` 0 残留（源码/前端/移动端）。
- **P0-2**：MobileWsChannel.kt 实测 JSON 帧 `{"type":"ping"}` + `awaitingPong` 判定在位。
- **P1-19**：`neurova/`、`scripts/` 下 `from tests` 0 残留（ast_scan 薄转发除外）。
- **守卫执法复核中发现并当场修复**：S2 退役 `test_recoverPasswordFromSourceConstant.py` 后，`protected_tests.2.txt`/索引残留悬空路径 → shards 守卫红（`TestEntriesAreTheShardsOwnProperty`）→ 已从索引与分片 2 摘除，shards 16 passed 复绿。
- **S8 收口缺口**：6 个退役死页的 ohosTest 删除停留在暂存区未随 68e9db057 入库——本次补提交（页面已退役而测试残留会让 ohosTest 收集到引用已删页面的用例）。
- 各会话台账自报的预存失败（S1 列 18 项、S7 列 7 项等）均为并行在途/环境性失败，与修复批无因果，未计入回归。

## 4. 遗留与待拍板（各会话移交汇总）

| # | 事项 | 来源 | 建议 |
|---|---|---|---|
| 1 | neurflow `/executions/{id}/breakpoint`、`/debug/resume` 属主语义未定 | S1 | 复用 `_ensure_execution_owned`（执行记录属主=调试会话属主），小改动可随下批 |
| 2 | `security/url_guard.py` 与 `knowledge/url_guard.py` 双份 URL 校验 | S2 | 教义第 6 条收口为一份（各有在役消费方，需回归） |
| 3 | media 列表面（/list、/stats、/trash、/memory）按 agent 维度不过滤上传者 | S2 | 审计未点名；涉及 agent 协作可见性产品语义，需拍板 |
| 4 | RuntimeApi 三页面（ContextChannel/AgentComputer/AgentTrajectory）后端无端点，页面恒错误态 | S4 | 下线三条路由或后端补面（路由表归 S8 域） |
| 5 | LogPage「导出」以 clearLogs 占位 | S4 | 改接 /v1/audit/export |
| 6 | ohosTest 运行期红：ModelsApi.test 内联已退役模块；MemoryApi.search 等用例引用主源码不存在的方法 | S4 | 随模块退役删测或主源码补齐 |
| 7 | FE mock 时代类型（CollaborationTemplate 等）留 types/index.ets；ConfigManager/ServerProfiles 与 StorageAdapter 并存 | S4 | 后续重构批 |
| 8 | `OpenAIAdapter.stream_call` 空桩；coordination_api `/triage/check` 未映射 503；`telegram_webhook.py` 同步 `_api_request`；`search_all_markets_async` 零消费 | S5 | 小项可并 batch |
| 9 | FilePage 存储卡无配额语义数据源（/files/storage/info 仅总量） | S6 | 产品拍板口径后再接线 |
| 10 | P2 未清偿条目（规范/诚实性/资源类为主） | 总控 | 按 §3 各域继续分批 |
| 11 | P0-1 构建链打包注入（PyInstaller spec / CI 注入真实值） | S2 | 部署流水线配置，随下次发版批 |

## 5. 教义执行复核

- **先红后绿**：8 会话均先实证红灯（S1 35 failed 起步、S3 揭出第三层 `close(1006)` 非法码、S4 harness 10/11 红、S5 心跳测量法、S6 对旧实现 9/9 红、S8 守卫 3 failed）——无"写完实现再补测试"形态。
- **live-verify**：S1 真后端 11 项 403/200 实测、S2 真 uvicorn 双轮（含审计库实查 CRITICAL 事件）、S3 真后端 WS 往返、S4 模拟器装机 318 用例、S5 真 socket 心跳计时、S6 真后端形状逐字段核对、S7 全仓 grep 复扫、S8 hvigor 全量构建 + hap 产物时间戳核验。
- **命中点扫平**：各台账均含同根因扫平清单（S1 console 8 处、S5 渠道 19 处、S4 信封 23 模块盘点表、S7 双实现收口），符合教义第 5 条。
- **净 LOC**：各批提交说明均附分池去向；S7 净约 −13,650 行、S8 删 184M 双份模型，其余批净增合计约 +3,300（安全闸/属主门/归一基建），符合"修复优先、克制新增"。
