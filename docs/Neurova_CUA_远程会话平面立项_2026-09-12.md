# CUA Phase 3 扩展立项：远程会话平面（RS-1~5，隔离桌面的自建轻量路线）

> **provider 补全（2026-09-12 追加）**：~~RS-3 `container_provider.LinuxContainerProvider`（docker webtop GUI）~~ **已移除**——真实需求是"远程跑命令"，Linux/macOS 远程改走 **SSH 命令**（`computer_use/ssh_runner.py` paramiko key+密码 + `computer_ssh_exec` 工具，前端 computer-use 面板加**终端视图**渲染 `$命令+stdout+stderr`，即"SSH 窗口"）。RS-4 `rdp_provider.RdpDirectProvider`（凭据分桶 platform=rdp，不 spawn，destroy no-op）保留（面向已装 guest agent 的 Windows 既有机器 GUI）；`session_pool.build_provider` 仅 sandbox/rdp；`_sandbox_scope` 沙箱自动领用保留（Windows GUI 用）。**运行档对 SSH 命令**：review→审批，full/sandbox/auto→放行（远程已隔离，"进沙箱"对命令无意义）。live：RDP provider→池→领用→route=remote→guest→actions 闭环。至此 Windows=GUI（Sandbox/RDP+UIA+SOM），Linux/macOS=SSH 命令。
>
> **SSH 凭据配置闭环（2026-09-12 追加）**：`UserCredentialStore` 加 `set/get/list/delete_ssh_host`（多主机按 `ssh::<host>` 分键，加密落盘，列表脱敏）；`ssh_runner` 支持粘贴私钥 `key_text`（paramiko pkey，优先 key_path/password）+ per-host `resolve_ssh_credentials`；API `GET/POST/DELETE /v1/settings/ssh-credentials`（登录自管）；前端设置-高级"SSH 远程主机"卡（增删改 + 私钥/密码切换）+ i18n×11。live：配两台→脱敏列表→按 host 解析→key_text→pkey→远端输出。至此 computer_ssh_exec 端到端可用（真机连接仍需真实 host）。

> **交付状态（2026-09-12 实施）**：RS-2 guest agent ✅（`neurova/guest_agent/` FastAPI 8765 复用 actions.py/desktop_uia + token 鉴权 + client，8 测绿）；RS-1 remote 后端 ✅（`computer_use/remote_backend.py` 同 duck-type 代理 + `attach_remote_action_result` route=remote/delivery=background + ContextVar 会话路由，默认无绑定=本地零回归）；RS-3 会话池 ✅（`computer_use/session_pool.py` claim/release/per-user 复用/容量上限/空闲 TTL，provider 抽象）；RS-4 Sandbox 提供者 ✅（`computer_use/sandbox_provider.py` wsb XML 生成确定性 + runner 注入，真机 sandbox.exe 拉起留人工验收）。RS-5 可选项未做（按需）。11 测绿。详见 [[neurova-cua-phase3-rs-implementation]]。
>
> **生产触发层（2026-09-12 追加）**：`computer_use/runtime_policy.py` 桌面运行权限 4 档——full（本机，默认零回归）/ sandbox（变更动作进隔离会话，无会话则拒）/ review（变更动作经 ApprovalManager 审批，批准后重放执行）/ auto（低风险自动、中高风险进沙箱）。门挂在 `tool_executor._desktop_runtime_gate`（computer_* 分发），审批重放经 ContextVar 旁路防死循环；前端设置-高级加运行档选择器（i18n×11）。"何时领用沙箱会话"由用户选档 + `use_remote_session(pool,user)` 编排胶水落地，会话池 provider 就绪即生效。
>
> **provider 补全（2026-09-12 追加）**：RS-3 `container_provider.LinuxContainerProvider`（docker run webtop + 随机端口映射 + guest token env + per-user label，docker port 解析，runner 可注入）✅；RS-4 `rdp_provider.RdpDirectProvider`（凭据分桶 platform=rdp 取既有机器端点，不 spawn，destroy no-op 不触碰真机，无授权 fail-closed）✅；`session_pool.build_provider(name)` + `get_default_desktop_pool()`（env `NEUROVA_DESKTOP_PROVIDER`）工厂 ✅；`tool_executor._sandbox_scope` 把 sandbox/auto 档的变更动作核心执行包进 `use_remote_session`（领用→绑定→执行→归还，guest 自持 generation 跨动作复用）✅。live 端到端：RDP provider→池→领用→route=remote→guest→actions 全链闭环。至此 Windows(Sandbox+UIA)/Linux(container+像素)/RDP直连 三后端可选领用；macOS 仍按立项书暂不纳入。

> 立项日期：2026-09-12
> 来源：docs/Neurova_CUA升级方案_2026-09-12.md 第 6 节（取代 Cua Fleet 式云桌面池化的自建方案）
> 性质：架构新建（非缺陷修复）——净 LOC 为正，验收看"agent 在隔离桌面跑通既有 computer_* 契约 + local 后端零回归"
> 前置：Phase 1 的 `actions.py` 提取（动作实现与宿主解耦）+ `action_result.py` 契约 + `desktop_uia.py` 语义层，均已交付
> 关联代码：neurova/computer_use/（actions.py、__init__.py ComputerUseManager、action_result.py）；新组件 neurova-guest-agent、DesktopSessionPool

---

## 1. 核心判断（为什么自建而非集成 Fleet/闭源 SaaS）

Fleet 的本质**不是"远程桌面协议"**，而是三层：**容器/VM 托管 + 来宾内控制守护进程 + 显示流**。远程桌面协议只承担"人看"那一层。关键洞察：

> **Agent 的动作永远走控制面（HTTP/WS），不走显示协议。** 显示层的延迟/画质/协议差异对 agent 成功率**零影响**。

Neurova 已有控制面（`computer_*` 契约 + ActionResult），缺的只是：① 把它搬进隔离来宾；② 一个进程内会话池管理器。Scrapybara 类闭源 SaaS 已 404 且方向是 SaaS，不纳入；RustDesk/Sunshine 客户端路线面向人工远控，不适合 agent 程序化通道，明确排除。

## 2. 现状（2026-09-12 实测锚点）

- `ComputerUseManager`（`neurova/computer_use/__init__.py`）当前只有 **local 后端**：pyautogui（像素）+ uiautomation/UIA（语义），动作实现已提取到 `actions.py`（宿主/来宾可共用同一份）。
- 本地模式的固有痛点：pyautogui 全局输入**抢用户焦点/移动真实光标**，ActionResult 只能标 `unverifiable/global_input/foreground`（诚实降级，Phase 1 已做）；governance 的 `_platform_has_enforced_sandbox()` 在无真隔离时把 SANDBOX 级动作**升 DENY**——HIGH 风险动作在本地根本跑不了。
- 前端 `ComputerUsePanel.vue` 已实时收 `computer_action` 截图帧（分屏面板）——远程模式显示层**零新增前端工作**。

## 3. 整合架构（工具面零改动）

```
聊天页 Agent                Neurova 服务端                      远程会话平面（★新增）
computer_* 工具 ──调用──▶  tool_executor（dispatch 不变）
                           ├─ governance/approval（不变）
                           └─ ComputerUseManager 扩展
                               ├─ backend=local（现状，兜底不动）
                               └─ backend=remote ★
                                    │ claim()/release() 来自池管理器
                                    ▼
                          DesktopSessionPool ★进程内（非 K8s，数百行）
                            预热 N 个来宾、claim/release、空闲 TTL、
                            差分盘/Sandbox 重置、per-user 标签
                                    ▼
                          neurova-guest-agent ★来宾守护进程（端口 8765 WS+REST）
                            复用 actions.py → 暴露与本地一致的 computer_* 动作
                            + 显示流：截图帧(现有 WS)/noVNC/Selkies/RDP
                                    ▼
                          容器 webtop(Linux)/dockur-windows( Linux宿主)
                          VM   Windows Sandbox/Hyper-V(Windows宿主)
```

**三个设计要点**
1. **控制面/显示面分离**：agent 动作 = HTTP/WS 到来宾守护进程；显示协议只给人看。
2. **来宾复用现有契约**：guest agent 共用 `actions.py` → `computer_*` schema、ActionResult、governance 语义**一字不改**，仅 route 增 `remote` 档、delivery 天然 `background`——本地"非侵入"难题在远程模式**自动消失**（来宾是隔离机，抢不到用户真机焦点）。
3. **池是进程内的**：`DesktopSessionPool` 把 Fleet 的 WarmPool/Claim CRD 概念翻译成单进程内的预热/领用/归还/重置，非 K8s。

## 4. 分五个可独立验收的批次（RS-1~5）

| 批次 | 交付 | 依赖 | 独立验收判据 |
|---|---|---|---|
| **RS-1** | **Windows Sandbox 后端**：本机一次性隔离桌面；ComputerUseManager 加 `backend=remote` 路由 + 来宾占位；截图流复用现有面板 | Phase 1 actions.py 提取 + desktop_uia | 一个 HIGH 风险动作在 Sandbox 内跑通且 `delivery=background`、local 后端行为零变 |
| **RS-2** | **来宾守护进程 neurova-guest-agent**：端口 8765 WS+REST，暴露与本地同名 computer_* 动作（Sandbox/容器内同一守护进程） | RS-1 | 经 guest agent 的 click/type/dom_snapshot 返回 ActionResult 与本地**逐字段等价**（契约测试） |
| **RS-3** | **Linux 容器后端**：webtop 镜像 + 内置 guest agent 定制 Dockerfile + `DesktopSessionPool`（预热/claim/release/TTL/per-user） | RS-2 | 池并发 claim 两用户互不串会话；空闲 TTL 到期回收；容器崩溃 release 不泄漏 |
| **RS-4** | **RDP 直连后端**：把用户已授权的既有机器当会话后端（不造池）；凭据走现有凭据分桶 | RS-2 | 未授权机器不可达；凭据不落镜像/明文；断开自动 release |
| **RS-5** | 可选增强：dockur/windows（Linux 宿主一次性 Windows，预热池+差分盘缓解拉起慢）、Guacamole 网关（多协议聚合+会话录制审计联动 R3-4）、neko（多人围观审批现场）、Selkies（低延迟人类接管） | RS-3 | 每项各自独立开关，任一不装不影响 RS-1~4 |

建议实现序：RS-1→RS-2 是骨架（先在 Windows 生产现状上验证"来宾+控制面"闭环），RS-3 起横向扩展到 Linux/Docker，RS-4 是"连接既有机器"的旁路，RS-5 纯按需。**全程 local 后端始终兜底——远程是增强不是替换，远程全挂系统照常跑。**

## 5. 该平面顺带解决的三个老问题

1. **"非侵入"从难题变默认**：远程 `delivery=background` 天然成立，ActionResult 在远程档最干净。
2. **沙箱一致性升级**：governance 在远程后端拿到**真隔离** → HIGH 风险动作从"DENY"变"可跑"，agent 能力上限直接提升（`_platform_has_enforced_sandbox()` 的诚实升级规则命中）。
3. **审批现场可视化**：approval 流 + 来宾桌面截图流（或 noVNC/Selkies 接管）让"人工确认再执行"有操作现场，不再只读参数列表。

## 6. 目标与非目标

**目标**：agent 能在"另一台一次性/受控计算机"上执行桌面任务，工具面对上层**完全无感**（同 schema、同 ActionResult、同治理）。
**非目标**
- 不替换 local 后端。
- 不引入 K8s/编排平台（进程内池足够）。
- 不把显示协议当动作通道（红线）。
- 不在镜像里烘焙凭据。

## 7. 风险与缓解（诚实清单）

| 代价 | 说明 | 缓解 |
|---|---|---|
| Windows Sandbox 局限 | 每次全重置（无持久态）、需 Win Pro+、嵌套内存开销 | 持久态走 Hyper-V 差分盘或 RDP 直连；Sandbox 定位=高风险一次性任务 |
| dockur/windows 拉起慢 | 首次 ISO 下载+安装分钟级 | 预热池 + 差分盘快照；`/oem` 脚本预置 guest agent |
| Windows 许可 | dockur/windows 不分发 Windows，需自备 license | 生产部署前法务确认；Sandbox 无此问题 |
| 镜像维护 | webtop/guest agent 镜像跟版本 | 固定 tag + 月度重建；构建脚本入库 |
| 显示流 HTTPS | Selkies/WebCodecs 需安全上下文（前端 :8100 是 http） | MVP 用现有截图流；上 Selkies 走反代 https |
| 多一层运维 | Docker/KVM/Hyper-V 依赖 | 全可选项，local 始终兜底 |
| 安全边界 | webtop 容器内默认 passwordless sudo、网络可达 | 容器网络隔离（无 INET 需求断网模式）、凭据不进镜像、per-user 容器沿用现有隔离审计 |
| 来宾守护进程 = 新 RCE 面 | guest agent 监听端口即执行任意桌面动作 | 仅 bind 127.0.0.1/容器内网、双向 token、与宿主同套 governance 闸门；默认随池销毁 |

## 8. 触发条件（何时开工）
出现以下任一真实需求时启动 RS-1/RS-2 骨架：① 需要无人值守/高风险桌面自动化（当前被 SANDBOX→DENY 卡住）；② 需要给多个用户各发一台一次性桌面做任务；③ 需要"人类可在现场接管审批"的操作可视化。否则挂账不占排期，local 后端持续演进。

## 9. 验收总则
- 每批次独立 TDD；RS-2 的"ActionResult 逐字段等价本地"是全平面的一致性锚点测试，后续批次不得削弱。
- 合入前跑 tests/unit/computer_use 全绿 + 新增 remote 后端用例，且 **local 后端全部既有用例零回归**（远程是增量，禁改本地行为）。
- 与 R3-4 联动：远程动作同样落 desktop_action_audit（若 R3-4 先落地）。
