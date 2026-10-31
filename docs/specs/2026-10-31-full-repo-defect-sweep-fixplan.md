# 全库缺陷清扫修复计划（2026-10-31 体检 55 条 → 分批修复）

- **来源**：2026-10-31 六片只读体检（core+security / knowledge / api/endpoints / agent 链路 / 辅助子系统 / NeurUI），55 条，其中 4 条 P1 经人工复核属实。
- **台账**：本计划整体登记为 §6-448（`audit-reports/simplification-audit-2026-10-05.md`）；每批修复落格从 §6-449 起现查。
- **纪律**：每批先红后绿（红自证只 stash 本批生产文件）→ 最小修复 → A/B → 单任务单提交；每批台账落格。本文是计划不是实施授权的豁免——每格仍按教义执行。

## 批次划分（按危险度与改动面排序）

### 批 S：安全四条（P1，先修）
| 编号 | 位置 | 缺陷 | 红灯判据 |
|---|---|---|---|
| S1 | `api/endpoints/console_files.py:44-82` | console 附件零属主隔离（任意登录用户可读/删他人件） | user1 上传 → user2 list 不含 / download+delete 得 404；修前红 |
| S2 | `api/endpoints/skill_pool_api.py:616-715` | 待审技能/经验审批六腿漏 `_require_agent_access`（写他人 agent 资产） | user2 调 agent-A 的 approve/reject/pending → 403；修前红 |
| S3 | `api/endpoints/knowledge_graph_api.py:291-328` | 图谱补建无 admin 校验 + `list_knowledge` 无租户/可见性过滤（跨租户抽取） | 非 admin 得 403；仅可见条目被抽取 |
| S4 | `agent/memory_retrieval_chain.py:668-696` | 检索缓存键无 user/agent 维度且无 TTL（跨用户串味+永不过期） | 同 query 异 user 第二次检索不得返回他人缓存；缓存条目带时间戳 |

### 批 F：假成功三兄弟（P1）
| 编号 | 位置 | 缺陷 | 红灯判据 |
|---|---|---|---|
| F1 | `api/endpoints/console.py:724-1203` | 非流式 chat 恒回 200+空 reply（agent.chat 未调用） | stream=False + 真 agent → reply 非空且为 agent 产出 |
| F2 | `api/endpoints/console.py:2420` | WS 异常吞成 "Echo: …" 假成功 | agent.chat 抛错 → WS 收 error 帧而非 Echo |
| F3 | `api/endpoints/memory/eki.py:248/279/358` | 三腿参数键名与真身错位（假数据/谎报成功/参数丢弃） | 按真身签名逐腿契约断言（process 读 observation、batch-update 走 updates、decay 用 hours_ahead） |

### 批 D：数据正确性两条（P1）
| 编号 | 位置 | 缺陷 | 红灯判据 |
|---|---|---|---|
| D1 | `knowledge/repository.py:2140-2166` | supersede_old 漏 `_save()`+governance 同步——重启后裁决反转 | 裁决 supersede_old → 重新 `_itemsFromNarratives` 水合 → 旧条目不再出现 |
| D2 | `knowledge/foundation/admission.py:329` | 内容去重漏传 tenantId（跨租户折叠） | 租户 B 写入与 A 同内容 → B 租户可见自己的行、A/B 互不串 |

### 批 C：并发正确性（P1）
| 编号 | 位置 | 缺陷 | 红灯判据 |
|---|---|---|---|
| C1 | `agent/loops/openai_loop.py:589,734` + `anthropic_loop.py:62` | `_rounds`/`_gate_runner`/`_round_usage` 挂 per-agent 单例（交叠会话互踩） | 状态并入 TurnRunState；两轮交叠互不清零（单测造交叠） |
| C2 | `agent/memory_retrieval_chain.py:388-398` | 主源命中后被后续检索器覆写 | Annotation(1.0) 命中后再跑 MoE/Fallback → primary 仍是 Annotation |
| C3 | `agent/knowledge_retriever_adapter.py:279` 等 | 三路同步重 IO 直跑事件循环 | retrieve 内部重 IO 经 to_thread（事件循环可被 wait_for 抢占） |

### 批 R：资源与可靠性（P1/P2）
| 编号 | 位置 | 缺陷 |
|---|---|---|
| R1 | `skills/creation_governance.py:153-156` | EvidenceStore 旧库迁移必炸（ALTER+UPDATE 撞隐式事务）——回填从未成功 |
| R2 | `agent/chat_pipeline.py:514-519` | finish_task 裸奔在 finally（清理失败炸掉已生成的回复） |
| R3 | `core/connection_pool.py:166` | `_created_count` 建连失败不回退（5 次失败整池砖死） |
| R4 | `evolution/closed_loop.py:128-136` | 自适应权重 save 非原子（崩溃归零） |
| R5 | `collaboration/outbox_handler.py:362-421` | 失败态不落盘/退避无人读/死信留原文件（毒事件无限重试） |
| R6 | `core/trace_recorder.py:364` | 轨迹文件只写不删（磁盘慢漏+明文滞留） |

### 批 X：其余 P2（按域小批）
knowledge：三套连接无 WAL/busy_timeout；治理端点租户过滤不一致；changed_fields 恒空；注入计数全记 default。agent：跨天取尾部倒置；死缓存；swarm/溢出回写裸 create_task。api：eki 之外的旧版通知参数、会话排序跨用户写、files approve/reject 不落盘、上传无上限。杂项：守卫双主体句误报（本会话自产）；结晶器 confirm_pending 同 key 双写。前端：neuron.ts 裸 axios 401；CanvasDesigner `isDisposed` 漏 `.value`；GraphWorkbench 切 Agent 串显；GraphExplorer3D WebGL 泄漏；KnowledgePage 搜索分页断链/导入计数不重置；`.optimized` 同名 store 雷；主题守卫盲区。core：EventBus 跨线程投递；HealthCheck 幻影旋钮；MemoryCache TTL/shutdown；safe_paths O_NOFOLLOW；ApprovalManager 锁内回调。

## 执行状态

| 批 | 状态 | 提交 |
|---|---|---|
| S | ⬜ | — |
| F | ⬜ | — |
| D | ⬜ | — |
| C | ⬜ | — |
| R | ⬜ | — |
| X | ⬜ | — |

每批完成后回填本表（提交号 + 台账格号）。
