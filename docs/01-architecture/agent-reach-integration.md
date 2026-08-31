# Agent-Reach 整合分析（→ Neurova 工具体系）

> 对象：Panniantong/Agent-Reach（76.6k★，MIT，Python 3.10+，核心 ~6.9K 行）
> 克隆位置：E:/项目/_reference/agent-reach ｜ 2026-08-30

## 一、它是什么（一句话）

**互联网能力路由器**：把 15 个平台的"接入踩坑经验"（API 选型、多后端路由、失败重试链、登录态处理、数据清洗）固化成一个 CLI（`agent-reach`）+ 一份给 Agent 看的路由文档（SKILL.md）。它的核心资产不是代码，是**选型与重试链的持续维护**（例：2026-06 yt-dlp 被 B 站风控封死 → 切换 bili-cli，用户零操作）。

## 二、平台覆盖与形态

| 分类 | 平台 | 接入方式 | 配置门槛 |
|---|---|---|---|
| web | 任意网页 | Jina Reader（`r.jina.ai/URL`） | 零配置 |
| video | YouTube | yt-dlp 字幕提取+搜索 | 零配置 |
| video | B 站 | bili-cli（多后端路由） | 零配置搜索 |
| search | 全网语义搜索 | Exa via mcporter（MCP） | 自动配置免 Key |
| dev | GitHub | gh CLI（公开读零配置） | 私有需登录 |
| web | RSS/Atom | feedparser | 零配置 |
| social | V2EX | 官方 API | 零配置 |
| social | Twitter/X | twitter-cli / OpenCLI | 登录态 |
| social | Reddit/Facebook/Instagram | OpenCLI（复用 Chrome 会话）/ rdt-cli | 登录态 |
| social | 小红书 | OpenCLI / xiaohongshu-mcp | 登录态 |
| career | LinkedIn | linkedin-mcp / Jina | 登录态 |
| finance | 雪球 | 官方接口 | 轻配置 |
| audio | 小宇宙播客 | Whisper 转录（Groq/OpenAI Key） | 轻配置 |

**形态关键点**：
1. `agent-reach` CLI 本体只做 **install/setup/doctor/format/transcribe**（安装向导、体检、输出清洗）；**实际读取走上游工具**（yt-dlp、gh、curl→Jina、twitter-cli…）——它本质是"路由表 + 体检器 + 格式化器"
2. 自带 **SKILL.md**（Agent 消费的路由文档：先 `doctor --json` 体检 → 按 active_backend 选命令组 → 失败按 references 重试链）
3. 自带 MCP server 但**只暴露 doctor/status**（作者明说：读能力直接调上游）
4. 凭据本地 `~/.agent-reach/config.yaml`（权限 600），Cookie 提取器（cookie_extract.py）
5. 兼容"任何能跑命令行的 Agent"——**接口就是 shell 命令**

## 三、Neurova 现状对接点（已核实）

| Neurova 既有能力 | 位置 | 对接价值 |
|---|---|---|
| `web_search`（Exa 已有实现） | builtin_tools.py:334 + tool_executor._execute_web_search | 全网搜索与 Agent-Reach 的 Exa 路径**重叠**——无需重复接入 |
| `web_fetch`（网页抓取转纯文本） | builtin_tools.py:455 | 与 Jina Reader 路径**重叠**——已有 |
| `computer_shell`（LLM 可跑任意命令，治理预检+沙箱后端刚升级） | computer_use.shell | **agent-reach/上游 CLI 的现成执行通道** |
| MCP 层（mcp_bootstrap/mcp_client/tool_router） | neurova/tool_layers | 可接外部 MCP，但 agent-reach 的 MCP 只暴露 status——价值低 |
| 治理/审计/肌肉记忆闭环 | tool_executor | 一等工具接入后自动获得学习闭环 |
| 肌肉记忆/技能注册表 | skill_registry | 可把 SKILL.md 注册为技能 |

**结论**：Neurova 已覆盖 web_search + web_fetch（网页阅读）；**真正的增量是平台直达能力**——YouTube/B 站字幕、Twitter、RSS、小红书、V2EX、雪球、播客转录、GitHub 深度（Issue/PR）。

## 四、整合方案（三层，按投入排序）

### 方案 A：零代码接入（半天内生效）

venv 安装 `agent-reach`（pip，MIT）→ 在 `builtin_tools.py` 的 `computer_shell` 工具描述里注入**命令路由表**（从 SKILL.md 提炼：`agent-reach doctor --json` 体检 + 各平台零配置命令）。

- LLM 经由已有 shell 工具自由调用，治理预检自动生效
- 零配置六路（网页/YouTube/RSS/V2EX/GitHub 公开/B 站搜索）立即可用
- 代价：依赖 LLM 自觉按路由表走；失败重试链靠提示词约束

### 方案 B：一等内置工具（推荐，1-2 天）

封装 5 个高频内置工具（内部 subprocess 调 `agent-reach format` + 上游命令，输出统一清洗）：

```
youtube_transcript(url)      # yt-dlp 字幕 → 纯文本
bilibili_search(query)       # bili-cli（B 站风控坑已被 agent-reach 踩平）
rss_read(url)                # feedparser
v2ex_hot()                   # 官方 API
social_search(platform, q)   # twitter/小红书等（按 doctor 的 active_backend 路由，未配置返回明确引导）
```

- 进 builtin_tools schema → 自动获得**治理预检、审计、肌肉记忆学习闭环、web_search/web_fetch 同级的工具描述**
- doctor 体检作为工具的运行时自检（未配置平台返回配置引导而非报错）
- 上游 CLI 缺失时优雅降级（对齐 CI 的 OPTIONAL-SKIP 惯例）

### 方案 C：技能注册（补充）

把 Agent-Reach 的 SKILL.md + references/ 注册进 `skill_registry`（`create_from_skill` 已有）——复杂调研场景（多平台组合）给 LLM 提供路由知识。与 B 互补，非必需。

### 不推荐

- 走 agent-reach 的 MCP server（只暴露 status，读能力本来就要调上游）
- 代码级 fork 进 neurova/（它的价值在"持续维护的路由经验"，fork 即断粮——应作为**外部依赖**跟随上游更新，`agent-reach check-update` 内建了版本提醒）

## 五、风险与注意

1. **登录态平台**（Twitter/小红书/Reddit 等）：需要用户配置 Cookie/OpenCLI——渐进式暴露，未配置时工具返回"该平台需配置"引导（不自动登录，遵守其不碰用户浏览器的安全边界）
2. **Windows 兼容**：零配置六路（yt-dlp/Jina/feedparser/gh）均跨平台 ✓；OpenCLI 桌面路径标注仅桌面端
3. **治理**：social_search 等内置工具不含 command 参数，不触发沙箱判定；外呼域名走网络出口，如需管控可在防火墙层加白名单
4. **播客转录**需要 Groq/OpenAI Key（转录走付费 API）——列为"配置后解锁"
5. **依赖体积**：agent-reach 核心依赖少（requests/feedparser/yt-dlp 调用），但 yt-dlp 等上游 CLI 需单独安装（它有 install --system 向导）

## 六、建议

**做**。增量真实（视频字幕/社交平台/RSS 是 Neurova 完全没有的能力域），且 Agent-Reach 的核心价值（踩坑经验的路由维护）恰好是 Neurova 自己维护不起的——以外部依赖方式吸收，跟随上游换代。

**节奏**：方案 A 先行（半天内让 LLM 能用起来）→ 观察实际调用命中 → 命中高的平台按方案 B 提升为一等工具 → 播客转录等重依赖平台最后。全程按既定纪律先红后绿。
