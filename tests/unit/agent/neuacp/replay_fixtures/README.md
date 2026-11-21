# neuacp 真实 transcript 回放 fixtures（G2）

本目录存放**真实 CLI 子进程的一手 transcript**（JSON fixture），由
[`scripts/neuacp_record_fixture.py`](../../../../scripts/neuacp_record_fixture.py)
录制：用真 `NeuacpClient` 拉起真 CLI、按共享场景脚本执行，双向帧经真
frame_log 账本（写盘前内嵌脱敏）留痕后落盘。契约测试
[`../test_replay_contract.py`](../test_replay_contract.py) 对每份 fixture
用真客户端管线**离线回放**（注入 transport），断言握手结果 / 步骤结果 /
事件回调序列 / 转录帧序与录制时一致，并以三类变异（相邻帧互换 / 丢帧 /
改字段类型）防恒真。

重新录制：

```bash
.venv/Scripts/python.exe scripts/neuacp_record_fixture.py --family opencode --scenario handshake
.venv/Scripts/python.exe scripts/neuacp_record_fixture.py --family opencode --scenario all
```

## fixture 形态

```json
{
  "fixture_version": 1,
  "family": "opencode",            // 目录键（catalog 单源）
  "scenario": "handshake",
  "recorded_at": "2026-11-21T...Z",
  "command": ["C:\\...\\opencode.CMD", "acp"],  // 录制时实际解析出的命令
  "cwd": "...",                    // 录制工作目录（一次性 scratch，仅作字符串随帧复用）
  "steps": [ {"op": "start", ...}, ... ],       // 场景步骤脚本（解释器单源在 replay_harness）
  "frames": [ {"seq": 1, "direction": "out|in|observed", "frame": {...}} ],
  "expected": { "steps": [...], "events": [...] }  // 录制时客户端行为，回放断言的基准
}
```

帧载荷已脱敏（结构级字段名 + 值级单源 `redactFrame`，落盘前后各一遍）。

## 录制矩阵（家族 × 场景）

录制环境：Windows 10.0.26300，opencode 1.2.27，node v24.14.0（npx 缓存内含
claude-agent-acp 0.109.0 / codex-acp 2.8.0）。✅=已录；❌=未录（原因如实登记）。

| 家族 \ 场景 | handshake | version_mismatch | prompt_end_of_turn | cancel_mid_prompt | permission_request |
|---|---|---|---|---|---|
| opencode | ✅ 3 帧 | ✅ 3 帧 | ✅ 7 帧（超时路径） | ✅ 10 帧 | ❌ 真实 CLI 未触发权限申请（prompt 被鉴权墙挡住，未走到任何工具调用） |
| claude-code | ✅ 5 帧 | ✅ 3 帧 | ✅ 11 帧（-32000 鉴权错误路径） | ❌ 不适用：prompt 被鉴权墙秒拒，4s 的 cancel 定时器未及发出，transcript 中无 session/cancel 帧（已按诚实纪律删除该退化 fixture） | ❌ 真实 CLI 未触发权限申请 |
| codex | ✅ 4 帧 | ✅ 3 帧 | ✅ 6 帧（session/new 即 -32000 鉴权错误路径） | ❌ 不适用：session/new 被拒，无会话可取消 | ❌ 不适用：无会话 |
| gemini-cli | ❌ 本机未安装 gemini CLI | ❌ 同左 | ❌ 同左 | ❌ 同左 | ❌ 同左 |

「错误路径也是契约」：无凭据环境录到的超时 / `-32000 Authentication required`
分类同样入 fixture 并参与回放断言——这正是外部 agent 接入回归网需要钉住的
失败形态。一旦本机配置了凭据，可用同一脚本重录，把成功路径的 transcript
换进来（fixture 与测试代码无需改动）。

## 协议陷阱清单（录制过程实际踩到的问题）

1. **protocolVersion 线上必须是整数**。本仓客户端曾发字符串 `"1"`，假 agent
   不校验类型故从未暴露；真实 CLI 按规范（ProtocolVersion = integer/uint16）
   以 `-32602 Invalid params` 拒绝。本目录全部 out 方向 initialize 帧钉的是
   整数 `1`；变异测试「改字段类型」专门覆盖此形状（int→str 必须变红）。
2. **initialize 应答字段名是 `agentCapabilities`**，不是本仓假 agent 里的
   `serverCapabilities`。消费方不能按后者取能力。
3. **opencode 的 stopReason 不守规范字面**：cancel 冲刷掉的 prompt 回的是
   `"end_turn"`，而非 ACP 规范的 `"end_of_turn"`。按字面穷举匹配的消费方
   会漏判；本仓 executor 侧对此是透传处理，fixture 已钉住该真实取值。
4. **适配器会主动推送非标准通知**：`_auth/status_update`（claude-code 与
   codex 都推）和 `auth/status_update`（仅 claude-code，参数形态还不同）在
   initialize 应答之后不请自来。客户端必须容忍未知方法的通知（本仓客户端
   将其落入 on_event，不视为协议错误）。
5. **鉴权墙的两种形态都被录到**：codex 在 `session/new` 就诚实回
   `-32000 Authentication required`；opencode 则对 prompt **既不报错也不
   应答地静默挂起**（探针等待 60s+ 无任何帧）——后者只能靠请求超时
   （`NeuacpTimeoutError`）收口，是最恶劣的失败形态，fixture 按超时路径
   如实录制。
6. **Windows 下 PATH 里的 `opencode`/`npx` 是 .cmd 垫片**，`Popen` 不解析
   PATHEXT 会直接 `WinError 2`；必须 `shutil.which` 解析成全路径（本仓
   客户端已内置）。回收必须树杀（`taskkill /T /F`）：垫片会孵化 node 子进程
   继续持有管道，单杀垫片会让 stderr/stdout 读端永远等不到 EOF。
7. **回放 transport 的保序陷阱**（录制/回放工具侧踩到）：客户端
   `_sendFrame` 是「先记 out 帧进账本、再 flush」；若假 transport 在
   `write()` 时就让 out 帧可见，供帧会抢在账本记账之前，制造「in 先于
   其应答的 out」的假序。真管道因缓冲天然保序，transport 必须在
   `flush()` 时才把帧交给读端（`ScriptedTransport` 已按此实现）。
8. **observed 帧的 `exit_code` 不可作契约**：真机树杀退出码随时序在
   0/1/未观测之间摆动，回放 transport 恒为 0。帧序对比统一剥掉
   `exit_code`，只钉「进程收口有 observed/exited 观测」。
9. **opencode 的 session/new 应答携带大块 models 清单，并随即主动推送
   `available_commands_update`**。这些不是噪声：事件序列与帧序一样属于
   契约，回放断言逐帧逐事件核对。

## 回放实现选择

采用**注入 transport**（`replay_harness.ScriptedTransport` + 替换
`acp_client.subprocess.Popen`），不起真子进程：被测对象是客户端管线本身
（真分帧 / 真 dispatch / 真 frame_log / 真脱敏），fixture 已是真实 CLI 的
一手 transcript；真子进程会把 .cmd 垫片、树杀时序、管道缓冲等不稳定因素
带进契约断言。每个 in 帧带「此前 out 帧数」阈值，客户端真实写出足量请求
后才供帧，保住「请求先于应答」的因果序。
