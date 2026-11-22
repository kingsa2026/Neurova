# reference_ad 工具与执行安全升级实施计划（D4 全域可借鉴点落地）

- 日期：2026-11-22
- 来源：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D4 维两份专项拆解的可借鉴点全量收口（21 项，见《reference_ad_remote_execution_teardown_2026-11-22.md》§4）
- 性质：**实施计划（备稿待拍板）**——按卡实施、每卡先红后绿+live-verify；竞品/外部对标，研究参考，不作产品事实源
- 目标：D4 专项十轴复评 82.0→90.0+（轴1 8.5→9.0/轴3 6.5→8.0/轴6 7.0→8.5/轴7 7.0→9.0/轴9 8.5→9.0/轴10 8.5→9.0）；总报告 D4 11.5→13.0+、总分 96.0→98.0+
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
| 批三 P2 | U12 | 远程执行轴8 | 结构化 \*\_UNSUPPORTED 拒绝+端能力声明路由 |
| 批三 P2 | U13 | 工具安全轴8 | HPKE 凭据信道评估（评估卡） |
| 批三 P2 | U14 | 工具安全轴4 | MCP Apps 交互 UI（评估卡） |
| 批三 P2 | U15 | 远程执行轴5 | 云沙箱双 provider（评估卡，依赖 U5） |
| 批三 P2 | U16 | 远程执行轴2 | 设备通道多型 token |
| 批三 P2 | U17 | 远程执行轴5 | 不可信会话凭据隔离 |
| 批三 P2 | U18 | 远程执行轴5 | 浏览器会话 topic 键控+截图落盘核对 |
| 批三 P2 | U19 | 工具安全轴10 | alint 式安全 lint 试点 |

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

**U5 沙箱第二档（评估+最小落地，依赖拍板 D-T1）**
- 做法：评估三路线——Docker 容器档（推荐：run_code/exec_command 增加 `isolation="strong"` 走容器执行，镜像最小化+无网络+只读根+临时可写 tmpfs）、Windows Sandbox 自动化档（已有 sandbox_provider 雏形）、Pyodide WASM 档（仅纯计算）。最小落地=容器档跑通 run_code 一条链。
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
- 做法：ssh/exec 类命令超过 soft 阈值（默认 45s）→返回 park 信封 `{parked: true, park_id, poll_after}`，后台任务继续执行；结果落 `tool_park_results`（内存+落盘），新增 `/v1/tools/park/{park_id}` 查询端点+WS 事件；模型可凭 park_id 再查。上限对齐 800s。
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

## 3. 批三 P2（体验/生态/强制面，八卡）

**U12 结构化 \*\_UNSUPPORTED 拒绝+端能力声明路由**：工具因能力未装配/端不支持时返回稳定 `{error_code: "TOOL_UNSUPPORTED", reason, supported: [...]}`；多后端桌面执行（本机/来宾机/RDP/Sandbox）按端能力声明选端器（computer_use 注册表扩 capability 字段）。红绿：未装浏览器引擎时 browser_navigate 返回结构化不支持而非异常。
**U13 HPKE 凭据信道评估（评估卡）**：评估 RFC 9180 形态对本仓凭据跨端传递（移动端/来宾机）的收益；产出评估结论，不接线不加分。
**U14 MCP Apps 交互 UI（评估卡）**：评估 SEP-1865 形态对本仓 MCP server 面的增量；产出结论。
**U15 云沙箱双 provider（评估卡，依赖 U5）**：托管/自托管双轨可行性（对标对方 market/onlyboxes）；产出结论。
**U16 设备通道多型 token**：relay/tunnel/mobile 的准入 token 分型（agent-token/user-token/service-token），撤销粒度到型。红绿：错误型 token 访问控制面被拒。
**U17 不可信会话凭据隔离**：分享/来宾会话禁用凭据类工具与凭据卡弹卡（fail-closed），凭据注入面加会话信任级检查。红绿：来宾会话触发 ssh 工具→直接结构化拒绝且不弹卡。
**U18 浏览器会话 topic 键控+截图落盘核对**：核对 browser_* 工具会话隔离与截图产物落盘路径，补齐缺口（如已有则核销）。
**U19 alint 式安全 lint 试点**：模型背书 lint 试点两条判据——"新出站代码必须走 safe_fetch（配合 U2）""shell 拼接必须过 command_segments"；先 warning 档跑误报率，达标后升 error 接入 static-gate。

## 4. 待拍板（D-T1..D-T6）

- **D-T1 U5 技术路线**：Docker 容器档（推荐，跨平台+生态熟）/ Windows Sandbox 自动化 / Pyodide WASM——影响 sandbox/ 新增模块与 run_code 参数面。
- **D-T2 U8 回灌通道**：REST 轮询（推荐，简单幂等）/ WS 事件推送 / webhook 回调——影响端点形态与前端配合。
- **D-T3 U1 known_hosts 存储**：数据根 JSON（推荐）/ 凭据桶扩展——影响 ssh_host_store 形态。
- **D-T4 U2 迁移范围**：一次全量迁移所有出站点（推荐）/ 先咽喉点后扫尾——影响 static-gate 首轮告警量。
- **D-T5 U19 是否接 CI 阻断**：先 warning 观察（推荐）/ 直接 error——影响误报成本。
- **D-T6 U13/U14 是否立项**：评估后拍板，可缓。

## 5. 明确不做

- 不引入闭源云侧网关依赖与 DO 状态机形态（本仓中继自托管可审计）。
- 不做 Electron IPC 形态（本仓无该架构）。
- 不把"主进程直执行无隔离"引入任何远程路径。
- 不为追分做无消费方的表面工程（HPKE/MCP Apps 只做评估、拍板后才实施）。
- 不改既有已验收工具的对外行为语义（仅增补元数据/错误形态，保持向后兼容）。

## 6. 验收与复评

- 每卡：先红后绿（失败测试先行）+真链路 live-verify 证据入提交说明；分域回归零新增失败。
- 批验收：批一完成→D4 专项复评轴7 7.0→9.0、轴3 6.5→8.0（总分 82.0→85.0+）；批二完成→轴6 7.0→8.5、轴9 8.5→9.0、轴1 8.5→9.0（→89.0+）；批三完成→轴10 8.5→9.0、轴4 9.0→9.5（→90.0+）。
- 总验收：总报告 D4 11.5→13.0+、总分 96.0→98.0+；全部复评读数回填本文件执行记录与总报告复核说明。

## 7. 执行记录

（待实施回填：逐卡 commit、红绿实测、live-verify 证据、复评读数。）
