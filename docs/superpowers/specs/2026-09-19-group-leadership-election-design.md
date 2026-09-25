# 群领导选举（Group Leadership Election）设计规格

- 日期：2026-09-19
- 状态：待评审（architectural）
- 关联：本设计是"actionability 门控（LLM 路由设置 opt-in）"的解耦后续，专治"多我方 agent 同群争答/回声"。

## 1. 背景与目的

外部群聊渠道（Discord/Telegram/飞书/钉钉/企业微信等）中，**同一物理群可能挂载多个我方 agent**（各自独立适配器）。当一条消息到达，多个我方 agent 会各自经 `channel_router` 收到并各自决定应答 → 产生：

- 对**人类**消息的**重复应答**（N 个 agent 回同一条）；
- 对**某我方/对端 bot** 消息的**互相应答回声风暴**（agent A 回 → agent B 视为新消息再回 → A 再回…）。

既有原语已部分缓解但未根治：`require_mention`（仅被 @ 应答）适合单 bot 群，但无法在"多我方 agent 同群、且都满足应答条件"时决定**由谁**应答。

**目标**：为每个群聊 `(channel_type, chat_id)` 选出**唯一 responder（群主/leader）**，同一时刻只允许 leader 应答；leader 失效时按租约自动接管。默认关闭、opt-in、fail-open，绝不因此吞掉人类消息。

## 2. 范围与非目标

范围：仅**外部渠道群**的应答仲裁，**同进程单实例**部署。

非目标（明确排除，YAGNI）：
- 跨进程/分布式租约与 leader 选举（拓扑已定为同进程）；
- 重启后 leader 持久化（内存态，重启首条消息重选）；
- 应用内 ACP/`AgentScheduler` coordinator 复用（不同域）；
- 复杂加权/排名选举算法。

## 3. 术语

- **group_key**：`(channel_type, chat_id)` 元组，唯一标识一个外部群会话面。
- **leader / 群主**：当前被授权代表我方在该群应答的 agent_id。
- **租约（lease）**：leader 的一次任期，`expires_at = now + ttl`（monotonic 时钟）。
- **续租（renew）**：leader 每处理一条该群消息即刷新 `expires_at`。
- **接管（takeover）**：租约到期或无 leader 时，由到达的候选申领为 leader。

## 4. 组件与接口

新增模块 `neurova/channels/group_leadership.py`：

```
@dataclass
class LeaderRecord:
    agent_id: str
    expires_at: float        # monotonic 秒

class GroupLeadershipArbiter:
    """进程内群领导仲裁器（单例，线程安全）。"""
    def may_respond(self, group_key, agent_id, *, now=None, ttl=None) -> bool:
        """返回本 agent 此刻是否可代表该群应答：
        - 无 leader / 租约过期：agent_id 申领为 leader，expires_at=now+ttl，True。
        - 已是 leader：续租，True。
        - 否则：False（本 agent 该轮静默）。"""
    def current_leader(self, group_key) -> Optional[str]: ...
    def _evict_stale(self, now) -> None: ...   # 回收长期空闲过期记录，防无界增长

get_group_leadership_arbiter() -> GroupLeadershipArbiter   # 单例工厂
reset_group_leadership_arbiter() -> None                   # 测试/重置
```

单一收口接线：`neurova/channels/channel_router.py` 的 `_handler`（已持有 `agent_id`、`chat_id`、`message.channel_type`）——在访问控制与 origin 判定之后、`agent.chat` 之前调用：

```
group_key = (message.channel_type, message.chat_id)
if not arbiter.may_respond(group_key, agent_id, ttl=lease_ttl):
    meta["leadership"] = {"granted": False, "group": group_key}
    return None            # 非 leader：本轮静默，不回发
meta["leadership"] = {"granted": True}
```

## 5. 数据结构与状态机

- 内存 `Dict[group_key, LeaderRecord]` + `threading.Lock`；纯进程内、无持久层。
- 每次 `may_respond` 决策：`未持有 | 已过期→申领 | 本人→续租 | 他人未过期→拒`。
- 接管并列（同刻多候选）：同进程 + 锁，**到达序**决定；不引入真并发竞争。可选按稳定优先级 tie-break（默认关，见开放项）。
- 回收：`may_respond` 内部惰性清理 `expires_at` 远早于 now 且非本人的记录；进程重启全部状态清空、首条消息重选。

## 6. 与既有机制的协作与优先级链

一条群消息进入 `channel_router._handler` 后的判定顺序：

1. **访问控制（既有）**：`group_chat_strategy`/whitelist/`require_mention`——不通过则按现有逻辑忽略。
2. **origin 判定（既有）**：`turn_origin` ∈ {human, bot_peer, …}。
3. **领导选举（本设计）**：非 leader → 静默 `return None`；leader 放行。人类与 bot 消息同规则（保证"一个"应答）。
4. **actionability 门控（既有，可选叠加）**：即便 leader，若 `bot_peer` 且近期无人类介入，仍可判不可行早退（回声双重保险）。

**人类消息永远由 leader 应答**——选举只收敛"由哪个我方 agent 回"，绝不因选举使人类落空。

## 7. 失效接管与时序

- leader 活跃即持续续租，任期稳定。
- leader 掉线/被静音/崩溃 → 停止续租 → `ttl` 后租约到期 → 该群下一条消息的任意我方候选到达即接管并应答。
- 建议 `ttl` 默认 **90s**（明显大于正常回复间隙、小于可接受的故障感知窗口）。可配置。

## 8. 错误处理 / fail-open / kill-switch

- 总开关 `group_leadership_enabled`（默认 False）关闭时：完全跳过选举，行为与现状一致。
- `chat_id` 缺失、配置读取异常、arbiter 内部异常 → **fail-open**：视为"允许应答"（退回现有 `require_mention` 语义），**绝不因仲裁故障导致全员静默或误吞**。
- env 逃生门 `NEUROVA_GROUP_LEADERSHIP`（on/off）优先级最高（运维强制/禁用）。

## 9. 配置面

并入 `routing` 设置分区（与 actionability 同族，前端"系统设置 → LLM 路由设置"）：
- `group_leadership_enabled: bool = False`
- `group_lease_ttl_seconds: int = 90`

读取沿用 `get_actionability_config` 同款 `load_app_settings().get("routing")` + env 兜底；新增 `get_group_leadership_config() -> (enabled, ttl)`。前端两个控件（开关 + TTL）列为可选后续。

## 10. 测试策略（TDD 垂直切片）

纯逻辑（`GroupLeadershipArbiter`，时间注入）：
1. 首个候选申领成为 leader 并可应答；
2. leader 再次调用→续租、`current_leader` 不变；
3. 非 leader 在租约内→拒应答；
4. 租约过期→其他候选到达即接管；
5. 过期记录被回收（无界增长防护）；
6. 开关关闭→不改变现状。

集成（`channel_router`）：
7. leader 正常回发、非 leader `return None` 静默；
8. leader 掉线后下一条由新 leader 应答；
9. 人类消息始终由 leader 应答（不吞）；
10. `may_respond` 抛异常→ fail-open 放行；
11. kill-switch/无 chat_id→跳过选举，退回 `require_mention` 行为。

## 11. 涉及文件与改动面

- 新增 `neurova/channels/group_leadership.py`（~90 行）+ 单测。
- `neurova/channels/channel_router.py`：+~8 行接线（访问控制/origin 之后、`agent.chat` 之前）。
- `neurova/core/app_settings.py` `ROUTING_DEFAULTS`：+2 键。
- `neurova/agent/actionability.py` 或 `group_leadership.py`：`get_group_leadership_config`（复用读取范式）。
- 可选：`SettingPage.vue` routing tab 增两控件 + i18n。

## 12. 净 LOC / 闭环 / 安全

- 新增集中在一个自洽深模块，`channel_router` 仅薄接线；默认关零行为漂移。
- 闭环：决策 + 续租 + 可观测 `meta["leadership"]` + 全链测试。
- 不改会话持久层、不改 ACP、不引分布式依赖；符合"融合增强既有链路、不挂新孤岛"。

## 13. 验收标准

- 多我方 agent 同群、开启后：任一时刻仅 leader 应答；leader 静默 ≥ttl 后由候选接管；人类消息恒被（leader）应答；关闭/异常/kill-switch 行为回退现状；上述测试全绿；`create_app` 与既有渠道/agent 套件无回归。

## 14. 开放项（实现前可定，不阻塞成文）

- 接管并列是否启用稳定优先级 tie-break（默认关，到达序）。
- 前端两控件是否本期就做（默认后置）。
- `ttl` 是否需要按渠道差异化配置（本期全局单值）。
