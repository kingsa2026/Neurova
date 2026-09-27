# Bugfix: 渠道页选不到智能体 + 已有渠道配置全部失效（两条独立根因）

**Bug ID**: Issue #290
**报告时间**: 2026-09-27
**修复时间**: 2026-09-28
**状态**: 已修复
**严重度**: 高（用户级误配静默写错归属；存量渠道配置整体失效且无告警）

## 症状

打开渠道管理页：

1. 顶部 agent 选择器里**看不到已注册智能体的名字**，只有孤零零一项「默认智能体」
   加若干空白行；点了空白行页面也不变。
2. 更坏的是：**保存会静默落到 `default` 名下** —— 用户以为在给 `凯蒂` 配飞书，
   配置实际写进了 `default` 的渠道表，且无任何提示。
3. 已有的渠道配置**全部失效**：卡片回到「未启用/未配置」，机器人前缀显示"未设置"；
   后端重启后飞书/钉钉/QQ/微信/企业微信一个都不连接，而机器上明明有一份
   写着真实凭据的配置文件。

## 根因（两条，互不相干、各自独立成立）

### Bug A —— 渠道页读错了 agentOptions 的键名

`stores/agents.ts` 的生产契约是 `{label, value, isWorkflow}`，
而渠道两页各自写成：

```ts
agentStore.agentOptions.map((o: any) => ({ value: o.id, label: o.name }))
```

`id` 与 `name` 两个键在生产端**从未存在**，于是：

1. `a-select` 收到一串 `value: undefined` → 渲染成**无文字空白行**（症状 1）；
2. 选中它 → `agentId = undefined`；
3. `channel-configs.ts` 的 `agentId ? { agent_id: agentId } : {}` → **不发参数**；
4. 后端 `Query(default="default")` 兜到 `default`（症状 2）。

第 3、4 步是最坏的一面：错键名不只是"看不见"，而是**写错地方**——GET 与 POST
走同一条链，用户级误配被后端默认值吞掉。

同一份契约在仓内已有 3 处正确消费方（`AgentSchedulerPage` / `CollaborationPage` /
`CanvasDesignerPage`），只有渠道两页各写了一份错映射。归属**消费端**：
引入点 `7846d74f` 当时生产端契约就已经是 `{label, value}`。

**为什么守卫全绿**：`AgentChannelPage.layout.test.ts` 把 store mock 成
`agentOptions: []` —— `.map()` 对空数组恒等，错键名永远不可能显形。

### Bug B —— 数据根换锚时存量配置没跟着搬

`721ef038`（2026-09-22）把渠道配置的锚点从包内 `<仓库>/neurova/data` 换到数据根
`<仓库>/data`，**没有带存量搬迁**：

```python
旧: CONFIG_DIR = Path(__file__).parent.parent.parent / "data"   # → neurova/data/
新: CONFIG_DIR = get_data_root()                                 # → <仓库根>/data/
```

旧锚点里那份带着真实凭据的配置从此**再无人读**：`_load_store()` 在新锚点找不到
文件即走 `if not CONFIG_FILE.exists(): return {"version": 2, "agents": {}}`，
**静默返回空表**——不报错、不告警、不日志。

爆炸半径比"页面显示空"更宽：

- **启动装配整链断**：`bootstrap_channel_adapters` 读到空表 → 日志
  `渠道启动装配完成: {registered: 0, connected: 0, skipped: 0, failed: 0}`，
  全零看起来"一切正常"（这正是本 bug 被拖了 6 天没人定位到落点的原因）；
- **跨 agent 身份冲突检测同时失明**：`_identity_conflict_owner` 只扫
  `_load_store()` 的结果，旧锚点里 5 个真实 bot 不在扫描面内 → 同 app_id 配到
  第二个 agent 时 409 不再拦，双长连接串台；
- **存量会被就地分叉**：任何一次保存都在新锚点建一份新表，旧那份永不读取也不清除。

A × B 的咬合点：存量全挂 `default` 名下，而侧栏进的 Agent 渠道页按路由 agent 查；
该页唯一能触达 `default` 的入口又是硬编码那一项，而 Bug A 让真实 agent 变成空白行
——用户既找不到自己的 agent，也解释不清"为什么配置不见了"。

**为什么守卫没拦住**：`tests/unit/core/test_data_root_no_cwd_landing.py` 的判据是
**源码字形**（"生产代码里不得出现第二份根"）。它把该模块从红扫到绿，却对
"绿了以后原来的数据还在不在"零判据；渠道配置类测试又**全部** monkeypatch 落点，
锚点本身从未被断言过。

## 修法

### Bug A（消费端收口，不动生产契约）

- 新增 `NeurUI/src/config/agentOptions.ts` 的 `buildAgentSelectOptions()`：
  store 的 `agentOptions` → `a-select` 选项的**唯一**组装点。缺 `value`
  （即身份）的条目整条丢弃——一条没有身份的选项落进选择器，唯一后果就是让用户
  误选并静默写错配置。
- 渠道两页改为共用它，删除各自的 `o.id/o.name` 映射（禁止第三份写法）。
- 两页 `onMounted` 补 `loadWorkflowAgents()`（此前从未调用 → 工作流编译出的
  agent 在这两页永远不出现）；**不**阻塞配置取数：渠道列表按路由的 agent 身份
  取数，与选项列表无依赖，把主内容挂在无关请求上会让一次慢/失败的 `/agents`
  拖空整页。

### Bug B（落点推导与存量搬迁同批）

- `neurova/core/data_root.py` 的 `adoptLegacyLanding()` 补"两侧都在"的**点名**：
  原实现直接 `return False`，等于让旧物里的内容无声失效。现改为一处告警
  （按旧落点路径去重，不按请求刷屏）后返回 False，新落点仍为事实源。
- `channel_config.py` 的落点改为**调用时**经
  `dataLanding("channel_configs.json", legacy=("neurova", "data", "channel_configs.json"))`
  解析——旧锚点字符串只出现在本模块一处，与"按层数推导只准出现在 `data_root.py`"
  同形。落点调用时解析而非模块级常量，`NEUROVA_DATA_DIR` 注入才对延迟装配生效。
- **同一根因的第二批命中点**（教义第 5 条）：八个种子记忆脚本
  （`neurova/memory/scripts/*.py`）同样在换锚时丢了存量（旧锚点
  `neurova/memory/data/yi_ling_memory.db`，重跑即新建空库 → "种子记忆不可见"）。
  落点收口到新模块 `seed_db_landing.py` 的 `seedDbPath()` 单点，八处旧锚点定义归零。

## 实证

### 红灯（实现前实测）

Bug A：

```
FAIL src/pages/__tests__/AgentChannelPage.agentSelect.test.ts
  Received: [ {label: "默认智能体", value: "default"},
              {label: "", value: "undefined"}, {label: "", value: "undefined"} ]
```

Bug B（`tests/unit/api/test_channel_config_landing_anchor.py`，4 failed）：

```
FAILED TestLandingFollowsTheInjectionPoint::test_landingIsUnderDataRoot
FAILED TestLegacyStoreIsRelocated::test_legacyStoreIsRelocatedOnRead - KeyError: 'default'
FAILED TestLegacyStoreIsRelocated::test_conflictIsNamedNotSilent
FAILED TestBootstrapSeesRelocatedStore::test_bootstrapRegistersRelocatedPlatforms
       AssertionError: 启动装配没按搬回来的存量重建适配器  assert 0 == 5
```

第二批命中点（`tests/unit/memory_ingest/test_seed_db_landing_relocation.py`，
旧实现下 8 failed）：

```
FAILED TestSeedScriptsShareOneLanding::test_scriptGoesThroughTheSingleLanding[...] (8 例)
       AssertionError: 落点未走单点 seedDbPath()
```

### 绿灯（实测）

- `tests/unit/api/test_channel_config_landing_anchor.py` 9 passed；
- `tests/unit/memory_ingest/` 290 passed（含新判据 12 例）；
- `tests/unit/channels tests/unit/api tests/api`：A/B 比对**新增失败为 0**
  （基线 32 条失败集合 → 修复后 24 条，差集全部是本批新判据由红转绿）；
- 前端 `npx vitest run` 233 文件全绿（含新增两页各一例），`npx vue-tsc --noEmit` 净；
- 静态门禁 `scripts/ci_static_gate.py` 全通过。

### live-verify（真链路，证据脚本入库）

`tests/manual/channel_landing_anchor_290.py`：

```
[1] GET 行数: 5 ['dingtalk', 'feishu', 'qq', 'wechat', 'wecom']
[2] stats: {'registered': 5, 'connected': 5, 'skipped': 0, 'failed': 0}
[3] 已点名的冲突落点: ['<伪仓库根>/neurova/data/channel_configs.json']
LIVE-VERIFY PASSED / Issue #290 Bug B
```

改前同一脚本的装配读数是 `{registered: 0, ...}` 全零。

## 未闭环项（登记，不静默遗留）

### 已收口（2026-09-28 第二批）

2. ~~**Agent 渠道页的 agent 切换不走路由**~~ **已修**：身份收口到路由
   （`agentId` 改读 `route.params`，选择器只推路由；首挂载与后续 URL 变化走
   同一条取数路径）。判据 `NeurUI/src/pages/__tests__/AgentChannelPage.agentRouteSync.test.ts`。
3. ~~**管理面 agent 盲**~~ **已修**：`restart` / `clear-queue` / `conflicts`
   三端点加 `agent_id` 形参，manager 按复合键取实例，冲突扫描面改全量实例表，
   队列清空按 `payload.metadata.agent_id`（行自带的事实）收口，前端调用点透传身份。
   判据 `tests/unit/channels/test_mgmt_agent_scope_290.py` +
   `ChannelIntegrationPage.mgmtAgentScope.test.ts`。
4. ~~**落点已分叉的另外两项**~~ **部分收口**：`neurova/memory/data/neurova_memories_persist.db`
   已按**配对**收养（见下节"配对"）。**`yi_ling_memory.db` 的打包态落点仍未实拍**
   （需真实桌面部署环境），如实留在这里。

### 配对收养（本批发现的更深一层根因）

记忆持久层是**一对文件**：`MemoryManager` 拿 `db_path` 当主库，另在同目录配一个
持久库，而**真行写进的是后者**。原先的换锚救济按单文件语义工作，只搬了主库 ——
搬过来的是空壳（读到 0 行），症状与"完全没搬"逐字相同，而"旧物已搬走"的断言全绿。

现收口到 `memory_layer/persist_landing.py` 的 `persistCompanionPath()` 单点
（写入端与收养端共用），`seed_db_landing.seedDbPath()` 按成对收养。
判据 `tests/unit/memory_ingest/test_seed_db_landing_companion.py`；
live-verify `tests/manual/seed_memory_pair_relocation_290.py`。

> 口径提醒：本条只解决**收养**。旧锚点那份与真工作区库的**内容归属**
> （哪一份是权威）仍属产品口径，不在本批范围内。

### 仍未闭环（需产品口径或另单承接）

1. **存量渠道的归属裁决**：存量 5 条挂在 `agents.default` 下，而侧栏进的是
   `/agent/<真 agent id>/channel`。修 A、B、②之后用户**能主动切回** `default`
   看到配置，切换也不再回退，但"存量该继续挂 default，还是按 `agents.json`
   的真实身份重新归属"属产品口径，需拍板后再动。
5. **`app_secret` 明文落盘的旧账**：搬迁会把这份明文一起搬到新落点，是否同批落掩码
   需单独决定（旧账见 `docs/空数据页面与保存落盘排查_2026-09-12.md`）。
