# reference_ad 工具与执行安全升级实施计划（D4 全域可借鉴点落地）

- 日期：2026-11-22
- 来源：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D4 维两份专项拆解的可借鉴点全量收口（21 项，见《reference_ad_remote_execution_teardown_2026-11-22.md》§4）
- 性质：**实施计划（已实施完毕 2026-11-22：三批十九卡+U20 全部落地，D4 专项复评 86.5/100）**——按卡实施、每卡先红后绿+live-verify；竞品/外部对标，研究参考，不作产品事实源
- 目标：D4 专项十轴复评 82.0→86.5 已达（批一~三）；批四（W1 统一远程执行面+W2 lint 升 error）目标=轴3 8.0→9.0、轴7 8.5→9.0，专项 86.5→89.0+；总报告 D4 12.5→13.0+、总分 98.0→98.5+（对 LobeHub 97.5 领先扩大至 1.0+）
- 范围红线：只吸收借鉴点，不动既有已验收行为；净新增 LOC 逐卡申报；不引第三方重依赖（paramiko/pyotp 级别以下优先标准库）

## 0. 卡位总览

| 批 | 卡 | 借鉴点来源 | 一句话 |
|----|-----|-----------|--------|
| 批一 P0 | U1 | 远程执行轴3 | SSH host key 校验收紧（TOFU→known_hosts+首接确认卡） |
| 批一 P0 | U2 | 工具安全轴7 | SSRF 防护收敛为专用 safe-fetch 模块+静态检查强制 |
| 批一 P0 | U3 | 远程执行轴7 | 远程失联"未执行、可安全重试"错误语义 |
| 批一 P0 | U4 | 远程执行轴4 | 派发前最后一刻授权复验 |
| 批二 P1 | U5 | 工具安全轴6 | 沙箱第二档（容器/WASM）评估+最小落地 |
| 批二 P1 | U6 | 工具安全轴9 | 动态干预审计注册表（声明式参数级审批） |
| 批二 P1 | U7 | 工具安全轴1 | 工具 manifest 运行元数据（超时 clamp/序列化） |
| 批二 P1 | U8 | 远程执行轴7 | 长命令 park+迟交回灌 |
| 批二 P1 | U9 | 远程执行轴2 | 通道认证加固三件套（token 后置/newest-wins/watchdog） |
| 批二 P1 | U10 | 远程执行轴8 | 进程树清算（CIM BFS+批量终止） |
| 批二 P1 | U11 | 远程执行轴8 | 失败分级重试守卫（传输级才重试） |
| 批二 P1 | U20 | U18 核对升级 | 浏览器 context 按用户池化+产物属主登记（核对发现跨用户可读真实缺口） |
| 批三 P2 | U12 | 远程执行轴8 | 结构化 \*\_UNSUPPORTED 拒绝+端能力声明路由 |
| 批三 P2 | U13 | 工具安全轴8 | HPKE 凭据信道评估（评估卡） |
| 批三 P2 | U14 | 工具安全轴4 | MCP Apps 交互 UI（评估卡） |
| 批三 P2 | U15 | 远程执行轴5 | 云沙箱双 provider（评估卡，依赖 U5） |
| 批三 P2 | U16 | 远程执行轴2 | 设备通道多型 token |
| 批三 P2 | U17 | 远程执行轴5 | 不可信会话凭据隔离 |
| 批三 P2 | U18 | 远程执行轴5 | 浏览器会话 topic 键控+截图落盘核对 |
| 批三 P2 | U19 | 工具安全轴10 | alint 式安全 lint 试点 |
| 批四 P0 | W1a | 复评轴3 剩余差距 | 统一远程执行面·端点注册表（SQLite+六形态登记） |
| 批四 P0 | W1b | 复评轴3 剩余差距 | 统一分派漏斗+离线 hold 全覆盖 |
| 批四 P0 | W1c | 复评轴3 剩余差距 | 工具面收口+绕过静态守卫 |
| 批四 P0 | W2 | 复评轴7 剩余差距 | lint 升 error（shell 分段默认 strict+static-gate 双保险） |
| 批四收尾 | W3 | 移交项扫荡 | 工具执行结构化错误信封全端点透传（console/governance/skill/computer 同根因压扁点） |
| 批四收尾 | W4 | 移交项 | neuacp 池键属主段补全（登记行 ownerId 完整） |

## 1. 批一 P0（安全实益，四卡，无阻塞可开工）

**U1 SSH host key 校验收紧**
- 现状：两处 paramiko 均 AutoAddPolicy（`computer_use/ssh_runner.py:64`、`tunnel/remote_deploy.py:92-93`），中间人可冒充主机。
- 做法：新增 `security/ssh_host_store.py`——known_hosts 按 `(agent_id, host, port)` 存 `data/<agent_id>/ssh_known_hosts.json`（sha256 指纹+首见时间+确认来源）；ssh_runner 连接前比对：命中放行、未命中且 strict 模式（NEUROVA_SSH_STRICT_HOSTKEY，默认开）→ 经 WS computer_action 通道弹"主机确认卡"（展示 host:port+公钥指纹）轮询确认后写入续跑，拒绝/超时→fail-closed；remote_deploy 同步接入。key 变化=中间人嫌疑→拒绝并审计 HIGH。
- 红绿：红=模拟同 host 换 key 当前可直接连通；绿=严格模式下换 key 被拒+审计事件、首接确认后放行、拒绝后连接失败。
- live-verify：本机 sshd（或本地模拟 SSH server）真连——首接确认→执行→复连免确认→换 key 被拒三段。

**U2 SSRF 防护收敛为专用 safe-fetch 模块+静态检查强制**
- 现状：守卫分散在 http_fetch.py（208 行，禁自动跟随+逐跳复核语义）与各咽喉点（web_reach/rss_read/knowledge_ingestion/webhooks），覆盖靠自觉。
- 做法：新增 `security/safe_fetch.py` 单一出口——连接时与每一跳 redirect 校验目标 IP（私网/环回/link-local/169.254 meta/IPv6 内网）+响应体积上限+SSRFBlockedError 可识别异常+错误日志只到 origin；http_fetch 与各出站咽喉全部改走它；新增 `scripts/check_outbound_fetch.py` 静态扫描（CI static-gate 挂载）：neurova/ 内直用 httpx/aiohttp/urllib 出站的非白名单文件即红。
- 红绿：红=直连 127.0.0.1/169.254.169.254 与 302 跳私网当前可成功；绿=三者均被 SSRFBlockedError 拒绝、正常外网域放行、扫描脚本对既有白名单文件零告警。
- live-verify：本地起 127.0.0.1 httpd+公网域各一，工具出站实测拦截/放行。

**U3 远程失联"未执行、可安全重试"错误语义**
- 现状：SSH 超时/连接失败与"命令可能已执行"不可区分，调用方无法安全重试。
- 做法：`computer_use/ssh_runner.py` 区分失败相位——连接失败/认证失败/超时未拿到任何输出→`RemoteNotExecutedError`（executed=False, retryable=True）；已拿到部分输出后中断→executed=unknown（不可盲目重试）；tool_executor 把它映射为结构化错误载荷（含 phase/retryable），前端可读。neuacp spawn 的 SSH 前缀路径同样接入。
- 红绿：红=对不可达 host 执行当前返回普通失败；绿=返回 phase=connect/retryable=True 的结构化错误，且对已产出输出的中断不再标记 retryable。
- live-verify：不可达 IP+真实 sshd 两 case。

**U4 派发前最后一刻授权复验**
- 现状：审批通过到真正执行之间存在时间窗，目标/参数可能被改（steer/新上下文）。
- 做法：tool_executor 在审批通过后、执行前增加 `_final_dispatch_recheck`：对 ssh/exec/file 写类工具复验目标（host 在凭据桶已有条目、路径在会话工作根内、命令首段仍命中白名单），任一变化→重新走审批而非直接执行；审计记录 recheck 结果。
- 红绿：红=审批后篡改参数（测试内直接改 params）当前仍按旧审批执行；绿=复验发现不一致→转回审批队列并审计。
- live-verify：真后端起会话，审批一条 ssh 命令后改参数重放，观察二次审批。

## 2. 批二 P1（可靠性/架构，七卡）

**U5 沙箱第二档（最小落地，路线已拍板 D-T1）**
- 做法（D-T1 已拍板=Docker 容器档）：run_code/exec_command 增加 `isolation="strong"` 走最小镜像容器（无网络+只读根+临时可写 tmpfs）；Windows Sandbox 自动化与 Pyodide WASM 不做。最小落地=容器档跑通 run_code 一条链。
- 红绿：红=strong 档缺实现时参数被忽略按旧档执行；绿=strong 档真实在容器内执行且宿主文件系统不可见（挂载白名单外路径探测失败）。
- live-verify：容器内执行读 `/etc/passwd` 外探测+正常计算两 case。

**U6 动态干预审计注册表**
- 做法：新增 `security/dynamic_interventions.py`——声明式规则（工具名+参数谓词+干预动作），首批两条：file_delete/file_edit 命中"永久删除"语义必问；computer_ssh_exec 目标 host 首次出现必问（与 U1 确认卡合并）。ToolExecutor 治理预检后查注册表，命中→转审批链（L1）。
- 红绿：红=跨出会话工作根的 file_delete 当前不需额外确认；绿=命中规则后产生待审批项、批准才执行、拒绝不执行，全部审计。
- live-verify：真链路删除会话外文件→审批卡出现→批准执行。

**U7 工具 manifest 运行元数据**
- 做法：`builtin_tools.py` `_BUILTIN_SCHEMAS` 每条目增补 `runtime: {timeout_ms_clamp: [1000,800000], default_timeout_ms, serializable: bool, ordered_group}`；tool_executor 执行时读取并 clamp；超时不再散落硬编码。
- 红绿：红=schema 声明超时与执行体实际不一致时以执行体为准；绿=执行体读单源 clamp，越界声明被钳到区间。
- live-verify：构造慢工具（sleep）验证 clamp 生效。

**U8 长命令 park+迟交回灌**
- 做法：ssh/exec 类命令超过 soft 阈值（默认 45s）→返回 park 信封 `{parked: true, park_id, poll_after}`，后台任务继续执行；结果落 `tool_park_results`（内存+落盘），新增 `/v1/tools/park/{park_id}` 查询端点（REST 轮询，D-T2 已拍板；WS 推送/webhook 不做）；模型可凭 park_id 再查。上限对齐 800s。
- 红绿：红=120s 命令当前 60s 超时即失败且无法取回；绿=park 后首响应为信封、到期后 park_id 可取到完整结果，重复查询幂等。
- live-verify：真 sshd 跑 `sleep 90 && echo done` 全链取回。

**U9 通道认证加固三件套（token 后置/newest-wins/watchdog）**
- 做法：tunnel/agent.py 与 relay/app.py——准入 token 改"连接后首条 auth 消息"（URL 不再携带）；同 channel 新连接顶替旧连接（旧连接停止服务不回抢）；连接全窗口 watchdog（拨号→TLS→握手→auth 超时统一 15s 强制重试）。mobile WS 侧同步核对。
- 红绿：红=URL 带 token 的旧形态当前可用（token 可进中继日志）；绿=新形态下 URL 无 token、首消息认证通过、错误 token 拒绝；同 id 双连接旧者退位。
- live-verify：真机配对链路回归+恶意双连测试。

**U10 进程树清算**
- 做法：`neurova/security/process_reaper.py`——Windows 用 PowerShell CIM 快照 BFS 收后代 pid+taskkill 批量（20/批）；POSIX 用进程组 kill；接入 neuacp 进程池清扫、subagent 取消、exec_command 超时三处。
- 红绿：红=派生孙进程当前清算后残留；绿=父+子+孙全部退出，池内无僵尸。
- live-verify：真起三层进程树后触发清算，tasklist 复查。

**U11 失败分级重试守卫**
- 做法：tool_executor 与 mcp_resilience 统一重试策略——仅 transport/连接级失败允许换连接/会话重试；应用层错误（工具返回的业务失败）不重试；对变异类工具（写/发）默认不重试，除非调用方显式声明 idempotent。
- 红绿：红=应用层失败当前存在自动重试路径；绿=transport 级重试保留、应用层失败零重试，幂等声明工具不受影响。
- live-verify：假 MCP server 统计调用次数验证。

**U20 浏览器会话隔离与产物属主（源自 U18 核对，发现真实缺口，不核销）**
- 缺口 1：playwright 后端为进程级单例单 BrowserContext（`computer_use/browser_manager.py:1465,2438-2439,2524`），所有用户/会话共享同一批 tab/cookie/localStorage——A 会话可读 B 会话页面状态、并发互踩；车道键仅 `browser:<活动tab>`（lane_mutex.py:264-268），非会话粒度。
- 缺口 2：browser_pdf（browser_manager.py:1326）/browser_download（:1369）/write_pdf（tool_executor.py:7157）产物经 `persist_bytes`（llm/generators/runtime.py:193-205）落**共享目录** data/generations/，不登记 generation 账本属主——serve 端反查 owner 为空→任何登录用户可读他人下载件/PDF（generation.py:902-937），同名互相覆盖。
- 做法：playwright 后端按 user_id（至少）池化独立 BrowserContext（对齐 camofox 按 user_id 池化先例 browser_manager.py:2541-2559）；三条落盘链登记账本属主+stem 加会话/用户段+唯一后缀防覆盖。
- 红绿：红=A 用户可读 B 用户 browser_download 产物（当前 200）；绿=403/404；红 2=B 会话写 cookie A 会话可见；绿 2=互不可见。
- live-verify：双会话双用户真浏览器链路+产物读取跨权测试。

## 3. 批三 P2（体验/生态/强制面，八卡）

**U12 结构化 \*\_UNSUPPORTED 拒绝+端能力声明路由**：工具因能力未装配/端不支持时返回稳定 `{error_code: "TOOL_UNSUPPORTED", reason, supported: [...]}`；多后端桌面执行（本机/来宾机/RDP/Sandbox）按端能力声明选端器（computer_use 注册表扩 capability 字段）。红绿：未装浏览器引擎时 browser_navigate 返回结构化不支持而非异常。
**U13 HPKE 凭据信道评估（评估卡，D-T6 已拍板：评估后拍板）**：评估 RFC 9180 形态对本仓凭据跨端传递（移动端/来宾机）的收益；产出评估结论，不接线不加分。
**U14 MCP Apps 交互 UI（评估卡，D-T6 已拍板：评估后拍板）**：评估 SEP-1865 形态对本仓 MCP server 面的增量；产出结论。
**U15 云沙箱双 provider（评估卡，依赖 U5）**：托管/自托管双轨可行性（对标对方 market/onlyboxes）；产出结论。
**U16 设备通道多型 token**：relay/tunnel/mobile 的准入 token 分型（agent-token/user-token/service-token），撤销粒度到型。红绿：错误型 token 访问控制面被拒。
**U17 不可信会话凭据隔离**：分享/来宾会话禁用凭据类工具与凭据卡弹卡（fail-closed），凭据注入面加会话信任级检查。红绿：来宾会话触发 ssh 工具→直接结构化拒绝且不弹卡。
**U18 浏览器会话 topic 键控+截图落盘核对**：核对 browser_* 工具会话隔离与截图产物落盘路径，补齐缺口（如已有则核销）。
**U19 alint 式安全 lint 试点**：模型背书 lint 试点两条判据——"新出站代码必须走 safe_fetch（配合 U2）""shell 拼接必须过 command_segments"；先 warning 档跑误报率，达标后升 error 接入 static-gate（D-T5 已拍板：先 warning 观察）。

## 4. 批四（复评剩余差距追平，2026-11-22 二次立卡；D-W1a/b/c、D-W2 已拍板）

**W1a 统一远程执行面·端点注册表（SQLite，D-W1b 已拍板=SQLite+离线 hold 全覆盖）**
- 现状：六形态（SSH/guest/隧道/neuacp/远程 MCP/中继代部署）各自为政——ssh_runner/guest_agent/tunnel/neuacp 名册/mcp_source 各自记录连接信息，无统一注册表与审计面（grep 实证）。
- 做法：新建 `neurova/remote_exec/registry.py`——RemoteEndpoint（endpoint_id/kind: ssh|guest|tunnel|neuacp|mcp/owner+tenant/capability 声明/health+last_seen/连接信息引用）落 SQLite（core/db_migration 注册迁移）；六形态接入登记（全命中点扫荡：ssh_runner 建连、guest_agent 注册、tunnel 配对/relay、neuacp 名册、mcp_source）。
- 红绿：红=六形态当前无统一注册表面（grep 实证各自为政）；绿=六形态注册可查、租户段隔离、审计事件齐全。
- live-verify：真后端注册 ssh+guest 两端点→查询→租户隔离断言。

**W1b 统一分派漏斗+离线 hold 全覆盖**
- 做法：新建 `neurova/remote_exec/dispatch.py`——dispatch(tool_call, endpoint) 统一入口：准入（租户/能力/审批复验，复用 U4）→路由形态执行体（ssh_runner/guest_agent/tunnel/neuacp）→统一结果信封（executed/phase/retryable，U3 语义）→离线 hold（端点不可达 hold 至超时+宽限，返回"未执行、可安全重试"）→清算（kill_tree）。computer_ssh_exec/guest 工具/隧道形态先行接入。
- 红绿：红=ssh/guest 当前各自为政无统一信封（各返回各的）；绿=两形态经漏斗执行、离线 hold 生效、审计一致。
- live-verify：真 sshd+guest 桩双形态经漏斗执行+离线 hold 实测。

**W1c 工具面收口+静态守卫**
- 做法：tool_executor 的远程工具（computer_ssh_exec/guest_*）全走漏斗（全命中点扫荡）；新增守卫测试——远程形态绕过漏斗（直调 ssh_runner/guest client）即红。
- 红绿：红=存在绕过漏斗的直调；绿=守卫断言零绕过。

**W2 lint 升 error（D-W2 已拍板=默认 strict+双保险）**
- 做法：check_shell_segments.py 默认档 strict（--warn 才降档）；check_outbound_fetch 已 strict；两扫描器显性写入 .cnb.yml static-gate；单测继续钉住（违规即测试红）。
- 红绿：红=引入一个未登记出站点/拼接点→static-gate 红；绿=当前仓零违规通过。
- live-verify：本地跑两扫描器+单测。

**W3 工具执行结构化错误信封全端点透传（移交项扫荡卡，2026-11-22 立）**
- 现状：/tools/execute 已单点修复（45a8c452c——失败响应 data.result 携带原始结构化载荷，顶层 error 串保留兼容）；同一根因（结构化失败载荷压扁成裸 error 串）仍散布于 console.py:950、governance.py:245/365、skill.py:418、computer.py:785/901/919/933/972（HTTPException detail 形态，结构化字段同丢）。
- 做法：逐点把失败响应升级为「顶层 error/message 串保留 + 结构化载荷随响应透传」（各端点按自身契约选 data.result/extra 字段承载，不破坏既有消费方）；HTTPException 形态改挂 detail=结构化对象或附 X- 结构化头，取不破坏前端既有判读的最小形。
- 红绿：红=各命中点以结构化失败载荷调用→响应仅见裸串；绿=结构化字段全部可达且既有断言零回归。
- live-verify：真后端逐端点打失败探针（治理拦截/技能失败/浏览器失败各一）。

**W4 neuacp 池键属主段补全（移交项卡，2026-11-22 立）**
- 现状：NeuacpProcessPool 池键只有「租户+成员」段无属主段，remote_endpoints 登记行 ownerId 恒空（运行台账属主在 agent_run_ledger 有权威记录，登记表属辅助盘点面——属主缺省影响 owner 维度检索/审计连接）。
- 做法：attachProcessPool 装配期把 swarm 成员 id 带入池键（新键段追加，兼容读旧键——存量在飞池按旧键取得到）；registry 登记行 ownerId 随之补全；§6.4 租户段语义不变。
- 红绿：红=登记行 ownerId 恒空；绿=装配期带属主后登记行 ownerId=swarm 成员 id、旧键兼容读取不破。
- live-verify：真后端 spawn 一个 neuacp 成员→查登记行属主。

**登记不立卡（无消费场景不做表面工程）**：mcp 单例属主恒 default——MCP server 配置当前为部署级共享，per-user 作用域不存在；出现 per-user MCP 配置场景时再立卡把属主随配置传入。

## 5. 拍板结果（2026-11-22 交互拍板，六项全落定）

- **D-T1 沙箱第二档路线：Docker 容器档**——U5 按此实施（run_code/exec_command 增 `isolation="strong"`）；Windows Sandbox 自动化与 Pyodide WASM 不做。
- **D-T2 park 回灌通道：REST 轮询**——/v1/tools/park/{park_id} 查询端点；WS 事件推送与 webhook 回调不做。
- **D-T3 known_hosts 存储：数据根 JSON**——data/<agent_id>/ssh_known_hosts.json；凭据桶扩展不做。
- **D-T4 SSRF 迁移范围：一次全量迁移**——5-8 个出站文件同批改走 safe_fetch，静态检查直接开严格模式。
- **D-T5 lint 门禁：先 warning 观察**——两判据 warning 跑误报率，清零后升 error 接 static-gate。
- **D-T6 评估卡：评估后拍板**——U13/U14 各出评估结论再定是否实施。
- **D-W1a 统一远程执行面范围：六形态全量收口**——SSH/guest/隧道/neuacp/远程 MCP/中继代部署全部接入统一注册表与分派漏斗；先试点两形态的做法不做。
- **D-W1b 注册表持久化与离线语义：SQLite 表+离线 hold 全覆盖**——端点注册表落 SQLite（含租户/能力/健康度），离线 hold（"未执行、可安全重试"）覆盖全部远程形态；进程内注册表不做。
- **D-W2 lint 升 error：默认 strict+双保险**——check_shell_segments 默认 strict（--warn 才降档）、两扫描器显性写入 .cnb.yml static-gate、单测钉住；仅挂载不改默认的做法不做。

## 6. 明确不做

- 不引入闭源云侧网关依赖与 DO 状态机形态（本仓中继自托管可审计）。
- 不做 Electron IPC 形态（本仓无该架构）。
- 不把"主进程直执行无隔离"引入任何远程路径。
- 不为追分做无消费方的表面工程（HPKE/MCP Apps 只做评估、拍板后才实施）。
- 不改既有已验收工具的对外行为语义（仅增补元数据/错误形态，保持向后兼容）。

## 7. 验收与复评

- 每卡：先红后绿（失败测试先行）+真链路 live-verify 证据入提交说明；分域回归零新增失败。
- 批验收：批一完成→D4 专项复评轴7 7.0→9.0、轴3 6.5→8.0（总分 82.0→85.0+）；批二完成→轴6 7.0→8.5、轴9 8.5→9.0、轴1 8.5→9.0（→89.0+）；批三完成→轴10 8.5→9.0、轴4 9.0→9.5（→90.0+）。
- 批四验收：W1+W2 完成→D4 专项复评轴3 8.0→9.0、轴7 8.5→9.0（86.5→89.0+）；总报告 D4 12.5→13.0+、总分 98.0→98.5+（对 LobeHub 97.5 领先扩大至 1.0+）。轴6 云沙箱 provider 档（8.0→8.5）按 U15 评估待真实消费场景另卡。
- 总验收：总报告 D4 11.5→13.0+、总分 96.0→98.0+；全部复评读数回填本文件执行记录与总报告复核说明。

## 8. 执行记录

- **2026-11-22 评估卡回填（U13/U14/U15/U18）**：U13 HPKE=**暂缓**（本仓凭据不穿不可信中转：一次性配对码+connect ticket+TLS+SSH 信道+本地注入四条链路均已闭环；引入 HPKE=第二套并行凭据面，违教义第 6 条）；U14 MCP Apps UI=**暂缓不立项**（本仓 MCP 消费方全为无头 agent，无 UI 宿主，做了即"注册无消费者模块"）；U15 云沙箱双 provider=**暂缓**（单机部署形态零云沙箱消费方，先落 U5 容器档，未来上云时 provider seam 长在 code_sandbox 既有后端选择处）；U18 核对=截图链已规范（核销），但发现两个真实隔离缺口→**新增 U20 卡**入批二（浏览器 context 跨用户共享；浏览器产物共享目录无属主登记可被任意登录用户跨读）。
- **2026-11-22 U19 试点回填（shell 分段判据）**：`scripts/check_shell_segments.py`（AST 判定四类 shell 执行点 × 拼接/格式化，豁免 tests//scripts//ALLOW 登记/治理 import 邻近使用）+ `tests/unit/security/test_shell_segments_scan.py` 先红后绿 32 例全绿；全仓实跑 1273 文件、shell 执行点 5 处（hooks_engine:118、shell_sessions:96、computer.py:461、ssh_runner:273、remote_deploy:113）、调用点拼接 0 处 → 违规 0，warning 档退出 0；误报率 0/0 按 0.0 记（5 处命令串均变量透传，逐条人工复核无拼接面）；已知盲区=跨函数先拼接再透传（remote_deploy.writeText f-string → self.run → exec_command），待后续卡接过程间分析或按教义改 argv 传递；误报清零前维持 warning 不升 error（D-T5）。
- **2026-11-22 全部卡实施完毕（三批十九卡+U20）**：
  - 波次一：U2 SSRF 收敛=91969ed0a（safe_fetch 使能层委托 url_guard 单源+全量迁移+静态扫描严格零违规）；U1+U3 SSH host key known_hosts+首接确认卡+失败相位追踪=10b9cf7b2（真 socket 四段 live-verify）。
  - 波次二：治理簇五卡（U4 最后一刻复验/U6 动态干预注册表/U7 运行元数据/U11 失败分级重试/U12 结构化 UNSUPPORTED）=df23d131c；通道认证三件套+多型令牌（U9/U16）=79a15e220；U10 进程树清算+killpg 单源收敛=45c54da78；U5 容器沙箱档=b1f3feb6c；U19 shell 分段 lint=ead9c31e5。
  - 波次三：tool_executor 收尾簇（U8 park+迟交回灌/U17 不可信会话凭据隔离/U5 isolation 分派接线/U10 exec 清算接线/write_pdf 属主登记）=6fd2f600e；U20 浏览器 context 按属主池化+产物属主登记+车道属主段+端能力声明路由=372e12c95；收口补遗（auth_oidc 出站登记/动态干预测试入档）=b92e69ece；schema 补声明撤豁免=bf5bd9368。
  - 合并回归：tools+security+computer_use **3803 passed 零失败**（含 U1-U3、U20 真 chromium 13/13、U8 真 SSH 服务端、U10 真实三层进程树、U17 真实用户库 live-verify）。
  - **D4 专项复评：82.0→86.5**（总目标 90.0 未达，差距=对方分布式执行面/云沙箱档/lint 强制成熟度，诚实记档不入水分）；总报告 D4 12.0/11.5→**12.0/12.5 本仓反超 0.5**，总分 98.0/96.0→**98.0/97.0**。
- **2026-11-22 批四全部实施完毕（复评剩余差距追平，四笔提交本地未推）**：
  - W1a/W1b 核心包=c37697a31：新建 neurova/remote_exec/（registry.py 255 行+dispatch.py 301 行）——RemoteEndpoint SQLite 注册表（自然键 (tenantId,ownerId,kind,name) upsert+endpointId 稳定派生+DCL/RLock 单例+db_migration remote_exec 域 v1）+dispatchRemoteCall 统一漏斗（准入 unknown_kind/capability_missing 副作用前拒绝→执行体注入透传→仅 connect/timeout 且 retryable 进离线 hold 指数退避（0.5s×2 封顶 5s，端点标 offline）→窗口耗尽诚实返回「未执行、可安全重试」→auth/unknown 不重试→onEvent 生命周期事件）；25 用例先红后绿，db_migration 21+security 1487 零回归。
  - W1b/W1c SSH 接线=8ec41fcb4：_execute_computer_ssh_exec 注册制增量接入——未登记端点走既有直连路径（逐字节不变），已登记经漏斗；U1 主机确认卡/指纹冲突经 dispatch 新增 transparentExceptions 参原样上抛（默认空元组行为不变）；首跑成功即登记（connectionRef=ssh-bucket 引用名不落明文）；守卫 8 例（已登记必经漏斗/未登记哨兵不调/capability 缺失 TOOL_UNSUPPORTED/登记 fail-soft）+透传 6 例；live-verify 真后端 9573+真 socket SSH 桩三跑——直连登记（endpointId=7af2bfed543417df）→漏斗执行（remote_dispatch_start/result phase=exec）→不可达端点 NEUROVA_REMOTE_HOLD_MS=3000 三次 retry 后「未执行、可安全重试」+端点 offline+零新增 SSH 连接。
  - W1a 四形态登记=3b74367ae：guest（GuestAgentClient health/action 成功 DCL 一次性，owner=领用 user_id、tenant=resolveUserDepartment 单源）/tunnel（_dialAndAuth 收 FRAME_REGISTERED 且 routeId 落定，owner=instanceId）/neuacp（进程池 factory 成功后登记，tenant=池键租户段同源、ownerId 诚实缺省）/mcp（connect_server 会话建立成功，connectionRef=url 或 stdio 命令头不落凭据）；全 fail-soft+拿不到租户上下文跳过不臆造；15 用例先红后绿；真 guest FastAPI+真 SQLite live-verify（health 即登记/action 不重复/token 不落登记面/跨租户隔离成立）。
  - W2 lint 升 error=51276d9f8：check_shell_segments 默认 strict（违规退出 1）+--warn 降档；check_shell_segments+check_outbound_fetch 双扫描器显性挂进 .cnb.yml 与 GitHub ci.yml static-gate（**补上 U2 交付时实际未挂载 outbound_fetch 的缺口**）；红 5F→绿 37P；全仓实跑双扫描器 0 违规；红色演示（临时拼接文件 strict 拦截）已验已清。
- **2026-11-22 批四复评回填（v17）**：工具安全专项 86.5→**88.0**（轴3 8.0→9.0 统一执行面、轴10 9.0→9.5 lint 强制）。立卡验收线「轴7 8.5→9.0、86.5→89.0+」系轴归属标注误差（lint 属轴10 测试/供应链；轴7=SSRF 已于批三复评至 8.5）——按「只经据实复评回写、不许预支」纪律落档 88.0，总目标 90.0 仍未达（差 2.0）。主报告 D4 12.5→**13.0**/14 反超 1.0；总分在并行 v15（上下文收官 85.5）/v16（D7 路由复评 7.5）之后 97.0/100.5→**97.0/101.0**（对 LobeHub 快照领先 4.0）。剩余差距=轴6 云沙箱三档（U15 评估：待真实消费场景另卡）+对方设备 attestation/多版本兼容深度。
- **2026-11-22 移交项处置（用户指令「处理一下移交项，该立卡的立卡」）**：
  - 已清偿=**/tools/execute 失败面结构化错误信封透传**=45a8c452c（失败响应 data.result 携带原始结构化载荷、顶层 error 串保留兼容；红 4F→绿 19P；live-verify 真后端 9575 两案：缺参 param_errors 透传+未登记主机首见 U6 L1 审批信封 approval_id/governance/pending_approval 完整透传，启动 [ERROR]=0）。
  - 已立卡=**W3 结构化错误信封全端点扫荡**（console/governance/skill/computer 同根因压扁点，见 §4）+**W4 neuacp 池键属主段补全**（见 §4）。
  - 登记不立卡=**mcp 单例属主 default**（per-user MCP 配置场景不存在，出现消费场景再立卡）。
- **2026-11-22 W3+W4 实施完毕（用户指令「两卡开工」；两卡改动经并行会话统一收口提交=ea414149f，主控复验测试全绿）**：
  - W3=skill.py `SkillExecuteResponse` 增可选 `error_detail` 字段（失败原始载荷原样透传）+computer.py 五处 502 改 `JSONResponse`（detail 串保留+result 结构化透传）+复扫新增命中点 provider.py（端点字段同步更新）；**排除登记**=console.py:950（聊天错误事件构造，非工具执行响应面）/governance.py:245,365（审批协调器与续跑内部记账）——现场复核与「响应面压扁」不同根因，不硬改。test_structured_error_sweep 7 例+三回归件 18 例全绿；live-verify 三探针全过（启动 [ERROR]=0）。
  - W4=池键追加属主尾段（六元组→七元组；`_normalizeKey` 双形态兼容、`poolKey(ownerId="")` 缺省回旧六元组），attachProcessPool 装配期传成员 id（**偏离申报**：成员 id 只在 swarm 装配期可得，对 swarm.py 最小穿参——不改则属主只能装 run id、杀死同成员跨 run 进程复用，不可取）；登记行 ownerId=成员 id；test_neuacp_pool_key_owner 20 例（旧键兼容/租户段不变/属主段真实参与池键防串池/stats 透出 owner）；live-verify 真进程池+真桩 CLI 三查（登记属主/复用幂等不增行/旧键兼容）全过。合并回归零新增失败。
  - 遗留收口（2026-11-22 清理批，用户指令「清理遗留问题」）：①升级前 ownerId="" 旧登记行——经查真实数据根**从未落行**（data/remote_endpoints.db 不存在，各代理与 live-verify 均用临时数据根，预测的测试污染未发生），无事可清；②W3 代理的全量套件验证未及回报（代理结束）——以定向回归（sweep 7+三回归件 18+池键属主 20+/tools 透传 4，均绿）与收口提交复验为准，其独立 worktree（Neurova_w3_verify）已清理；③连带清理三个迁移前遗留坏 worktree（nv-b12-base/a1base/abWebhook——.git 指向迁移前旧路径不可用、钉住的提交均不可达）并 prune 元数据；④误建的 0 字节 data/remote_endpoints.db 已删。
