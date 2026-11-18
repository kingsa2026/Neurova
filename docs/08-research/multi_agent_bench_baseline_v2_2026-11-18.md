# 多 Agent 协作评测报告 v2（multi-agent bench，新判据口径）

> 生成时间：2026-11-18T00:52:02Z（report_id: bench-20261118T005202Z-989f4e）
> 驱动：真装配链（create_app + _on_startup + 进程内 benchmark agent），provider=api.mosi.cn/v1 · nex-n2.6，两模式共 26 任务、零错误
> 原始 JSON：[multi_agent_bench_baseline_v2_2026-11-18.json](multi_agent_bench_baseline_v2_2026-11-18.json)（由 S1-1E 报告生产点落盘后归档）
> 与 v1 对照：[multi_agent_bench_baseline_2026-11-17.md](multi_agent_bench_baseline_2026-11-17.md)（旧口径，保留作对照）

## 本轮新口径（S1 评测地基落地后首次真模型实测）

- **usage 回传**：TaskOutcome 携带 prompt/completion/total tokens、耗时、步数、工具数（1A）；
- **轨迹效率判据**：expect_trajectory 可用，数据源=P3-2 span trace 与台账计数（1B，含 S15 接线的轨迹生产者）；
- **任务隔离记忆**：taskIsolatedMemory 默认开启，报告已注记（1C，对治 H-7 实测的跨任务串扰）；
- **T1 重设计**：虚构来源标记任务改为"依据给定材料归纳"（1D 路 a）；
- 评分口径与 v1 完全一致（字面量量规），两轮分数可直接对比。

## 开销与收益对照（swarm − solo）

| 指标 | 差值 |
|---|---|
| 成功率差 | 0.0 |
| 均分差 | 0.0 |
| 平均耗时差 (s) | -10.287 |
| Token 倍数 | **0.857**（v1 为 None——usage 缺失；本项为 F2 补全后的新读数） |

## 分模式聚合

| 模式 | 任务数 | 通过 | 成功率 | 均分 | 不可解(识别/总数) | 平均耗时(s) | Token（prompt/completion） | 步数 | 工具数 | 错误 |
|---|---|---|---|---|---|---|---|---|---|---|
| solo | 13 | 1 | 0.0769 | 7.69 | 0/2 | 33.275 | 521,138（461,916/59,222） | 20 | 0 | 0 |
| swarm | 13 | 1 | 0.0769 | 7.69 | 0/2 | 22.988 | 446,748（398,973/47,775） | 17 | 0 | 0 |

## 思考档位变量（effort_inference）

**solo**：deep 6 任务 0 通过；standard 7 任务 1 通过（0.1429）
**swarm**：deep 6 任务 0 通过；standard 7 任务 1 通过（0.1429）

## 逐任务明细（含 usage）

| 任务 | 模式 | 通过 | 得分 | 耗时(s) | Token |
|---|---|---|---|---|---|
| t1-sim-evidence-digest | solo | False | 0.0 | 13.2 | 15,194 |
| t1-sim-evidence-digest | swarm | False | 0.0 | 11.3 | 17,053 |
| t1-sim-infeasible | solo | False | 0.0 | 7.0 | 16,517 |
| t1-sim-infeasible | swarm | False | 0.0 | 5.6 | 17,363 |
| t3-rubric-board-memo | solo | False | 0.0 | 26.0 | 19,723 |
| t3-rubric-board-memo | swarm | False | 0.0 | 15.5 | 22,884 |
| t3-rubric-comparables | solo | False | 0.0 | 28.0 | 29,024 |
| t3-rubric-comparables | swarm | False | 0.0 | 17.6 | 29,678 |
| t3-rubric-credit-memo | solo | False | 0.0 | 33.0 | 56,118 |
| t3-rubric-credit-memo | swarm | False | 0.0 | 13.8 | 29,473 |
| t3-rubric-dcf-valuation | solo | False | 0.0 | 81.5 | 91,898 |
| t3-rubric-dcf-valuation | swarm | False | 0.0 | 88.6 | 118,177 |
| t3-rubric-due-diligence | solo | False | 0.0 | 46.3 | 63,317 |
| t3-rubric-due-diligence | swarm | False | 0.0 | 19.7 | 33,529 |
| t3-rubric-earnings-review | solo | False | 0.0 | 28.9 | 36,409 |
| t3-rubric-earnings-review | swarm | False | 0.0 | 13.6 | 36,856 |
| t3-rubric-exec-summary | solo | **True** | 100.0 | 14.4 | 16,480 |
| t3-rubric-exec-summary | swarm | **True** | 100.0 | 8.8 | 16,822 |
| t3-rubric-infeasible-price | solo | False | 0.0 | 10.3 | 19,140 |
| t3-rubric-infeasible-price | swarm | False | 0.0 | 5.5 | 19,513 |
| t3-rubric-ipo-memo | solo | False | 0.0 | 19.8 | 29,435 |
| t3-rubric-ipo-memo | swarm | False | 0.0 | 14.1 | 28,553 |
| t3-rubric-lbo-model | solo | False | 0.0 | 68.7 | 80,208 |
| t3-rubric-lbo-model | swarm | False | 0.0 | 13.1 | 23,901 |
| t3-rubric-ma-thesis | solo | False | 0.0 | 55.6 | 47,675 |
| t3-rubric-ma-thesis | swarm | False | 0.0 | 71.7 | 52,946 |

## 与 v1 对照（同模型同任务集，口径升级）

| 维度 | v1（2026-11-17） | v2（本轮） |
|---|---|---|
| 通过率 | solo/swarm 均 1/13 | solo/swarm 均 1/13（持平） |
| Token 倍数 | None（usage 未回传） | **0.857**（swarm 更省） |
| 平均耗时差 | -14.385s | -10.287s（swarm 更快，两轮一致） |
| 记忆隔离 | 未隔离（实测串扰） | taskIsolatedMemory 默认开 |
| T1 族 | 虚构来源任务（真模型不可用） | 材料归纳重设计（仍未通过，诚实记录） |
| swarm 机制实证 | 邮箱/闸门 | + 候选制 CAS 合入经审批链 L0 自动批准上墙（真实运行中触发） |

## 诚实结论

1. 通过率与均分两轮完全一致（1/13、7.69）：低分仍由**字面量量规严格性**主导（markdown 标题 vs【】格式要求即 0），这是 harness 口径特性，不是模型能力或协作机制的变化——两轮对照的价值在机制验证而非分数。
2. **F2 缺口闭合**：usage/轨迹列从 None 到全量（token 倍数 0.857），"新判据+记忆隔离下的真模型复跑"完成，F2 满锚的实证环节补齐。
3. swarm 相对 solo **更快且更省**（-10.3s、0.857× tokens）且通过率持平——协作开销为负增益，与 v1 方向一致。
4. 真实运行中，S4 候选制的 CAS 合入经审批链 L0 自动批准落地（merge_candidate 审批事件实测产生），S17 请求级归档全程留痕——新机制在真模型负载下工作正常。
