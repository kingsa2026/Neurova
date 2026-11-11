# agent-reach CLI 内置工具接入与 social_search 死门修复（实施记录 2026-11-12）

## 0. 背景与裁定

将 agent-reach（CLI 面跨平台内容直达：GitHub/雪球/Boss直聘/LinkedIn/小宇宙/B站/V2EX/YouTube/小红书/Reddit 等）接入为本仓内置工具。

接入形态三选一（新工具并存／仅后端接线／全量替换自实现）征询未获回复，按推荐项执行：
**CLI 桥接＋新增 `agent_reach` 内置工具＋顺手修复 social_search 死门**。裁定的依据是
教义第 7 条对照（见 §2 owner 表）：四个零依赖自实现（web_fetch/bilibili_search/youtube_transcript/v2ex_hot）
是各自能力的现役 owner 不动；social_search 的后端门集成在两个**不存在的库模块**上
（`agent_reach.core`／`agent_reach.config`，PyPI 0.1.0 与源码仓 main 均无——前批实测
现量见 `tests/unit/web_reach/test_unavailableBackendIsNamedNotSilentEmpty.py` 旧 docstring），
属同根因命中点，一并收口。⑥ 乙案裁定（不删能力、不可得/未接入两种读数互不同形）延续，
其实现面从幽灵库 import 换成 CLI 面。

上游契约以 v1.6.0 实测为准（`doctor`/`channels`/`read`/`<channel> <action>` 真实输出）：
stdout 单行 JSON envelope、错误码 `{code,message,hint}`、doctor `channels` 为**列表**。
安装口径：`uv tool install https://github.com/Panniantong/Agent-Reach/archive/refs/tags/v1.6.0.zip`
（PyPI 同名包非本项目）；uv 产物落 `~/.local/bin` 常不在 PATH ⇒ 桥接按已知目录回退。

## 1. 交付清单

| 交付 | 落点 |
|---|---|
| CLI 桥接（唯一集成面） | `neurova/web_reach/agent_reach_cli.py`：可执行定位（PATH→uv bin 回退）、argv 直传（无 shell）、envelope 归一（成功/错误码/超时/非 JSON/未装各形态互不同形）、SSRF 门（`read` 模式入口过 `url_guard.assert_public_url`，位置参数拒绝 `-` 开头防 flag 注入） |
| 内置工具 `agent_reach` | schema 单源 `neurova/builtin_tools.py`＋分派/执行体 `neurova/tool_executor.py`＋超时表 `agent/tool_coordinator.py`（240s）。三 mode：`channels`（列渠道语法）/`read`（读链接自动选渠道）/`action`（渠道动作：search/quote/transcribe/subtitle…）。capability：readOnly＋shared 作用域（合取判据串行，防争用上游渠道会话） |
| social_search 死门修复 | `neurova/web_reach/reach.py`：`run_doctor` 换 CLI doctor（成功原样透传、失败点名）；`social_search` 阶梯＝CLI 不可得→backend_unavailable＋安装指引；渠道 not_added/needs_setup→接入引导（带上游 problems/hint）；就绪→CLI 渠道动作真实执行；NEED_LOGIN→登录引导。三种读数互不同形（⑥ 乙案） |
| 退役 | `neurova/web_reach/social_exec.py` 整文件（幽灵库集成的执行半边，仓库内零消费者）；`credentials.user_config_path`（为幽灵库 config_path 建的路径帮手，生产零消费）；`_web_reach_call` social 分支的 user_id 读取线（凭据分桶不再进工具执行路径） |

## 2. 能力 owner 对照（教义第 7 条对比记录）

| 能力 | owner（本批后） | 说明 |
|---|---|---|
| 普通网页读取 | `web_fetch`/`web_read`（Jina＋SSRF 门，零依赖） | agent-reach read 与其同源（Jina），无增量，不并列提供 |
| B 站搜索 | `bilibili_search`（yt-dlp bilisearch＋412 退避，零依赖） | 不动 |
| YouTube 字幕 | `youtube_transcript`（yt-dlp json3 实测沉淀） | 不动 |
| V2EX 热榜 / RSS | `v2ex_hot` / `rss_read` | 不动 |
| 社交六平台登录态搜索 | `social_search`（**本批复活**，走 CLI 渠道动作） | 旧 per-user 凭据 env 注入路径退役（从未成功执行过：门先死） |
| GitHub/雪球/Boss/LinkedIn/小宇宙/小红书/Reddit | `agent_reach`（CLI） | 本批纯新增面 |
| 平台链接富读取（自动选渠道） | `agent_reach` mode=read | 普通网页仍归 web_fetch |

## 3. 验收（红→绿→live-verify）

- **红灯**：`tests/unit/web_reach/test_agent_reach_cli.py`（桥接契约 17 格）＋
  `test_social_search_cli.py`（阶梯 6 格）＋`tests/unit/tools/test_agent_reach_tool.py`
  （三元组 8 格）＋夹具 `fixtures/tool_surfaces/agent_reach.json`——模块缺席期收集期红，
  实测输出见提交说明。
- **绿灯**：web_reach＋agent_reach 套件 96 passed；守卫族
  （schema/dispatch 对账、AST 参数、capability 三轴、不可重现名单、openai 格式源不可变、
  超时表诚实性、身份契约、子进程编码棘轮、dev 环境契约）305 passed／1 skipped。
  子进程编码棘轮 1 红（3 文件计数超基线）经 A/B 定性**预存**：涉事 3 文件与基线均与
  HEAD 一致、不在本批改动面。
- **live-verify（9527 真链路，.venv 重启后判据：[ERROR]=0＋Registered router /v1/providers）**：
  ① 工具清单 106 项含 `agent_reach`/`social_search`；② `mode=channels` 真跑 CLI
  14 渠道全语法（16KB 大输出走既有 output_ref 落盘）；③ `mode=read` example.com →
  channel=web/backend=jina/标题正确；④ `mode=action` github search → 诚实 RATE_LIMITED
  （上游错误码+hint 透传）；⑤ `social_search` twitter → **复活面**：「twitter 渠道未接入：
  运行 agent-reach add twitter」（此前恒「后端不可得…装不上」死门文案）。
  途中修一处：needs_setup/needs_login 返回补 `error` 键承载指引原文——咽喉/API 的
  成败映射只取 `error`，缺了它指引塌缩成笼统「工具执行失败」。

## 4. 尾巴格（不许静默遗留）

**§6-591 · 社交平台凭据切片退役——已闭环（2026-11-12 退役批）**。拆除面：后端
`settings.py` 三端点（GET/POST/DELETE `/social-credentials`）＋`SocialCredentialRequest`
模型、`credentials.py` 社交段（`set_platform_credentials`/`platform_status`/
`clear_platform_credentials`/`list_platforms`/`_KEY_TO_PLATFORM`，平台键集注册表清空）、
前端 `CredentialManager.vue` 社交卡＋`settings.ts` 三函数＋`SocialPlatformStatus`、
11 语言 10 个 `social*` 键＋`myCredentialsHint` 文案去社交从句。缺席守卫
`tests/unit/web_reach/test_social_credentials.py` 钉路由/符号/键集三缺席＋相邻活面
（SSH/RDP/通用桶）不误伤。验收：守卫 4 红→绿；后端相关套件 173 passed；前端双门
vitest 2449 passed＋vue-tsc exit 0；live-verify（9527 .venv 重启，[ERROR]=0）：
`GET/DELETE /social-credentials` → 404、`/ssh-credentials` → 200 存活、工具清单 106 项含
`agent_reach`/`social_search`。迁移口径：已录入社交凭据的读数改用 `agent-reach add/login`
（登录态归上游 CLI 浏览器会话）。

**§6-592 · RDP 直连凭据授权面——已接通（2026-11-12 接通批）**。面形态完全镜像 SSH：
`credentials.py` 新增 `rdp::endpoint` 单记录专用访问器（`set/get_rdp_endpoint`/`rdp_status`
脱敏/`delete_rdp_endpoint`，JSON 落加密桶）；`platform_credentials` 批量读与
`PLATFORM_REQUIRED_KEYS` 注册表随批退役（换专用访问器后注册表零消费者，缺席守卫
改钉）；`rdp_provider` 读线换 `get_rdp_endpoint`（旧 `platform_credentials("rdp")`
恒空读随之消灭）；`settings.py` 新增 `GET/POST/DELETE /rdp-credentials`（脱敏读、
host+首次 token 校验、空 token 不覆盖已设值、未配置 DELETE→404）；前端
`CredentialManager.vue` RDP 卡＋`settings.ts` 三函数＋12 键 i18n×11（撇号全走
U+2019 避插键坑）。验收：红灯 18（新面 404/缺方法/守卫未满足）→绿；后端
computer_use＋web_reach＋工具面 663 passed；前端双门 vitest 2454 passed＋
vue-tsc exit 0；live-verify（9527 .venv 重启，[ERROR]=0）：首次缺 token→422、
完整写入→200、GET 脱敏 token_set=true 不回显、空 token 更新 host 改 token 留存、
DELETE→200→再删 404、ssh-credentials 200／social 404／工具清单含 agent_reach。
provider 侧 resolver 接通由 `test_default_resolver_reads_credentials`（真 store 形态）
钉死——真机 guest-agent 连接须用户实际配置后使用。
