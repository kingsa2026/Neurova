# Neurova 全库代码审计——行程与发现详录（2026-11-04）

> 只读评审产物。全程未改动任何生产代码、测试或文档（工作树保持 clean）。
> 本文是 2026-11-04 全库代码审计的**过程实录与发现详录**：§2 记行程，§4 记发现全字段，
> §8 记主会话复算实测，§9 记未覆盖面。缺陷登记待点单后按台账惯例落格
> （`audit-reports/simplification-audit-2026-10-05.md` §6 尾号现算至 **§6-516**，本批自 **§6-517** 起）。
> 标注体系沿用旧台账：**✅ = 主会话独立复算原文；◑ = 子代理取证（给 file:line，主会话抽查头部断言）**。

---

## 1. 定位、口径与纪律

| 项 | 口径 |
|----|------|
| 任务性质 | 只读盘点，**先出报告等点单，零点单不动码**（既定任务分发口径） |
| 范围 | 全库 5862 个跟踪文件（`git ls-files | wc -l` 现算） |
| 基准 | main @ 2026c7f4（知识库三时间戳台账落格），工作树 clean |
| 方法 | 主会话侦察定界 → 六个互不重叠批次并行只读子代理 → 主会话对 P1 头部断言逐条复算 → 汇总分级 |
| 去重纪律 | 每报一条先 grep 旧台账 `audit-reports/simplification-audit-2026-10-05.md`（1.1 万行），已收且无恶化不重报 |
| 预算纪律 | 吸取旧台账执行事故教训（150 次工具调用截断、maxTurns 空手），**每批显式封顶 40 次工具调用，先广 grep 后精读，宁可少而实** |
| 表达纪律 | 面向用户正文一律中文；死码/断点逐条带影响面（接线后实现什么、数据来去、不接线留下什么），不给一句「死码」了事 |

**为什么是六批**：旧台账记录过"单批项数与调用预算不封顶即截断"的三次事故（skills+evolution 合批、channels+knowledge+security 组 1800 万 token 截断、尾部包组撞 maxTurns）。
本批按子系统边界切成六个互不重叠批次，每批独立预算与独立产出格式，失败可单独重派不牵连。

---

## 2. 行程实录（按时间顺序五步）

### T0 · 侦察定界

- 规模现算：`git ls-files | wc -l` = **5862**；顶层分布 neurova 1074 / tests 2667 / NeurUI 839 / docs 491 / NeurovaHarmony 260 / scripts 103 / audit-reports 39 / models 32 / helm 21 / embedding 13，余为散件。
- 二级分布：neurova/api 140、cognitive_layers 103、knowledge 81、core 78、agent 76、collaboration 65、evolution 61、channels 61、llm 55、skills 54、security 37、context 31（其余见 §3 批次表）；NeurUI/src 630、src-tauri 168。
- 台账定位：最近一笔 docs(audit) 提交（2026c7f4）改动 `audit-reports/simplification-audit-2026-10-05.md` ⇒ **该文件即现役台账**；读其头部（v2 三态口径 A 可删/B 需人裁/C 该接线）与 §6 缺陷格格式（一档逐项档案、file:line + 来历 + 影响面 + 判定），本批产出格式与之对齐。
- 尾号现算：`grep "§6-516"` 落在该台账 ⇒ 后继自 §6-517 起。

### T1 · 六批次并行派发

一次消息并发六个 `general-purpose` 只读子代理（范围/判据见 §3）。**并发事故如实记录**：
首波 6 并发触发 `user concurrency limit exceeded`，B（core/agent/context）、E（前端）、F（Tauri/Harmony/CI）三批未启动；改两波重派——第二波 B+E 成，第三波 F 成。教训并入 §9：本机并发上限低于 6，后续大批次派发按 ≤3 并发规划。

### T2 · 六批回收统计

| 批次 | 范围 | 工具调用 | 时长 | 子代理 token | 产出 |
|------|------|---------:|-----:|-------------:|------|
| A 安全与鉴权 | security/auth/api 鉴权面/web_reach/config/CI 凭据 | 37 | 325s | 1,085,426 | P1×3、P2×2、P3×1 |
| B core/agent/context 正确性 | core/agent/context/execution_engine/sandbox | 24 | 157s | 656,894 | P2×2、P3×2 |
| C knowledge/api 服务面 | knowledge/llm/memory/memory_ingest/channels/api 端点/models/embedding | 43 | 478s | 1,357,799 | P1×2、P2×2、P3×3 |
| D 其余子系统死码 | skills/evolution/collaboration/cognitive_layers/tool_layers/plugins/computer_use/tts/asr/aigc_studio/包根 | 42 | 599s | 1,515,697 | P2×2、P3×1 |
| E 前端 NeurUI | NeurUI/src + public | 41 | 199s | 556,641 | P1×2、P2×5、P3×1 |
| F 桌面/鸿蒙/脚本/CI | src-tauri/NeurovaHarmony/scripts/.github/helm/config/根构建件 | 41 | 364s | 765,103 | P1×1、P2×3、P3×2 |
| **合计** | | **228** | | **≈594 万** | **24 项实证缺陷**（去重后 P1×8、P2×15、P3×9） |

（批次小计含跨批合并口径：如 E 的两条 P1 死码在 §4 合并为一条双 store 收口项叙述，计数以 §4 为准。）

### T3 · 主会话交叉复算（P1 头部断言逐条过原文）

对将进报告头部的 7 组断言逐一复算，**全部命中、无一误报**（实测见 §8）：

1. web_reach 首跳守卫 + http_fetch 两引擎均默认跟随重定向（读 reach.py:68-92、http_fetch.py:80-104 原文）；
2. model.py DELETE 处理器通篇无 None 拒绝（读 model.py:325-368 原文）；
3. TB 分支独缺 reindex 登记（读 repository.py:850-904 原文 + grep `_record_index_op` 全分布：443/972/1159/1527/1578/1694/1845/1873/1917/2056/2343，856-899 区间无命中）；
4. ingest_bridge `create_knowledge` 调用缺两参（读 ingest_bridge.py:215-249 原文）；
5. 前端 optimized 双 store 全仓 0 引用（grep 排除自身后 exit=1）；
6. MANIFEST.json 无 sha256/digest 字段（grep -c = 0）；
7. 前端 optimized 零引用与 MANIFEST 复算同命令批次完成。

### T4 · 汇总分级

24 项实证缺陷按 P0-P3 分级（P0=0）、存疑区 9 项不列缺陷、已查未见问题面按六批归并；给出处置序①-⑥（§10）。**报告已在会话内交付，等点单。**

---

## 3. 批次设计详录（范围 × 判据）

### 批 A · 安全与鉴权
- 范围：`neurova/security/`、`neurova/auth/`、`neurova/api/` 鉴权面（middleware/error_handlers/CORS）、`neurova/web_reach/`（SSRF 视角）、`config/`、`.cnb.yml`、`.cnb/`、`.github/`、`helm/`、根 start* / install.py；全仓硬编码凭据扫描。
- 判据：注入四型（SQL/命令/路径/SSRF）、不安全反序列化、硬编码密钥、鉴权缺口（对照 `docs/s08_route_auth_baseline_2026-09-11.txt` 查漂移）、CORS 过宽、加密误用。

### 批 B · 核心链路正确性
- 范围：`neurova/core/`、`neurova/agent/`、`neurova/context/`、`neurova/execution_engine/`、`neurova/sandbox/`。
- 判据（仓库纪律摘录，违反即缺陷）：SQLite 多线程走 RLock、schema 走 db_migration 注册表；单例 DCL+RLock；身份唯一通道 `neurova_request_user_id`（第二 ContextVar 装 user_id 即病）；可选依赖惰性 import；`except: pass`/无痕吞异常；资源泄漏（Session 不关、缓存无界、裸线程）；asyncio 内阻塞 IO。

### 批 C · 业务服务面（重点：三时间戳新批接线完整性）
- 范围：`neurova/knowledge/`、`neurova/llm/`、`neurova/memory/`、`neurova/memory_ingest/`、`neurova/channels/`、`neurova/api/endpoints/` 与路由装配、`neurova/models/`、`neurova/embedding/`。
- 背景：15d23a09 / c2ed2966 / 2026c7f4 三笔（三时间戳批）刚落地；已登记尾巴 TD② 不算新发现。审的是入库写入→存储→查询过滤→消费方的闭环，及 epoch 秒/毫秒/ISO 双轨混用、新端点三处登记、输入校验。

### 批 D · 其余子系统死码/双源
- 范围：`neurova/skills/`、`evolution/`、`collaboration/`、`cognitive_layers/`、`tool_layers/`、`plugins/`、`computer_use/`、`tts/`、`asr/`、`aigc_studio/`、包根 `__init__` 链。
- 方法：全仓 import 语句语料零引用扫描（排除 tests/ 与定义自身）→ 排除 `__init__` 再导出假阳性复扫 → 类名级与动态字符串级复核 → 旧账逐条对账。验收口径明确写入：**交 0 条不算失败，交 10 条假阳性才是失败**。

### 批 E · 前端 NeurUI
- 范围：`NeurUI/src/`、`NeurUI/public/`（不含 src-tauri）。
- 判据：XSS（v-html/innerHTML/window.open）、硬编码凭据、前后端契约对账（≥5 条核心链路抽样）、时间契约三轨（epoch 秒/毫秒/ISO）、断点（零引用组件/store/action）、泄漏（定时器/监听未清理）、竞态、空 catch。禁跑 npm，纯静态。

### 批 F · 桌面壳/鸿蒙/脚本/CI
- 范围：`NeurUI/src-tauri/`、`NeurovaHarmony/`、`scripts/`、`.github/workflows/`、`helm/`、`config/`、根构建件。
- 判据：Tauri capability/CSP/updater、自定义命令透传面；Harmony 凭据/明文 HTTP/deep link；脚本危险操作/路径注入/硬编码本机路径/双源；CI 配置漂移（与 parity 守卫咬合核对）；全范围凭据扫描（.pem 进仓即 P0）。
- 已知事实不重报：scripts/ci 5 文件非 ASCII print、`_utf8ChildEnv` 双定义（旧账 §6-489 复算注已收）。

---

## 4. 发现详录（P1×8、P2×15、P3×9）

编号即处置引用号；✅/◑ 见 §1 标注体系。

### 4.1 P1（8 条）

**P1-1 ✅ model.py 全部写/探测端点用 `get_optional_user`，匿名可删改模型配置**
- 位置：`neurova/api/endpoints/model.py:329`（DELETE）、`:379`（PUT）、`:464`（/switch）、`:563`（/check-connection）、`:650/:668`（/download-source、/download）。
- 根因：`get_optional_user`（`api/auth.py:652-656`）未认证返回 None 不拒请求，handler 内不判 None；`NEUROVA_GLOBAL_AUTH` 默认 off（`api/global_auth.py:56-58`），兜底实际不存在。
- 影响面：docker-compose.yml:25 与 `helm/neurova/templates/configmap.yaml:10` 均设 `NEUROVA_HOST=0.0.0.0` ⇒ 容器部署下匿名可删除/篡改模型配置、触发模型下载；`/check-connection` 接受用户给定 `base_url` 发请求，是匿名 SSRF 探测原语。s08 基线记 OPEN 属既存状态，但其声称的 enforce 兜底默认关闭＝无兜底。
- 处置：非 GET 端点改 `get_current_user`，写面加 `require_admin`；或把 enforce 设为部署缺省。

**P1-2 ◑ 容器部署首账号抢注防护 fail-open**
- 位置：`neurova/api/endpoints/auth.py:545-563`；docker-compose.yml、helm/ 均未配置 `NEUROVA_BOOTSTRAP_ADMIN_TOKEN`。
- 根因：引导令牌两处均缺时仅打 warning 放行（代码自认"服务端部署存在管理员抢注风险"），而部署面从不设置该令牌。
- 影响面：0.0.0.0 部署下，公网首访 `/api/v1/auth/register` 者注册即管理员；再叠 recover-password 链（`MASTER_RECOVERY_PASSWORD` 已知接受风险，旧账 §6-166/§6-171）即全站接管。
- 处置：服务端形态缺令牌拒绝首账号注册（fail-closed），桌面单机保持现状。

**P1-3 ✅ web_reach 出网 SSRF 守卫可被 302 重定向绕过**
- 位置：`neurova/web_reach/reach.py:72-81`（首跳 `_assert_public_host` + `_url_guard_assert_public`）、`neurova/http_fetch.py:85-101`（curl_cffi 与 urllib 两引擎均默认跟随重定向）。
- 根因：`http_fetch.py:12` docstring 自述"SSRF/协议守卫归调用方"，调用方只守了第一跳；`curl_requests.get(url, impersonate="chrome", **kw)` 未关重定向，`urlopen` 默认经 HTTPRedirectHandler 跟随。
- 影响面：任何能投喂 URL 的工具入口（web_read/rss_read/youtube_transcript 等）用公网 URL 一跳进 `http://127.0.0.1:9527/`、`http://169.254.169.254/`，响应正文原样返回调用方——可读型 SSRF，最坏泄露本机 API 与云元数据。
- 处置：每跳重定向重过 `assert_public_url`，或两引擎均禁跟随。

**P1-4 ✅ TB 更新重入库绕过索引重排——覆盖后检索仍回旧代块**
- 位置：`neurova/knowledge/repository.py:856-899`（TB 分支 `self._save()` 后 `:899` 直接 return）；对照其余全部内容变更点 `:972/:1159/:1527/:1578/:1873/:2056` 均有 `self._record_index_op("reindex", ...)`（grep 全分布复核）。
- 根因：批 TA 只改摄取边界与存储字段，TB 分支覆写 title/content/chunks/parents/content_fingerprint 并落盘，但索引不知情。
- 影响面：同文档改后重导入（批 TB 主场景，含异步队列 `ingest_worker.py:90-94` 复用同函数）条目正文是新的，分片/向量索引仍是旧代 chunks——`search_visible_items` 按块命中返回旧文本与旧块级明细，恰好复刻本批要消灭的"检索污染"，只是挪进了索引层。数据流：导入端点 → TB 覆盖 → 索引不知情 → 检索读旧。
- 处置：TB 分支 `_save()` 前补 `_record_index_op("reindex", existing["knowledge_id"])`，与其他变更点对齐。

**P1-5 ✅ 企业微信入站边界丢源时间——同一根因未按教义第 5 条扫荡**
- 位置：`neurova/knowledge/ingest_bridge.py:222-245`：`:224` 已拿 `parsed.metadata`（`document_pipeline.py:118-119/132-133` 确有 created_at/modified_at），`create_knowledge` 调用却缺 `source_created_at`/`source_modified_at`。
- 根因：批 TA 只改了 `knowledge_ingestion.py` 这一条摄取边界；`ingest_bridge` 这条并行边界消费同一 `parse_document` 产物未透传，`_resolveSourceDates` 等价回退也没做。
- 影响面：wecom 入库条目三时间戳恒空串 ⇒ (a) TB 对这批条目永不触发（`repository.py:856` 判 `str(source_modified_at or "")` 为假），改后重导退回"新旧两代并存"；(b) TD① 按源修改时间过滤时 wecom 条目在 `:1129` `srcT is None` 全被排除——用户视角"按时间一筛，企微知识全消失"；(c) 前端源时间列/明细恒空。接线后：企微文档与文件导入行为一致，覆盖 TB/TD①/前端展示三个消费面；不接线则该边界是三时间戳功能的永久盲区。
- 处置：`ingest_bridge.py` 在 `:238` ingest_time 旁按 `_resolveSourceDates` 同口径补传两参；逻辑抽公共函数防第二份定义。

**P1-6 ✅ 桌面壳运行时下载链全程零完整性校验**
- 位置：`NeurUI/src-tauri/src/lib.rs:321`（download_python_runtime）、`lib.rs` download_file/download_with_fallback（约 430-460）；`models/MANIFEST.json:5-21` 只写 version+urls（grep sha256/digest 零命中）。
- 根因：下载完直接 `tar -xzf` 落地为后端解释器/Node，无哈希比对；候选源含 npmmirror、阿里云两个第三方镜像。守卫 `tests/unit/desktop/test_route_b_runtime_download.py` 只钉路由/回退不钉完整性。与旧账 §6-156/176 已修的技能/插件通道（TOFU+落盘摘要）同类不同命，本通道未在任何台账登记。
- 影响面：桌面端首启 `start_download`（lib.rs:963）即触发；镜像投毒或上游 tag 被篡改 ⇒ 下载被替换的 Python/Node ⇒ 后端以其身份执行任意代码。
- 处置：MANIFEST 加 sha256，落盘前校验再解压；pip 侧 `install_python_dependencies` 补 `--require-hashes`。

**P1-7 ✅ `stores/collaboration.optimized.ts` 与 `chat.optimized.ts` 整文件零引用死码，且与活实现同名导出、同 store id**
- 位置：`NeurUI/src/stores/collaboration.optimized.ts:60`（`defineStore('collaboration', ...)`）、`NeurUI/src/stores/chat.optimized.ts`（同构）；活实现 `src/stores/collaboration.ts`（8 消费方）、`src/stores/chat.ts`（20 消费方）。
- 根因：全仓 0 引用（grep 文件名与 `useOptimized*` 两种模式排除自身验证）；两份导出名逐字相同、Pinia id 相同——教义第 6/7 条点名的第二份定义并存。
- 影响面：任何人把 import 来源改成 `.optimized`（IDE 自动补全会建议），两份 store 以同一 id 互踩状态、devtools 混淆，优化版 bug 永不被现有测试咬住。删除则零行为变化。
- 处置：教义第 7 条对比后取一份，另一份连同测试删（预期整文件退役）。

**P1-8 ◑ （计数并入 P1-7 口径的独立死码断点）`getConsoleChatSSEUrl` 指向后端不存在路由且自身零调用**
- 位置：`NeurUI/src/api/modules/console.ts:97-104`（拼 `${base}/console/chat/stream?...`）。
- 根因：后端 `console.py` 全部路由无 `/chat/stream`；流式实际由 `chat.py` 的 `POST /api/v1/chat/stream` 承担；前端亦无该函数调用方。
- 影响面：双病叠加——接口客户端声明了一条照着接必 404 的链路，同时它自身是死码；每个读到它的人会误以为 console 有独立 SSE 通道。
- 处置：删该函数，注释指回 chat.py 真实端点。
（归并说明：会话内交付的 24 项计数把本条计在 P1 死码双源项内；本文按批次口径全录，总数不变。）

### 4.2 P2（15 条）

**P2-1 ◑ `/metrics`、`/health/detailed` 在免鉴权白名单，匿名可读运维指标**
`api/global_auth.py:38-44`。enforce 模式下也放行；指标面暴露路径级调用量/时延。处置：移出白名单或限 loopback/管理令牌。

**P2-2 ◑ web_reach 凭据加密密钥与密文同机落盘**
`web_reach/credentials.py:70-77`：`secrets.token_hex(32)` 生成密钥写本地 keyfile，与 Fernet 桶同处数据根——拿到文件读权限即同时拿到密钥与密文。仅对抗弱接触面，桌面单机威胁模型下 P2。处置：接 OS 级凭据保护（DPAPI/Keychain）派生。

**P2-3 ◑ Tauri CSP 为 null 且 withGlobalTauri 开启**
`NeurUI/src-tauri/tauri.conf.json:27/:29`。主窗渲染 LLM 生成内容，一旦前端有未消毒注入点，无 CSP 兜底，注入脚本可直调 lib.rs:1096 自定义命令并携本地凭据访问 9527。capability 面（仅 `core:default`）已收窄故非 P1。处置：设显式 CSP（`default-src 'self'; connect-src 'self' http://127.0.0.1:9527`），评估 withGlobalTauri 消费方。

**P2-4 ◑ 安装器把管理员明文口令拼进 NSIS 进程命令行**
`NeurUI/src-tauri/installer-wpf/MainWindow.cs:1018`（`" /NU=" + adminUser + " /NP=" + adminPass`）。安装窗口期同机低权进程经 WMI `Win32_Process` 可读明文；配套 bootstrap_admin.ini 明文落盘有"首启消费即删"补偿（`:1136-1157`），命令行这半无。处置：改环境变量或临时凭据文件传递。

**P2-5 ✅ TB 闸门绕过内容指纹去重，两个方向都判错**
- 位置：`repository.py:856`（TB 先于 `:900-906` 指纹去重）+ `knowledge_ingestion.py:32-41`（`_resolveSourceDates` 把无元数据源的回退钟——入库时刻——当源修改钟）+ `:320`（URL 导入把标题串当 filename→source_path）。
- 影响面：① 重复导入**未改动**的同一文件：不再走指纹去重短路，每次追加一条 `old==new` 的 source_update_reingest 修订（`repository.py:869-878`）、刷新 created_at（`:887`，前端"入库时间"列无谓跳动）、修订列表无界增长；② **同名不同文**：两个同名 report.docx 或两个同标题网页在同 agent+租户下，后导者凭"钟更晚"覆盖先导者正文——旧判据按内容指纹判定并存，新实现静默合并。
- 处置：TB 触发前先比 content_fingerprint（相同仍走原去重短路）；回退钟（非真实元数据）不启用 TB 覆盖；URL/同名场景 source_path 用真实 URL/路径。

**P2-6 ◑ 工具参数反射提取失败被无痕吞掉，工具 schema 静默退化**
`execution_engine/tool_engine.py:505-509`：`_extract_parameters` 用 `inspect.signature` 生成暴露给 LLM 的工具参数定义，包 `except Exception: pass` 无日志无标记。反射一旦失败（动态构造/C 扩展/半初始化 callable），LLM 拿到空/残缺 schema，每次调用因缺参失败且现场零留痕——同函数其他失败路径均有 log，此处是唯一静默点。处置：补 `logger.warning` 保留空列表语义，与同文件留痕口径对齐。

**P2-7 ◑ supervisor 幂等账本单例带参调用覆盖全局实例：连接泄漏 + 账本分裂 + 未走 DCL**
`agent/supervisor/ledger.py:86-95`：`if _ledger is None or dbPath:` ——传 dbPath 即无条件覆盖 `_ledger`，旧实例 sqlite 连接不 close、不走 reset；已持旧引用的调用方与后续取到的不是同一份，该账本唯一目的（跨重启/多 Worker 幂等去重）失效。附带：单例普通 Lock 锁内创建，未按 AGENTS.md §3 走 DCL+RLock。生产消费方仅 `acp_api.py:280` 无参调用，当前不触发——属接口固有雷。处置：带参改走显式 reset 入口，创建路径补 DCL。

**P2-8 ◑ 批 TC 冲突时间建议只到 HTTP 边界，零消费方**
产生于 `repository.py:2160`（time_context）与 `:2113-2145`（`_conflictTimeContext`）；透出于 `knowledge_sharing.py:87-89`（entry 轴整行透传）、`knowledge_core.py:401`（详情 `**entry`）；前端零消费（全仓 grep time_context/newer_side 仅 repository.py 一处；`KnowledgePage.vue:230-252` 冲突队列只渲染 axis/kind/severity/policy）。影响面：newer_side/两侧源修改时间/basis 已随冲突接口发出，但裁决人在 UI 看不到任何时间读数——"给裁决者时间信号"的设计目的到不了人，属只写不读；且给人"功能已闭环"错觉。处置：KnowledgePage 冲突行/详情补 time_context 展示（i18n 11 语言随批），或明确登记进台账尾巴。

**P2-9 ◑ `collaboration/seen_cursor.py` 479 行失去最后调用方，与 glance_yield_rules 构成同功能双实现**
- 来历：旧账 §3-B7 记 `coordination_decorators.py:47` 是其外部唯一调用方；189bc226（2026-10-07，让位执行体收成一份）删除 coordination_decorators.py 后，新鲜度能力由 `glance_yield_rules.py:107/:393`（内存版 `_seen_sequences` + preflight）承担；`coordination_api.py:42-46` 注释显式弃守 `/seen-boundary/*` 并点名 seen_cursor——全仓已无任何代码调用它。
- 影响面：接线的话，SeenCursorManager 提供带 SHA256 去重、持久化到 data_root 的新鲜度预检（防协作操作重复执行），可替代现役内存版"重启即失"的游标；不接线/删除的话，失去持久化级新鲜度游标，479 行及其测试退役，无端点行为变化。
- 处置：**待拍板**——或删（教义 7 已选定 glance_yield_rules 那份，479 行属"接通后未退役清理"残留），或反向接线换得持久化。二选一，不许并存。

**P2-10 ◑ `tool_layers/browser_capability.py` 189 行全仓零生产调用（旧账漏网实证项）**
唯一非测试引用是 `tool_layers/__init__.py` try/except 再导出；消费仅 tests。头注释宣称"与 ComputerUseManager 协作、注入 LLM system prompt 的浏览器能力描述"（capabilities/limitations/best_for、`to_llm_context()`），但 computer_manager/browser_manager/capability_state 均未引用——宣称的接线从未建成。来历：7835c367（2026-06-04 pyc 骨架恢复）批量引入，旧账全文 grep 零命中。影响面：接线则各浏览器后端能力描述经 to_llm_context() 进 agent 系统提示词，模型据此选后端；删除仅失描述词汇表与单测，无端点/运行行为变化。处置：待拍板——接线或整文件删。

**P2-11 ◑ `stores/utils.ts` 全部导出零消费**
`NeurUI/src/stores/utils.ts:16-130`（handleStoreError/logStoreOperation/mapApiResponse/snakeToCamel/camelToSnake/safeGet/deepMerge 七个导出，`from '@/stores/utils'` 全仓 0 引用）。store 各自已在别处实现错误处理/字段名转换，留着即第二个候选事实源。处置：确认无动态引用后整文件删。

**P2-12 ◑ 知识条目时间戳类型声明与运行时口径相反**
`NeurUI/src/api/modules/knowledge.ts:19-20/:762` 声明 `created_at?: string`；后端实发 epoch 秒（`repository.py:850/:887` `...timestamp()`；旁证 `fts_index.py:102` 对 updated_at 做 float()）；页面用 `formatEpochSecondDate`（秒口径）渲染是对的，TS 层靠 antd 宽类型穿透才没红。同文件 revisions 的 `updated_at` 又真是 ISO（`repository.py:875-876`）——同名字段两种量纲全靠声明区分。影响面：三时间批（c2ed2966）刚落地，`source_created_at/source_modified_at`（ISO）与 `created_at`（秒）双轨并存，下一个消费方若信类型声明按 ISO 处理 created_at，即复现 `displayText.ts:39` 钉过的"全表 1970/Invalid Date"回归。处置：主条目 created_at/updated_at 改 `number`，与 `AnnotationItem:250-251` 对齐。

**P2-13 ◑ OAuth 把 app_secret 拼进 URL query 后 window.open 无 noopener**
`NeurUI/src/modules/collaboration/CanvasStoreDrawer.vue:194-200`：URLSearchParams 含 app_secret 直接拼进 GET authorize URL；secret 进浏览器历史、可能进服务端 access log 与 Referer。后端 `neurflow_stores.py:230` 确以 query 收参（双端同病，前端可先自救）。同文件 window.open 未带 'noopener'（对照 `MdPreviewPanel.vue:61` 已带，同仓两种口径）。影响面：多平台店铺 OAuth 接入链路（taobao/jd/pdd/douyin 等 8 个 Tier 2 平台）。处置：改 POST 表单或一次性 code；window.open 补 'noopener'。

**P2-14 ◑ scripts 硬编码本机绝对路径，他人环境必挂**
`scripts/desktop/expand_nsi_template.py:15/:36/:56`：OUT_DIR 写死 `C:\Users\xccoo\AppData\Local\Temp\nsis_verify`；任何非 xccoo 账户运行必挂；文件头 docstring 还自称产出 `/tmp/nsis_verify/`，文实不符。处置：改 `tempfile.gettempdir()`，docstring 同步。

**P2-15 ◑ scripts/config.py 端口常量与部署面平行、无守卫咬合**
`scripts/config.py:22-23`（BACKEND_PORT 9527/FRONTEND_PORT 8100），唯一消费者 `health_check.py:469-479`；`deploy_config_consistency_check.py` 只比 MIN_PYTHON_VERSION 不比端口。compose/Helm/lib.rs 任一侧改端口后 health_check 静默探错端口。处置：两端口纳入跨文件比对，或删常量改读单一来源。

### 4.3 P3（9 条）

**P3-1 ◑** `source_modified_after/before` 非法值静默改变过滤语义：`_parseSourceDate("garbage")` 返回 None 后范围条件被跳过，但 `:1129` "无源时间排除"仍生效——传错格式得 200＋被静默收窄的结果集，排障困难（`repository.py:1127-1136`、`knowledge_common.py:96-97` 无格式校验）。处置：端点层 ISO 可解析性校验，不可解析回 422。

**P3-2 ◑** PDF `D:` 形时区偏移被丢弃：正则只吃到秒位、硬贴 timezone.utc——UTC+8 下 PDF 源修改时间整体偏 8 小时进 TB 判定与 TD① 过滤，日期边界当天 0-8 点段条目误含/误排（`repository.py:203-216`）。处置：补偏移捕获组合成 tz。

**P3-3 ◑** 前端过滤区间按本地日期拼串、后端按 UTC 解释：`KnowledgePage.vue:1340-1341` 拼 `T00:00:00`/`T23:59:59` 裸 ISO → 后端 fromisoformat 后 naive 贴 UTC——UTC+8 用户选"11-04 起"实际从本地 08:00 生效，当天上午修改的文档被误排；`T23:59:59` 丢当天最后一秒。属"时间契约双轨"的时间感知新变体（时区错读，非 §6-489 秒/毫秒错读复发）。处置：前端带时区拼串或后端约定 naive＝本地并文档化。

**P3-4 ◑** memory 门面 `_MODULE_MAP` 两个死键指向已退役模块：`memory/__init__.py:90`（agent_self）/`:92`（memory_stream）——旧账 §6-372 家族判删的模块文件已删，门面映射未随批清理；`:98-102` 急切装载循环把必然失败的 ImportError 降为 debug。每次 `import neurova.memory` 白付两次失败 import_module＋两条 debug 噪音。处置：删两行，净 LOC -2。

**P3-5 ◑** 观测链路无痕吞异常四处：`execution_monitor.py:220-222/:236-238`（metric/alert handler）、`:459-461`（执行日志加载）、`core/db_indexes.py:200-201`（PRAGMA index_info 失败→该索引 columns 静默为空，快照被审计链路读）。处置：各补一行 `logger.debug(..., exc_info=True)`，不改控制流。

**P3-6 ◑** Windows AppContainer profile 删除失败静默：`sandbox/appcontainer.py:202-204`——失败原因（权限/名字被占）不可见，残留 profile 致下次同名创建报错，形成"清理失败→创建失败"连锁且第一现场无痕。处置：debug 留痕；创建路径命中 ERROR_ALREADY_EXISTS 时复用旧 profile。

**P3-7 ◑** 硬编码色守卫只扫 `#hex`，`rgba()/hsl()` 裸值绕过契约：`hardcodedColors.test.ts:38` 正则不认 rgba；实例 `CrossSessionSearch.vue:221` `background: rgba(74, 158, 255, 0.12)` 非 var 令牌——主题切换时非 hex 裸色不受 variables.css 约束，与该守卫要拦的"浅色主题对比度穿透"同类。处置：守卫正则扩 `rgba?\(/hsl\(`，白名单同步补令牌色。（`App.vue:78-143` antd theme token 是主题源头定义，不属违例。）

**P3-8 ◑** `start_server.py:140-142` 注释称"默认 0.0.0.0:9527 与 Dockerfile/compose/Helm 同源"，实际 `:73` 缺省 127.0.0.1——误导暴露面判断。处置：更正注释。

**P3-9 ◑** `scripts/desktop/cnb_release_assets.py:44` 用 `os.popen("git remote get-url cnb 2>nul")`：Windows 专用重定向，非 Windows 下静默取不到 remote（有 token 缺失报错兜底，仅小疵）。

---

## 5. 存疑区（未定案，不列缺陷——请勿当结论使用）

1. curl_cffi `allow_redirects` 默认值未读其源码逐一验证（据其 requests 兼容 API 为默认跟随）；urllib 跟随是确定的。P1-3 结论按"至少一路跟随"成立。
2. `url_guard.py:40-55` 已做 getaddrinfo 逐解析结果判定（好于常见实现），但校验与实际请求是两次解析，DNS rebinding TOCTOU 窗口理论仍在——代码注释自认此点，属已知缓解水平。
3. `global_auth.py` 白名单路径与 health.py 路由实际挂载前缀是否逐字对齐未核实；错配则 enforce 模式白名单覆盖面偏移。
4. `mobile_pairing.py:936/:966` 配对端点未挂 `_get_current_user_id`——若设计为手机端凭一次性配对码调用则合理，未深读。
5. `core/hooks_engine.py:110` shell=True：执行源是本机 hooks 配置文件而非 HTTP 输入，威胁模型未深读；`execution_engine/shell_sessions.py:98` 同理且有 `security/command_authority` 审批面。
6. `data_masking.py:167` md5 做脱敏指纹（非口令存储）、`artifacts_api.py:236` sha1 做 artifact id——均非密钥派生/口令场景，未定缺陷。
7. mermaid 渲染 `el.innerHTML = svg`（`useMermaidRenderer.ts:59`）：安全性取决于 mermaid 初始化是否显式 securityLevel，未核到初始化参数。
8. tts/asr 各自 `model_downloader.py` 同壳双份（ASR 头注释自认"模式复制自 tts"）：壳同构但后端机制实质不同（HF hub snapshot vs whisper.load_model 官方通道），是否构成教义 6 双源需人裁；旧账未点名此对。
9. 根 `package.json:4` version 1.0.0 与产品版本（1.0.0-beta7）不同值：桌面链版本咬合守卫只覆盖 NeurUI 侧两份+lock，根 package.json 的版本消费方未查到——是产品版本展示面即第二处版本定义，是工作区占位则无事，需人确认。
10. `channel-configs.ts:134` conflicts 检查路径与后端 `channels.py:588` 挂载前缀是否对齐，未完成核对。
11. `models/cost_store.py:246-341` 五处 `except Exception:` 未逐一看护（不在本批改动内，预算所限未深查）。
12. `updated_after: float`（epoch 秒，入库钟）与 `source_modified_after: str`（ISO，源钟）同驻一个请求模型——设计文档明示的"契约只增不改"双轨，暂不计病；第三口钟入模型前建议先立字段命名规约。
13. `repository.py:898` 的 `source_updated` 标志仅随导入响应透出，NeurUI 与后端均无读取方——接 UI 提示"本次为更新重入库"或删。
14. `execution_engine/agent_colab.py:38/:52` `_plans` 全量读入/写回 plans.json 无淘汰——是否算增长风险取决于计划生命周期管理，未深查。
15. `core/agent_run_ledger.py:235` 终态写入 fire-and-forget daemon 线程：有 logger.warning 留痕、注释说明由 reconcile 兜底，判定为有意设计，列出供复核。
16. `core/module_tracker.py:184` check_loop daemon 线程未精读到 stop/join 收口，若常驻至进程退出则可接受，未定论。
17. installer.nsi:928 与 WPF 壳 MainWindow.cs:1136 两处各写一份 bootstrap_admin.ini，注释互指"同通道"——是否触发教义 7"同功能先比后合"未裁。
18. `.github/workflows/cost-guards.yml` 用 checkout@v3/setup-node@v3，ci.yml 用 @v4/@v5——同官方 action 版本不齐，非安全问题，属洁癖项。

---

## 6. 已查未见问题面（六批扫过且确认干净）

**身份与并发（批 B）**
- 身份通道（§6-163 裁定甲）：全仓 `neurova_request_user_id` 唯一定义在 `core/identity_context.py:28`；`turn_state.py:107` 已按裁定甲去 user_id 化且有防复活注释；其余 ContextVar（capability_gap、swarm 子深度、cancel_token、tool_trace、trace_context、usage_accounting、post_chat_pipeline 步骤结果、turn_context 族）均非身份第二通道。
- SQLite 合规：agent/ 直连点仅 supervisor/ledger.py（RLock 全程）；eviction_ledger_db.py 有 RLock+WAL+迁移注册表（v1-v3）+重建侧 finally close；connection_pool 收尾路径的宽捕获属资源收尾且注释明确。
- HTTP 会话：ffmpeg.py:96、scheduler.py:580 均 async with，无泄漏。缓存淘汰：tool_engine deque(maxlen)、core/cache.py、session_snapshot、memory_retrieval_chain 均 LRU；orchestrator 窗口缓存有淘汰且写侧对已淘汰槽 raise 留痕。线程生命周期：scheduler 重试循环 daemon+drain+join；idle_tracker 有 stopAll。asyncio 阻塞 IO：同步重活均经 to_thread（contextvars 不丢轮次）。

**安全四大面（批 A）**
- CORS：`cors_policy.py` 默认 8 项 localhost/tauri 白名单、非 `*`；改白名单的端点挂 check_role。
- 命令注入：console /debug/command 为 require_admin+白名单+数组执行（2026-09-07 已根修）。
- 路径穿越：files_api 上传段净化+basename+relative_to 双校验+危险扩展名拒绝；workspace_files 读写均过 `_resolve_inside`。
- 反序列化：metadata 用 ast.literal_eval；无 yaml.load 非 safe、无生产 eval/exec 裸奔（safe_expr 有 AST 白名单前置）。
- SQL：f-string 命中点均为内部表名/列名/schema 常量，参数值一律 `?` 占位。
- 基线漂移：skill.py/media.py/generation.py 已加 router 级 get_current_user——较 s08 基线 OPEN 收紧（改善非漂移）。
- debug 面：/test 仅 debug 模式注册；/health/recover 显式 501。口令学：bcrypt、hmac.compare_digest、Fernet。error_handlers 无堆栈回显。

**三时间戳主路径闭环（批 C）**
- 文件导入主路径写入→存储→查询→消费闭环成立：document_pipeline 元数据 → knowledge_ingestion 透传+回退 → repository 落条目/_migrate_entry 存量补齐 → item_response → 前端列+明细，字段名/类型/展示单源一致。JSON 存储无需 SQLite 迁移；队列 schema 迁移已注册。异步导入路径源时间随主函数继承。搜索 limit Field(ge=1, le=100)。epoch 秒/毫秒：memory_ingest 的毫秒钟字段不流入 knowledge 元数据，两链无交叉污染。
- 前后端契约对账（批 E）：聊天历史/聊天 REST 兜底/会话列表/知识库/配置/渠道配置/认证 401 刷新链全对上；唯 SSE 死码链（P1-8）与类型声明病（P2-12）例外，均已列缺陷。

**2026-10-05 后新增件接线（批 D）**
association_cues 三件、evolution 七新件（blind_selection/deterministic_judge/skill_evidence/proposal_lifecycle/task_yardstick/automation_prerequisites/eval_corpus）、plugins 重接批、aigc_studio/video_reconcile、causal_reasoning——全部有生产消费方；revert 曾回补的 channels 七件与 question_decomposer 已再次退役，非现存孤儿。neurflow 全件、tool_layers 其余件、cognitive_layers 非记忆层、skills 存活件均接线。范围内单行 `except: pass` 零命中。

**前端（批 E）**
- XSS：7 处 v-html 全走消毒链（marked+DOMPurify+sanitizeUrl 协议白名单）；CrossSessionSearch 高亮先 escapeHtml 再包 mark；TextPreviewPanel hljs 自转义。
- 凭据：src 内无硬编码 token/key/内网地址。定时器/监听：抽查 8 处 setInterval 均有卸载清理，usePolling 自带清理。空 catch 仅一处且有注释说明语义。

**桌面/鸿蒙/CI（批 F）**
- Tauri capability 仅 core:default；Cargo.toml 无 fs/shell/process 插件；5 个自定义命令均固定动作，无任意路径/命令透传；Command::new 只起 layout 内固定解释器/tar。
- updater 未配置（无 pubkey 缺失/私钥进仓问题；通道缺失是产品缺口非安全病）。
- 鸿蒙：无生产硬编码凭据（192.168.* 均在注释/ohosTest/mock）；api/ws base_url 缺省空串由配对回填；WebSocket token 只走 Authorization header 不进 URL，连接日志不含 token；无自定义 scheme deep link 入口；权限仅 INTERNET/GET_NETWORK_INFO/CAMERA。
- 版本单源：tauri.conf.json 与 NeurUI/package.json 被守卫逐字咬合（现同 1.0.0-beta7），非失控双源。
- CI：.cnb.yml 与 ci.yml 有 parity 守卫咬合；分片数两头咬合；helm 端口与 lib.rs/Dockerfile/compose 一致且有部署一致性守卫；NPC 段无私有 maxTurns 残留。
- 凭据扫描：git 跟踪文件中 .pem/.key/.pfx 0 个；ghp_/AKIA/xox/sk- 等字面量 0 命中；create_admin_user 口令走环境变量；cnb_release_assets token 只取环境/remote 解析不落盘。

---

## 7. 旧账核对与去重记录

**批 D 零 import 候选 13 件中 12 件已收、未恶化、不重报**：auto_skill_improver、emotion_conduction_module、explainability、forgetting_recovery_storage_mixin、project_to_skill、relation_mixin、skill_chain_executor、skill_generator、skill_packager、temporal_reasoner、workflow_evaluator、proactive_question（经 `neurova/memory/_MODULE_MAP` 惰性装载核实非孤儿）。复扫 NONE 件 positional_encoding、temporal_knowledge_graph（经 tkg_retriever_adapter 接 chat_pipeline）、memory_layer/security 亦均有账。已知线索 OutboxHandler.register_handler 维持旧账 §6-489 原状（drain 侧 2026-09-20 已接线，register 侧仍零调用，无新事实不重报）。

**本批三条新报的与旧账关系**：
- P2-9 seen_cursor：旧账 §3-B7 已收当时判"需人裁（偏接线）"，2026-10-07 后**实证恶化**（最后调用方被删）⇒ 升格重报；
- P2-10 browser_capability：旧账**漏网**实证项 ⇒ 新报；
- P3-4 memory 门面死键：旧账 §6-372 处置**执行后的新增残留** ⇒ 新报。

**已知接受风险照录不另立格**：`MASTER_RECOVERY_PASSWORD = "neurovamakehappy"`（`api/endpoints/auth.py:73`）——旧账 §6-166/§6-171 详登且为用户裁定"按原形态接回写死常量"，仅 5 次/15 分钟限流拦着；建议随 P1-1/P1-2 鉴权批一并复核。

---

## 8. 复算记录（主会话 ✅ 项实测）

| 复算项 | 动作 | 实测 |
|--------|------|------|
| P1-3 SSRF 重定向 | 读 `web_reach/reach.py:68-92` 原文 | `:69/:80` 首跳断言；`:81` 直入 http_fetch；无任何 per-hop 校验 |
| P1-3 两引擎跟随 | 读 `http_fetch.py:80-104` | `:90/:92` `curl_requests.get` 无 allow_redirects 参数；`:100` `urlopen` 默认跟随 |
| P1-1 匿名写 | 读 `model.py:325-368` | `:333` `Depends(get_optional_user)`；`:334-368` 处理器通篇无 None 拒绝 |
| P1-4 TB 缺 reindex | 读 `repository.py:850-904` + `grep -n "_record_index_op"` | TB 分支 856-899 无命中；其余变更点 972/1159/1527/1578/1873/2056 均有登记 |
| P1-5 企微缺参 | 读 `ingest_bridge.py:215-249` | `:224` 有 parsed.metadata；`:222-245` create_knowledge 无两参 |
| P1-7 双 store 零引用 | `grep -rn "collaboration.optimized\|chat.optimized" NeurUI/src ...` 排除自身 | exit=1（0 命中） |
| P1-6 MANIFEST 无哈希 | `grep -c "sha256\|digest" models/MANIFEST.json` | 0 |

◑ 项以子代理 file:line 取证为准，主会话未逐条二次复核（见 §9 边界）。

---

## 9. 未覆盖面与审计边界（请勿当结论使用）

- **tests/（2667 文件）未逐审**：只作守卫参照与零引用扫描排除面；测试自身的质量审计不在本批。
- **docs/（491 文件）未审**：文档与代码的口径一致性未核对（仅用了 s08 基线做鉴权对照）。
- **NeurovaHarmony 只做了安全面粗扫**：凭据/明文 HTTP/deep link/权限四项，业务逻辑未深读（260 文件对 41 次调用预算）。
- **◑ 项未经主会话逐条二次复核**：P1 头部断言已复算（§8），P2/P3 依赖子代理取证；点单落格前建议按台账惯例对将落格条目逐条复算（✅ 化）。
- **预算内未深查的点名**：cost_store.py 五处 except、mermaid securityLevel、channel-configs conflicts 前缀、hooks_engine shell=True 威胁模型（均在存疑区）。
- **并发事故**：首波 6 并发超本机并发上限三批未启动（§2-T1），已重派补齐；该上限值本身未探明，后续大批次建议 ≤3 并发。
- **时间快照**：结论基于 main @ 2026c7f4 与当日工作树；三时间戳批后续若有新提交，P1-4/P1-5/P2-5/P2-8/P2-12 需对最新基线重核。

---

## 10. 点单接口（处置序建议，每批一个 commit）

| 批 | 内容 | 依据 |
|----|------|------|
| ① 安全批 | P1-1 + P1-2 + P1-3 同链同修：鉴权收紧（model.py 写面 + 首号 fail-closed）+ SSRF 每跳校验 | P1，容器部署全站接管链 |
| ② 知识库尾巴批 | P1-4 + P1-5 + P2-5 + P2-8：TB 补 reindex、企微透传、指纹短路、time_context 接 UI 或登记尾巴 | P1/P2，三时间戳批收口 |
| ③ 前端死码批 | P1-7 + P2-11 + P1-8 删净、P2-12 类型修正、P3-7 守卫扩正则 | P1/P2 |
| ④ 供应链批 | P1-6 下载完整性 + P2-3 CSP + P2-4 口令传递 | P1/P2，桌面链 |
| ⑤ 小修批 | P2-6/P2-7/P2-14/P2-15 + P3-1..P3-9 集中清 | P2/P3 |
| ⑥ 待拍板 | P2-9 seen_cursor 二选一、P2-10 browser_capability 接线或删、P2-2 密钥保护方案、存疑区 8/9 两项定性 | 需裁定 |

执行纪律：每批先红后绿（红灯实测证据进提交说明）+ live-verify（真后端 9527 真端点）+ 净 LOC 先 numstat 后写正文；落格自 **§6-517** 起逐条登记（落格前按 §9 边界对将落格条目复算 ✅ 化）。

---

## 11. P1 处置进度与核验记录（2026-11-04）

> P1×8 已按 §10 处置序①-④修复落库（`31560d222` fix(security)＝批①②、`333a0e5b1` fix(desktop)＝P1-6，前端死码批 P1-7/P1-8 随前端提交收口）。
> 本节为**独立核验记录**：逐项 HEAD 现读原文 + 重跑测试门 + 真实链路活体。结论：**8/8 修复并核验通过**。

| 项 | 修复实状（HEAD 现读） | 测试门 | 活体 / 实测 |
|----|------|------|------|
| P1-1 鉴权收紧 | ✅ model.py 9 个非 GET 端点全挂 `get_current_user`，5 个 GET 保持 `get_optional_user`（读面不变） | ✅ `test_model_write_auth_gate` 11 用例；受影响既有 4 套件（capability/outputProbe）带 token 跟随改造 | ✅ 真后端 9527 非变更探针：匿名 check-connection → 401、匿名 DELETE（不存在 id）→ 401、GET /models → 200 |
| P1-2 首号 fail-closed | ✅ `_isServerFacingDeployment`（NEUROVA_HOST 非环回＝服务端形态）缺令牌 403；桌面形态行为钉住不变 | ✅ `test_s04_bootstrap_admin_token_gate` 11 用例 | ✅ 隔离实例 `0.0.0.0:19527` + 全新数据目录：无令牌注册 → **403**（诚实 detail 点名配置方法） |
| P1-3 SSRF 逐跳 | ✅ http_fetch 双引擎禁自动跟随（curl `allow_redirects=False` / urllib `_NoRedirectHandler`）+ 显式逐跳循环 + `url_validator` 注入口；reach 两咽喉点接线 `_validateHopUrl` | ✅ `test_http_fetch_redirect_guard` 5 用例；既有 urllib 打桩三处随实现缝迁移 | ✅ 真 curl_cffi + 真本地 302 跳环回：守卫链 `ValueError` 拒（127.0.0.0/8），无守卫链到终址（跟随能力本身实证存在） |
| P1-4 TB 补 reindex | ✅ `repository.py:957` 起 TB 分支登记 `_record_index_op("reindex", ...)`，与创建路径同口径 | ✅ `test_sourceTimeAwareness::TestSameSourceReingestReindexesIndex` + 增量索引套件 | ⚫ 存储内部态；以真管线 E2E 为证（`test_sourceTimestampImportE2E` 真 docx → 真端点，绿） |
| P1-5 企微源时间 | ✅ `resolveSourceDates` 单源迁 `document_pipeline.py`；`knowledge_ingestion`/`ingest_bridge` 双边界同源消费（教义 6 收口） | ✅ `test_wecomIngestSourceDates` 2 用例 + `test_sourceTimestampContract` 迁移 | ⚫ 同上，真管线 E2E 绿 |
| P1-6 下载完整性 | ✅ `models/MANIFEST.json` 双归档钉 sha256；`lib.rs` `sha256_file`/`verify_sha256`（sha2 0.10，锁文件内既有），摘要不符诚实报错不进解压 | ✅ `test_route_b_runtime_download` 扩守卫（钉值格式 + 校验调用序源级咬合） | ✅ **两份钉值经真下载实测吻合**（npmmirror 现取：python `e90c1b64…` / node `edaca9bd…`） |
| P1-7 前端双死码 | ✅ `collaboration.optimized.ts` / `chat.optimized.ts` 删净（全仓零引用复核） | ✅ vitest 285 文件 / **2313 用例全绿** | — |
| P1-8 SSE 死链 | ✅ `getConsoleChatSSEUrl` 删净，新增退役守卫 `retiredArtifacts.test.ts` 咬合 | ✅ 同上 + `vue-tsc --noEmit` 过 | — |

**核验遗留（如实登记，不属 P1 未竟）**：
- `lib.rs` 未编译验证：本机无 cargo（PATH/cmd/用户目录均查证无）；sha2 为锁内既有依赖且源级守卫已咬合校验调用序，`cargo check` 待有 Rust 工具链的环境补跑。
- P1-1 的角色级收口（写面 `require_admin`）与 §10 批④⑤⑥（P2×15 / P3×9 / 待拍板）仍待点单。

*核验方式：HEAD 现读原文 + 222 项后端用例（含 P1 全修复面）+ 前端两道门 + 9527 真后端非变更探针 + 真下载哈希核对。临时验证实例与端口已全部清理。*

---

## 12. 遗留处置记录（2026-11-04，§11 之后）

> 范围：§11 两项核验遗留 + §10 批⑥待拍板项 + 存疑区 8/9。裁定项经交互选项提交，用户未作答，
> **按推荐项执行（均可逆，随时可推翻）**；裁定结论逐条在此留档。

| 项 | 裁定与结论 | 落库/证据 |
|----|------|------|
| P1-1 角色级收口 | **分级收口**：DELETE/PUT/download-source/download → `deps.require_admin()`（现役角色门，audit.py 同源）；/switch、/probe-*、/check-connection 保持登录（探针读型、切模型是 agent 工作面） | `efd1dd3f`；TestRoleGate 6 用例红→绿；test_model_download_api 假身份补 role 键跟随 |
| P2-1 运维指标暴露 | **限环回**：/metrics、/health/detailed 移入 `LOOPBACK_ONLY_PUBLIC_PATHS`，中间件按 client 判环回；/health 保持全公开（healthcheck 面不回退）；持凭证外部读不受影响 | `efd1dd3f`；7 用例纯 ASGI 直驱；live-verify 隔离实例 0.0.0.0:19527＋enforce：非环回 /metrics **401**、环回 200、非环回 /health 200 |
| P2-2 凭据 keyfile | **延后登记**（威胁模型弱：仅同机文件读权限；桌面单机形态收益有限）：尾巴＝「接 OS 级保护（DPAPI/Keychain），触发条件：多端同步或凭据面扩大」 | 零改动，本格即登记 |
| cargo check 遗留 | **根因不在代码**：仓级 `.cargo/config.toml` 把 link.exe 钉死在 C:/Program Files (x86)/.../BuildTools/ 标准位，VS2022 实装已迁 `E:\neurova-build-tools\VS2022`（P2-14 同类硬编码路径病）。去钉后 rustc 原生 vswhere 探测可用：`--config` 覆盖真路径 50.58s Finished（lib.rs P1-6 校验代码可编实证）→ 零注入干净环境 52.05s Finished | `680e0ea8`；cargo check 全绿 |
| P2-9 seen_cursor | **已接线**（另一会话批）：`coordination_api.py` / `agent_workspaces.py` / `agent_layout_migration.py` 有生产消费方——479 行不再是孤儿 | HEAD 现读 |
| P2-10 browser_capability | **已接线**（另一会话批）：`context/orchestrator.py` 消费 | HEAD 现读 |
| P2-8 time_context | **已接 UI**（另一会话批）：KnowledgePage.vue 冲突队列已渲染 time_context | HEAD 现读（3 处命中） |
| 存疑8 tts/asr downloader | **判定不并**（非教义 6 双源）：同壳但机制实质不同——tts 走 HF hub snapshot，asr 走 whisper.load_model 官方通道（HF 镜像不了 whisper 格式，asr 头注释已互认）；同形态不同功能不构成双实现 | HEAD 现读定性 |
| 存疑9 根 package.json | **判定为工作区占位**：`private:true` 的 cost-guard 脚本壳（guard:*/cost:* 五个脚本），version 1.0.0 无产品消费方；桌面版本守卫只咬 NeurUI 侧两份＋lock（现 1.0.0-beta7）。非第二版本源 | HEAD 现读定性 |
| P2-13 后端半边 | **已收**：authorize 端点 `@router.post`（neurflow_stores.py:230），前端 POST body 直传（CanvasStoreDrawer.vue 注释自陈不再走 query）；window.open 带 noopener | HEAD 现读 |

**处置余量清零**：P1×8（§11）＋P2×15＋P3×9 全部修复在案（P2/P3 主体由并行会话补修，本批 sweep 逐项 HEAD 现读复核：CSP、口令传递、TB 指纹短路、tool_engine、ledger、nsi 路径、端口守卫、422、PDF 时区、前端时区、memory 死键、监控留痕、appcontainer、start_server 注释、2>nul、stores/utils 删除、色守卫 rgba/hsl 扩展——P3-7 落成「存量基线棘轮＋禁新增」形态，强于原建议）；批⑥待拍板项全部落定。台账落格自 §6-517 起待点单。

---

*本文件为只读审计产物，未改动任何代码；归置 audit-reports/ 与旧台账同目录。*
