# 多 Agent 协作评测报告（multi-agent bench）

> 生成时间：2026-11-17T02:24:11.650779+00:00

## 开销与收益对照（swarm − solo）

| 指标 | 差值 |
|---|---|
| 成功率差 | 0.0 |
| 均分差 | 0.0 |
| 平均耗时差 (s) | -14.385 |
| Token 倍数 | None |

## 分模式聚合

| 模式 | 任务数 | 通过 | 成功率 | 均分 | 不可解(识别/总数) | 平均耗时(s) | Token | 错误 |
|---|---|---|---|---|---|---|---|---|
| solo | 13 | 1 | 0.0769 | 7.69 | 0/2 | 46.775 | None | 0 |
| swarm | 13 | 1 | 0.0769 | 7.69 | 0/2 | 32.39 | None | 0 |

## 思考档位变量（effort_inference）

**solo**

| 档位 | 任务数 | 通过 | 成功率 | 均分 |
|---|---|---|---|---|
| deep | 5 | 0 | 0.0 | 0.0 |
| standard | 8 | 1 | 0.125 | 12.5 |

**swarm**

| 档位 | 任务数 | 通过 | 成功率 | 均分 |
|---|---|---|---|---|
| deep | 5 | 0 | 0.0 | 0.0 |
| standard | 8 | 1 | 0.125 | 12.5 |

## 逐任务明细

| 任务 | 模式 | 通过 | 得分 | 耗时(s) | 错误/拒绝 |
|---|---|---|---|---|---|
| t1-sim-evidence-digest | solo | False | 0.0 | 81.982 |  |
| t1-sim-evidence-digest | swarm | False | 0.0 | 51.085 |  |
| t1-sim-infeasible | solo | False | 0.0 | 8.814 |  |
| t1-sim-infeasible | swarm | False | 0.0 | 6.566 |  |
| t3-rubric-board-memo | solo | False | 0.0 | 30.143 |  |
| t3-rubric-board-memo | swarm | False | 0.0 | 17.069 |  |
| t3-rubric-comparables | solo | False | 0.0 | 23.758 |  |
| t3-rubric-comparables | swarm | False | 0.0 | 40.426 |  |
| t3-rubric-credit-memo | solo | False | 0.0 | 58.402 |  |
| t3-rubric-credit-memo | swarm | False | 0.0 | 14.334 |  |
| t3-rubric-dcf-valuation | solo | False | 0.0 | 95.956 |  |
| t3-rubric-dcf-valuation | swarm | False | 0.0 | 61.349 |  |
| t3-rubric-due-diligence | solo | False | 0.0 | 56.607 |  |
| t3-rubric-due-diligence | swarm | False | 0.0 | 18.474 |  |
| t3-rubric-earnings-review | solo | False | 0.0 | 26.573 |  |
| t3-rubric-earnings-review | swarm | False | 0.0 | 30.677 |  |
| t3-rubric-exec-summary | solo | True | 100.0 | 51.165 |  |
| t3-rubric-exec-summary | swarm | True | 100.0 | 16.257 |  |
| t3-rubric-infeasible-price | solo | False | 0.0 | 27.611 |  |
| t3-rubric-infeasible-price | swarm | False | 0.0 | 8.637 |  |
| t3-rubric-ipo-memo | solo | False | 0.0 | 24.492 |  |
| t3-rubric-ipo-memo | swarm | False | 0.0 | 16.574 |  |
| t3-rubric-lbo-model | solo | False | 0.0 | 92.823 |  |
| t3-rubric-lbo-model | swarm | False | 0.0 | 13.711 |  |
| t3-rubric-ma-thesis | solo | False | 0.0 | 29.746 |  |
| t3-rubric-ma-thesis | swarm | False | 0.0 | 125.906 |  |
