# reference_ad 专项：远程执行能力细拆（Neurova vs LobeHub）

- 日期：2026-11-22
- 性质：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D4 维的二级专项——对《reference_ad_tool_security_teardown_2026-11-22.md》轴3（执行面架构）与轴6（沙箱隔离）中"跨主机/跨设备执行"部分的再细拆（竞品/外部对标，研究参考，不作产品事实源）
- 对象与证据：lobehub/lobehub（canary@2026-11-21 快照）vs 本仓主干。只读深读：对方 `device-gateway-client`/`device-control`/`device-identity`/`device-mcp`/`local-file-shell`/`builtin-tool-remote-device`/`cloud-sandbox`/`electron-server-ipc`/`apps/cli` vs 本仓 `tool_executor.py`（computer_ssh_exec/computer_shell）/`computer_use/ssh_runner.py`/`web_reach/credentials.py`/`agent/neuacp/ssh_transport.py`+`process_pool.py`/`relay/`/`tunnel/`/`guest_agent/`/`computer_use/rdp_provider.py`+`sandbox_provider.py`/`tool_layers/mcp_*`。全部结论带 file:line。
- 评分口径：本专项 10 轴 ×10 分 = 100 分（与总报告 D4、工具安全拆解互相独立，粒度最细）。

## 0. 结论摘要

**专项总分：LobeHub 84.5/100 vs Neurova 78.0/100**——对方胜在远程执行是产品主架构（设备网关双层授权+设备端防逃逸+云沙箱+厚测试），本仓胜在形态广度（六种已接线形态，含对方没有的"中继代部署"与"来宾机多后端"）。

- LobeHub 最强：**设备网关闭环**——服务端派发→Cloudflare Durable Object 复验 token claim→设备 WS 长连→Redis BLPOP 等结果→超时 clamp→离线 hold 窗口（timeout+45s 后才答 503 DEVICE_OFFLINE，"never ran, safe to retry"）→异步长命令 park+迟交回灌；服务端 `assertWorkspaceRootApproved` 堵"自带 workingDirectory=/"漏洞，设备端 realpath 前缀包含防符号链接逃逸，派发前最后一刻再验 dispatchAuthorization。
- Neurova 最强：**形态广度与凭据纪律**——六种远程形态（SSH 命令/外部代理 SSH/中继代部署/移动隧道/远程 MCP/来宾机桌面），按用户加密凭据桶（AES-256-GCM+DPAPI，GET 永不回显）、缺凭据 WS 弹"按需凭据卡"当场续跑、neuacp key_ref 只透引用名私钥不落名册、中继代部署可撤销全审计、进程池键含租户段。
- 双方共同短板：**远程身份证明都弱**——对方 deviceId 无 attestation（fallback UUID 可自报），本仓 SSH host key 全 AutoAddPolicy（TOFU）；凭据都无轮换机制。
- 一句话：对方是"**一台被双向鉴权网关管起来的远程设备**"，本仓是"**六条各自成路的远程通道**"——深度对方领先 6.5 分，广度本仓不落下风。

## 1. 十轴评分表

| # | 轴 | 满分 | LobeHub | Neurova | 判定 |
|---|----|-----:|--------:|--------:|------|
| 1 | 远程形态覆盖 | 10 | 9.0 | 8.5 | L 胜 |
| 2 | 通道与传输安全 | 10 | 8.5 | 7.5 | L 胜 |
| 3 | 远端身份与准入 | 10 | 7.0 | 6.5 | L 小胜 |
| 4 | 命令下发授权与租户隔离 | 10 | 9.0 | 8.5 | L 胜 |
| 5 | 远程执行隔离档位 | 10 | 8.5 | 6.5 | L 胜 |
| 6 | 远程凭据管理 | 10 | 8.5 | 8.0 | L 小胜 |
| 7 | 结果回传与清算 | 10 | 8.5 | 7.5 | L 胜 |
| 8 | 失败处置与进程清算 | 10 | 8.5 | 8.0 | L 小胜 |
| 9 | 审计与合规面 | 10 | 8.0 | **8.5** | **N 小胜** |
| 10 | 测试与契约纪律 | 10 | 9.0 | 8.5 | L 胜 |
| | **合计** | **100** | **84.5** | **78.0** | |

## 2. 逐轴详拆

### 轴1 远程形态覆盖（L 9 / N 8.5）

**LobeHub**：五类——①设备工具派发（server→DO 网关→设备 WS，覆盖 local-system 全套文件/shell/git/RPC）；②本机 shell（设备主进程）+远程 PTY（node-pty 真伪终端，sudo 可用，5 会话 LRU/30min 回收/1M 环缓冲，`device-control/src/terminal.ts:45-78`）；③浏览器回环（云 agent 经网关代理回设备：desktop 走 renderer webview、CLI 走 headless agent-browser，按 topic 隔离，`serverRuntimes/browser.ts:17-31`）；④云沙箱（market/onlyboxes，executeCode python/js/ts+沙箱内文件/shell）；⑤设备 MCP（desktop/`lh connect` 在用户设备 spawn stdio MCP server）。
**Neurova**：六类——①SSH 命令执行（computer_ssh_exec，paramiko）；②外部代理 SSH（neuacp transport=ssh：ACP/plugin 成员经 `ssh -o BatchMode=yes -i <key> -- <cmd>` 在远端拉起）；③中继代部署（档三：agent 持面板 SSH 凭据上机装 systemd 中继，成功自动切 relay，可撤销）；④移动隧道（自托管 relay+出站 TunnelAgent+一次性 ticket）；⑤远程 MCP（streamable HTTP/SSE+OAuth PKCE+熔断重连）；⑥来宾机桌面执行（guest_agent HTTP 守护+RDP 直连+Windows Sandbox 一次性会话）。
**判定**：形态数 6:5，本仓多出"中继代部署"（agent 自己部署自己的接入基础设施）与"来宾机多后端"两个独有形态；对方的形态全部收敛在统一网关架构下、彼此共享鉴权与清算。L 9 / N 8.5。

### 轴2 通道与传输安全（L 8.5 / N 7.5）

**LobeHub**：设备侧主动外连 WebSocket；token 不走 URL、作为连接后首条 auth 消息（`client.ts:99,448-454`），支持 apiKey/jwt/serviceToken；服务端 Cloudflare DO **复验 token claim**（路由参数本身不授权，client.ts:411-413 注释），workspace 设备要求 token 携带匹配 workspace_id claim（:110-116）；心跳 30s/3 次未 ack 重连、15s watchdog 覆盖 TCP+TLS+upgrade+auth 全窗口、同 connectionId newest-wins 防回抢（:51,572-589）。**审计盲点：DO 服务端代码不在 OSS 仓**（无 wrangler 配置），网关可信依赖闭源云。
**Neurova**：中继为自托管（`relay/app.py`）——手机 wss/https→中继←agent 出站连接；routeId=HMAC(准入令牌,instanceId) 派生、不接受调用方指定（:57-66）；streamId 一次性认领（:205-209）；配对凭证 HMAC 签名 token+短时效 connect ticket 绑定 token_epoch（撤销级联失效，mobile_pairing :437-504）；TunnelAgent 出站拨控制 WS、指数退避重连（tunnel/agent.py:140-151）。**已知代价：中继终结 TLS**（明文在中继内存可见，:13-14 登记在案）。
**判定**：对方 token 后置+DO 复验更强但服务端不可审计；本仓全栈自托管可审计但中继见明文。L 8.5 / N 7.5。

### 轴3 远端身份与准入（L 7 / N 6.5）——双方都弱

**LobeHub**：deviceId=sha256(machineId|userId|SALT)（`device-identity/src/index.ts:54-79`）；machineId 读不到时降级持久 UUID|randomUUID 并自报 `identitySource:'fallback'`；**无 attestation/挑战应答**——设备可信完全建立在 token 上，服务端仅枚举校验自报 identitySource（guards.ts:18-30），受管云设备身份源只由服务端写入（:14-17）。
**Neurova**：SSH 侧凭据从按用户加密凭据桶解析（platform=ssh 按 host 分键，AES-256-GCM 落盘+DPAPI 保护 keyfile，GET 永不回显，`web_reach/credentials.py:74-126`）；但两处 paramiko 均 **AutoAddPolicy（TOFU）**、无 known_hosts 校验（ssh_runner.py:64、remote_deploy.py:92-93）——中间人可冒充主机。
**判定**：对方的弱点是"设备可自报身份"，本仓的弱点是"主机可被冒充"；都缺强身份证明。L 7 / N 6.5。

### 轴4 命令下发授权与租户隔离（L 9 / N 8.5）

**LobeHub**：服务端 `assertDeviceOperable`（公共工作区设备=任意非 viewer 成员，私有=原注册成员或 owner，guards.ts:70-93）+`assertNotManagedDevice`（受管云设备禁 client 改写/share，:36-41）+`assertWorkspaceRootApproved`（workingDirectory 必须落在服务端持有的 device row 派生目录内，堵"自带 workingDirectory=/"，deviceWorkspaceGuard.ts:194-228）+陈旧连接 fail-closed NOT_FOUND（:269-277）+派发前最后一刻 `dispatchAuthorization.ts:20-40` 复验；设备端 `assertEntriesWithinWorkspace` realpath 前缀包含防符号链接逃逸（workspaceGuard.ts:52-65）、trash 永不硬删除、能力未注入给稳定 `*_UNSUPPORTED` 拒绝（dispatch.ts:168-185,425-432,587-643）。
**Neurova**：neuacp 进程池键含租户段（`(tenant, tool, command, cwd, transport, remote)` 六元组，process_pool.py:74-93）；SSH 工具走 shell 分段审批（每段展示，security/governance.py:138-169）+治理预检+ASK 裁决有界阻塞（tool_executor.py:1986,2142）；中继代部署仅 admin+触发即确认+审计 CONFIG_CHANGE/HIGH；MCP 按用户隔离。
**判定**：对方"服务端目录白名单+设备端 realpath+最后一刻复验"的三层授权是本仓没有的深度；本仓租户段进程池与分段审批是对应强项。L 9 / N 8.5。

### 轴5 远程执行隔离档位（L 8.5 / N 6.5）

**LobeHub**：云沙箱（market 默认/onlyboxes 自托管）与设备链路独立，executeCode python/js/ts+沙箱内文件/shell，share visitor 场景禁用 `lh` shim 防凭据交给不可信 shell（serverRuntimes/cloudSandbox.ts:27-45）；设备端 opt-in "Local Sandbox"（自认 PoC，沙箱失败**绝不回退**未沙箱执行，ShellCommandCtr.ts:330-332）。
**Neurova**：远程 SSH 执行依赖目标主机自身隔离（agent 侧不提供）；来宾机形态有 Windows Sandbox 一次性会话与 RDP 直连（sandbox_provider.py/rdp_provider.py，真实拉起依赖人工验收，半自动化）；本机 run_code 有 restricted_token/appcontainer，但那是本机档非远程档。
**判定**：对方云沙箱是真实可用的远程强隔离档；本仓 Windows Sandbox 形态存在但自动化程度低。L 8.5 / N 6.5。

### 轴6 远程凭据管理（L 8.5 / N 8）

**LobeHub**：creds 工具值统一 `******` 永不进模型上下文（injectResult.ts:34-58）；secret-channel HPKE 端到端信道（未接线）；桌面 keytar/safeStorage；device token 分 apiKey/jwt/serviceToken 三型。
**Neurova**：按用户加密凭据桶（AES-256-GCM+DPAPI keyfile，GET 永不回显）；**按需凭据卡**——SSH 缺凭据时经 WS computer_action 通道弹卡、用户补录后轮询 90s 当场续跑（tool_executor.py:7622-7634,7668）；neuacp key_ref 只透引用名、私钥路径 spawn 期经 key_resolver 解析、明文私钥不落名册（ssh_transport.py:30-40,81-93）；MCP OAuth client_credentials+PKCE、token 提前 60s 刷新、401 强制刷新重试（mcp_oauth.py:19-46）。**无凭据轮换机制**（SSH/RDP）。
**判定**：本仓"按需凭据卡+key_ref 引用名"体验与安全兼顾是差异点；对方"永不进上下文"纪律+三型 token 更严。L 8.5 / N 8。

### 轴7 结果回传与清算（L 8.5 / N 7.5）

**LobeHub**：Redis `BLPOP tool_result:{toolCallId}` 专用连接阻塞等结果（多 key 共享 deadline，ToolResultWaiter.ts:31,74-137）；设备离线 hold 至 timeout+45s 才答 503 DEVICE_OFFLINE（"never ran, safe to retry"，http.ts:24-31）；长 shell 超窗 park→设备 completionWatch 承诺迟交→`/api/agent/device-tool-completion` 回灌（principal 不匹配 403/幂等 onlyIfEmpty/placeholder 未就绪 503 重发/ack 30s 超时重发，asyncShellPark.ts:15-54、deviceToolCompletion.ts:50-112、client.ts:307-333）。**自认最弱环：清算链路长、多版本设备兼容分支多**。
**Neurova**：SSH 同步捕获 returncode/stdout/stderr（ssh_runner.py:83-90，timeout 默认 60s）；中继每请求一条数据连接、HTTP 缓冲搬运/WS 逐帧搬运（relay/app.py:255-356）；隧道状态机 probing/via_relay/relay_down。
**判定**：对方的"离线 hold+安全重试语义+异步迟交回灌"是生产级清算设计（尽管链路长）；本仓同步模型简单可靠但长任务与设备失联场景表达力弱。L 8.5 / N 7.5。

### 轴8 失败处置与进程清算（L 8.5 / N 8）

**LobeHub**：设备 MCP 进程树回收——Windows PowerShell CIM 快照 BFS 收集后代 pid+taskkill 批量 20/批（process-tree.ts:41-75）；会话守卫：仅 transport 级失败（404/MCPConnectionError）允许换新会话重试，**应用层失败不重试防变异工具二次副作用**（sessionGuards.ts:44-51）；死传输驱逐池化会话（:66-68）。
**Neurova**：进程池空闲 FIFO 复用+惰性清扫+池故障 fail-open 退直启（swarm.py:3112-3114）；remote-undeploy 撤销代部署（remote_deploy.py:366-415）；subagent cancel/rollback 工具族；relay_down 指数退避。
**判定**：对方的"按失败类型分级重试+进程树清算"更细；本仓 fail-open/可撤销/取消族覆盖面广。L 8.5 / N 8。

### 轴9 审计与合规面（L 8 / N 8.5）——本仓小胜

**Neurova**：治理裁决审计（tool_executor.py:2018,2058）+桌面动作审计（:2890-2907）+代部署审计 CONFIG_CHANGE/HIGH+触发即确认；shell 分段审批每段展示给用户；租户进进程池键与生成域台账（e7382b863 先例）。
**LobeHub**：workspace_audit_logs 40+ 动作（D9 已计）；设备派发有 dispatchAuthorization 复验与 deviceExecutionTime/workRegistration 回执，但设备端命令级审计面在 OSS 仓内未见系统化落点（待核实云侧）。
**判定**：本仓远程链路的审计颗粒（裁决/桌面动作/部署/租户）更完整。N 8.5 / L 8。

### 轴10 测试与契约纪律（L 9 / N 8.5）

**LobeHub**：device-gateway-client 9 文件约 3.8k 行、device-control 21 文件约 3.9k 行、device-mcp 8 文件约 2.1k 行、device-identity 1 文件、服务端 deviceGateway 另有 9+ 专项测试、CLI e2e——单域测试厚度极高。
**Neurova**：命中 ssh/relay/tunnel/remote/pairing/mcp/guest/deploy 的测试 81 个文件（test_ssh_transport/test_ssh_exec/test_ssh_credentials/test_remoteDeploy/test_tunnelAdmissionAndChannelState/test_relayDeploymentKit/test_mobilePairingRemoteDeploy/test_guest_agent/test_mcp_* 等）+tests/manual 活体脚本；live-verify 揪缺陷当场修的纪律（配对/隧道/代部署均真机验证过）。
**判定**：对方单域密度高，本仓跨六形态覆盖面广+真机活体验证。L 9 / N 8.5。

## 3. 与总报告及工具安全拆解的关系

- 本专项是《reference_ad_tool_security_teardown_2026-11-22.md》轴3/轴6 的再细拆，结论方向一致（远程执行深度对方领先）且更细：等权 84.5 vs 78.0。
- **不改总报告 D4 评分**：工具安全拆解（v7）已把该差距计入轴3/轴6（L 9/7.5 与 L 9/7），本专项未发现新的方向性误判；D4 维持 L 12.0 / N 11.5。
- 本仓反超项（轴9 审计）与可借鉴点清单见下节。

## 4. 可借鉴点——工具与执行安全全量（待拍板，非立即实施）

本节为 **D4 工具与执行安全全域的可借鉴点单一收口**（不止远程执行——含《reference_ad_tool_security_teardown_2026-11-22.md》全部轴与远程执行二级专项的全部条目；工具安全拆解 §4 已改为指向本节，不另立第二份清单）。按价值分档；来源轴标注在条目首，均附对方证据与本仓落点。

P0（安全实益，直接补缺口）：
1. **SSRF 防护收敛为专用包+lint 强制**（源：工具安全轴7）：把 http_fetch 逐跳守卫与各咽喉点校验收敛为单一 safe-fetch 模块（私网/环回/link-local/meta IP 逐跳过滤+体积上限+可识别异常），并以自定义静态检查强制新出站代码走它。影响面=http_fetch.py、web_reach、rss_read、knowledge_ingestion、model_runtime 媒体下载（对方 `ssrf-safe-fetch/index.ts:182-213`+alint no-unsafe-user-url-fetch 规则）。
2. **SSH host key 校验收紧**（源：远程执行轴3）：本仓两处 paramiko 均 AutoAddPolicy（TOFU，`ssh_runner.py:64`、`remote_deploy.py:92-93`）——改为 known_hosts 校验+新主机首接确认卡（可配置严格模式）。本仓远程链路当前最实的安全缺口。
3. **离线 hold 与"never ran, safe to retry"语义**（源：远程执行轴7，`http.ts:24-31`）：设备/主机失联时先 hold 至超时+宽限窗，再返回明确的"未执行、可安全重试"错误——消除"不确定远端是否已执行"的重复执行风险。
4. **派发前最后一刻授权复验**（源：远程执行轴4，`dispatchAuthorization.ts:20-40`）：审批通过与命令真正发出之间存在时间窗，目标/范围可能已被改——发出前再验一次归属与范围。

P1（可靠性/架构增强）：
5. **沙箱补档位**（源：工具安全轴6）：现有 restricted_token/appcontainer 之上评估容器级或 WASM 级第二档（对方 Pyodide/云沙箱形态），让 run_code 有"进程隔离"与"强隔离"两档可选。
6. **动态干预审计注册表**（源：工具安全轴9）：把"越出工作区即问/永久删除必问"类参数级动态审计做成声明式注册表（对方 `dynamicInterventionAudits.ts:13-20` 形态），与本仓审批链 L0-L2 叠加。
7. **工具 manifest 增补运行元数据**（源：工具安全轴1）：defaultTimeoutMs clamp 区间、是否可序列化/有序执行等进 `_BUILTIN_SCHEMAS` 单源（本仓已有 capability 声明，补齐超时/序列化维度；对方 `types/src/tool/builtin.ts:144-151`）。
8. **长命令 park+迟交回灌**（源：远程执行轴7，`asyncShellPark.ts:15-54`、`deviceToolCompletion.ts:50-112`）：超窗命令转后台承诺+结果迟交+ack 超时重发——补 SSH 同步 60s 模型对长任务的表达力。
9. **token 后置连接认证**（源：远程执行轴2，`client.ts:99,448-454`）：token 不进 URL、作为连接后首条 auth 消息、服务端复验 claim——加固本仓 relay/tunnel 通道（现凭据经 URL/头，中继侧可见）。
10. **newest-wins 连接顶替+全窗口 watchdog**（源：远程执行轴2，`client.ts:51,572-589,36-42`）：同 connectionId 新连接顶替旧连接防回抢；watchdog 覆盖 TCP+TLS+upgrade+auth 全窗口——本仓 TunnelAgent 重连逻辑可借。
11. **进程树清算**（源：远程执行轴8，`process-tree.ts:41-75`）：PowerShell CIM 快照 BFS 收集后代 pid+taskkill 批量击杀（20/批）——补强本仓进程池清扫与子代理进程回收。
12. **失败分级重试守卫**（源：远程执行轴8，`sessionGuards.ts:44-51`）：仅传输级失败允许换会话重试，应用层失败不重试——防变异类工具被重试造成二次副作用。

P2（体验/生态/强制面）：
13. **结构化 \*\_UNSUPPORTED 拒绝**（源：远程执行轴8，`dispatch.ts:168-185,587-643`）：能力未注入时返回稳定错误形态而非异常——本仓工具错误分类学可对齐。
14. **设备/端能力声明路由**（源：远程执行轴8，`systemInfo.ts:93-119`+Redis 缓存 `keys.ts:374-377`）：按端上报的 supportedTools/clientKinds 把调用路由到能执行的端——本机/来宾机/RDP/Sandbox 多后端统一选端。
15. **HPKE 级凭据信道评估**（源：工具安全轴8）：对方 secret-channel（RFC 9180）实现精良但未接线——本仓凭据面若需跨进程/跨端传递可参考，不接线不加分。
16. **MCP Apps 交互 UI**（源：工具安全轴4）：对方 SEP-1865 支持——本仓 MCP server 面可评估补 UI 约定。
17. **云沙箱双 provider**（源：远程执行轴5，`deployment.ts:6-14`）：market 托管/onlyboxes 自托管双轨——本仓沙箱档位可评估同款"托管+自托管"并存。
18. **设备通道多型 token**（源：远程执行轴2，apiKey/jwt/serviceToken，`client.ts:99`）：不同信任域用不同 token 类型，便于撤销与最小授权。
19. **不可信会话凭据隔离**（源：远程执行轴5，`cloudSandbox.ts:27-45`）：share visitor 场景禁用凭据 shim，防凭据交给不可信 shell——本仓分享/来宾场景可借。
20. **浏览器会话按 topic 键控+截图落盘**（源：远程执行轴5，`browser.ts:28-31,74-111`）：会话隔离与产物落盘纪律。
21. **alint 式安全 lint 扩展**（源：工具安全轴10）：以模型背书 lint 守 no-shell-command-injection/no-secret-exposure/no-unsafe-raw-sql 类安全判据（误报率定级后设 error）——补静态规则表达不了的安全判据。

不照搬：Electron IPC 零对端鉴权的本地信任模型（对方最弱环之一，`ipcServer.ts:64-102`）；闭源云侧网关依赖（本仓中继自托管可审计是对应优势，补 TLS 终结说明即可）；DO 状态机整体迁移（成本高且强绑云服务）；local-system 主进程直执行（对方弱项，本仓沙箱族路线更对）。

## 5. 本仓守卫提示（对方没有、勿被"对齐"掉）

1. **按需凭据卡**：缺凭据当场弹卡续跑（不落明文、不中断任务流）——体验与安全兼顾的独有形态。
2. **key_ref 引用名**：外部代理名册只透引用名，明文私钥不进名册。
3. **中继代部署**：agent 持凭据代部署自建中继、可撤销、全审计——对方无此形态。
4. **租户段进程池**：远程外部代理进程池键含租户，与生成域租户硬化同纪律。
5. **来宾机多后端**：guest_agent/RDP/Windows Sandbox 多后端桌面执行，对方无对应物。
