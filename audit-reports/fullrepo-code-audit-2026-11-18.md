# 全仓代码审计报告 — 2026-11-18

**审计性质**:只读静态审计(10 面并行)→ 统筹合并。非 test pass 报告;未跑全量测试、未改任何文件。

**基线**:统筹盘点时 HEAD `0be8050c`;各面以任务内 `git rev-parse`/工作树现状为准(轮次内工作树非洁:多会话在途 M/R/RM,行号多为工寸现读数,提交判据另 `git log -1 -- <file>`)。约 55 项在途改动横跨 docs/、audit-reports/、少量 neurova/、tests/。

**方法口径**:每面按热度/扇出定向深读 + 全局 grep/引用扫描(个别面自建 AST 扫描脚本);基于"全链路即可追溯 + 修复纪律七条 + 唯一事实源/单一契约"审;修复纪律§1-7、测试禁写法(MagicMock 冒充业务对象/恒真/绕过生产装配)、R4 类守卫红绿、liveness 检查(死面须点名数据流向与功能面)。非文本/二进制/生成物(见 §6)按存在性/排除处理。原宣称"逐一审计所有文件":执行口径为**分面全覆盖 + 定向深判**,非字面每行通读。

---

## A. 已裁定并落地:版本漂移(R4)

- **事实**:`helm/neurova/Chart.yaml:9` appVersion `1.0.0-beta13` vs `neurova/__init__.py:12` `__version__ = "1.0.0-beta14"`;Chart 注释自认"必须等于 `__version__`",守卫 `scripts/ci/deploy_config_consistency_check.py` R4(error 级,`:586-593`),已接线 `.github/workflows/ci.yml` `deploy-config` job(线 64-72)与 `.cnb.yml` 注释第 8 门。
- **裁定(2026-11-18 用户)**:代码 `1.0.0-beta14` 为真值 → Chart 跟进。
- **红→绿实测**(项目 `.venv` 3.12.10,有 pyyaml):改前 `exit=1` 含 `❌ [R4-images] Chart appVersion=1.0.0-beta13 与 neurova.__version__=1.0.0-beta14 不一致`;改后 `Chart.yaml` diff 就一行,R4 消失。**全仓文本源已无 `beta13` 残留**(grep,yaml/py/md/toml/json)。
- **复跑附带现状(非版本裁定所致,未动)**:`❌ [R5-env]` compose 声明 `NEUROVA_MASTER_RECOVERY_PASSWORD` 而应用源码不读(死配置;台账自述源码侧早已退役、恢复可配置形态须回空口令防线,见 `audit-reports/simplification-audit-2026-10-05.md:3077/3084`;helm 部署注入 `deployment-backend.yaml:102` 同型存疑);`⚠️ [R7-auth]` 副本>1 且 `ReadWriteOnce` 嵌入式 SQLite 多进程同写风险。**均在待拍板 #1**。

---

## B. 高

- **webhook 管理面无属主(多租户边界)** `[API]`:`neurova/api/endpoints/webhooks.py:31` router 级依赖 + `:121` 落 `"user_id": "default"` + `:77` 进程级共享 store(dict + `dataPath("webhooks.json")`,`_load/_save` :81-94/:90-91),deliveries 按 webhook_id 反查、无读侧过滤 → 原范围内任登录用户可读/改/删他人的 webhook 与投递记录。身份单通道/可见性走显式字段的仓纪律在此缺位(未见 owner 处理新增痕迹)。
- **子代理记账身份双属性回退** `[agent]`:`swarm.py:2156-2157` `userId = str(getattr(initiator_agent,"current_user_id","") or getattr(initiator_agent,"owner_user_id","") or "")` → 直通 `openSubagentRun(userId=)`(:2162-2172)与 `start_trace(user_id=)`(:2081-2084)。`current_user_id` 是 §3 单通道转发,`owner_user_id` 创建者配置(agent_core.py:264/269)。形态同型"第二 user_id 探测面",**但文件在在途途改动面,出期待对照 HEAD 版与 §3 裁定,不自判违宪**。

## C. 中(择要)

- **`usage_history.agent_id` 列写侧全不填** `[core]`:签名 `usage_history.py:165`(`agent_id: str = ""`),读侧 `agent_token_totals()`(:243-255 SELECT/GROUP BY)+`api/endpoints/analytics.py:303/311-317` 消费按 agent 呈现;全仓定位的生产写点仅 `llm/multi_model_client.py:937`/`:1353`,调用块均不传 agent_id → 列恒 `''`,按 agent 用量视图恒空/汇总。建议补传或诚实化口径(AGENTS §3-7)。
- **字面量 user_id** `swarm.py:2467` `"swarm"`、`tool_executor.py:7922` `"agent"`、`chat_pipeline.py:695-700`;不能道出真实主体,归产品口径观察项。
- **受保护名单空气条目** `[测试治理]`:`scripts/ci/protected_tests.txt`(:867/:871)及 `.1/.2/.3` 分片点 `tests/unit/memory_ingest/test_converter_codex.py`/`:test_converter_qwenpaw.py`——目录盘上无、HEAD 不踪;三分片并集去注释后 864 条与总文件逐条相等。守卫 `tests/unit/ci/test_protected_subset_shards.py` **实跑 1 failed / 15 passed**,失败点即存在性判。成因(清单滞后/重切遗漏/批次退役)未判,留维护者比对。注脚:本机 autocrlf=true,清单物理 CRLF,守卫 splitlines+strip 免疫。
- **文档标已退役模块"✅ 已实现"** `[docs 01-architecture]`:`COMPLETE_MODULES.md:22` 等(state_manager/api_standard/ConfigManager 等 `git ls-files` 0 命中;FUNCTIONALITY_ANALYSIS.md:48/310/317、PHASE5_DEVELOPMENT_PLAN.md:143、plugin-architecture-design.md:532/536/826/971-972)。带 2026-10-20 历史横幅的 `NEUROVA_CogArch_2.0.md` 宽恕面大;其余按"历史快照+已退役"刷表。
- **skills 面裁定记录** `[knowledge/skills]`:`FactSurface`/`mergeIntoLegacy` 测试触达、生产调用零,但 `read_surface.py` docstring 引工单011 真数据否证两池交织 → 不回档"漏接线",提案台账可检索留存;**不预设待用户拍板**(子代理 originally 建议,综述判"已有记录裁定")。
- **08-research 改名波引用面未刷** `[docs]`:约 19 对重命名 + 若干 in-place RM;≥12 非 08-research 文件、≥30 行仍引旧名(token 命中 INDEX.md/0-index/04-* /specs 等);终评正文相对链指向 MISSING 路径(落点文件名已存在)。INDEX"保留原文"注解针对目录级。
- **Mobile 配对 scheme 面** `[Mobile]`:`neurova://pair` Android 有 intent-filter(注释自称两端同一事实源),鸿蒙入库面未见同类 → 鸿蒙端是否闭**待数**;Capacitor 退役证据成立(`ad05c46fd`,现 `git ls-files` 无 web 资产残留);签名物 `.p12`/`passwords.local.md` 等 ignore 自洽(位置形态,不展开);token 类键名持久化面未逐读。
- **docs 计数/态叙述漂移样本**:记录"14+ 渠道/42 py" vs `neurova/channels` 62 py;"82 端点模块" vs `api/endpoints` 274 文件(口径疑路由/注册,**未核不下结论**);"60 页面" vs NeurUI pages 237 文件(未核);肌肉记忆 ✅ 与文件面存在(未跑测试)。
- **`docs/.cf_doc.md`/`.roles.md`**:已跟踪、外部 ASP 内容误置 docs 根(各 ~198KB),记态、**不改**。

## D. 低(合并清单)

- llm 簇:mock 信封 CHAR 进 token(`multi_model_client.py:1796-1818`);OpenAI adapter 缺 usage 估算同形(:251-254);`cost_tracking` 例外吞+warning(:164-217)/未知模型 0.0(:292-296);plugins grants 内层非 dict → 读取崩而非 corrupt 标(:199-205);benchmark 进程级累计差值当本任务用量、并发偏(:76-98/195-199);ASR test 态原地 append mock 无恢复(:29-31/90-93);TTS 默认链含 mock(ASR 反例同仓两叉,产品口径);`computer_use/browser_manager` 抓页无 url_guard 引用(:287-292);`reach._is_youtube_url` 子串匹配;`web_reach/credentials` 坏值→"未配置"同形;sandbox `CreateProcessAsUserW` 失败路径不 CloseHandle(:190-204);notifications 单条读无属主校验(:306-308)+`auth_code` 明文落盘(:66-75/192-193)。
- desktop/CLI/脚本/发行:§0 两条"先做对"(.venv only / 代理变量)无机器护栏; `start.sh` 解释器取向异质(.venv 仅兜底 vs Windows 只准 .venv);`auto_install` 硬编码 `--lang zh`;`create_github_release.py` 硬编码版本不读源 + 链 `CONTEXT.md` 死链;`.scanignore` 不排 .env/.venv(取决于消费工具语义,**未静态确认**);`start_server.py` port_guard 占位降级。
- NeurUI:`global.css:327/331/347` 字面色在硬编码守卫扫描面外;`styles/tokens.ts` 人肉镜像 variables.css;`export let/var` 20 处未核;15 未被 `@/pages` 引文件核为非路由子面板/区(未逐读契约);lint 脚本无 eslint 配置/依赖,**跑不起来**(与 AGENTS §4 记载同态)。
- 知识/进化/认知/skills 低档:eval 族 12 模块生产/测试调用点未分; `parameter_activity` 三态单源(消费面未追); `update_channel_weights` 静态零调用者(反馈增量调整不生效,d19 判定一致); `INTENT_CHANNEL_WEIGHTS` 两表未确同口径;`knowledge/__init__.py` pyc-桥梁占位桩(已跟踪、git 无 diff,史 `7835c3670`);`defaultOffFlags` 9 项编号跳号;双检索门禁(合成夹具硬阈值 vs 入库基线)并存、文档索引未记;bundled 树 `NeurUI/src-tauri/resources/backend` 1182 文件整树 gitignore、零历史、11-18 mtime —— 生成物 vs 手拷贝**未验证**。
- 记录/纪律资产:`repair-ledger-2026-11-16/` 冻结名而最近提交 11-17(11-17 夜→11-18 批无延申载体);`audit-reports/` 64 文件未在 0-index 登记却被当活引用源(`simplification-audit-2026-10-05.md` 热度 609 次触碰);`final-report.md` 档名无日期语境;lint/pylint×6/bandit 等无日期前缀;StartupManager/ModuleSystem 大部分面无驱动读数(候选,未书"死",所附影响面)。

## E. 正面确认(择要)

- `endpoints/__init__.py:363/:377` 注册失败显式 ERROR +「端点注册表未全量装载」;错误码→态映射诚实(`error_handlers.py:26-39`);webhook 入口复用 url_guard;`require_role`→`strictIdentityGate` fail-closed;迁移表 `transitionRun` 单源 + 叫停三态;Telegram 簇 9 文件单组合;workflow 续跑沙盒化 + callTool journal;测试守卫实态(collection hygiene 9 passed;protected-shard 1F/15P);NeurUI 硬编码色守卫咬合 + i18n 三重守卫 + retiredArtifacts 钉;`tests/` 唯一测试根成立。

---

## F. 覆盖与诚实声明

- 10 面全部到货(原批 7 份完整 + 续跑:knowledge/evolution/cognitive/skills、llm 簇、Mobile+docs);各面自带覆盖/未读/无法验证清单,原样有效,未在本报告二次悬浮。
- 无全量测试运行;实锚仅上述守卫红/绿与两条守卫实跑;其余为静态结论,未执行代码路径。
- 排除/受限:二进制资产、`gui-test-screenshots` 时序截图、`node_modules`/`.venv`/`__pycache__`/`.hvigor`/`.pytest_cache`、`dist`、`data`/`logs`/`agent_workspaces`/`test_workspace`/`models/*.data`、`.env` 值、zip bundle、签名物(位置形态打码);部分面"候选/不下结论"原样在案(`Info` 见相应条)。
- 共享树在途改动多,行号/结论以各面任务内 git 核验口径为准;他会话半成品文件已随条注明可疑来源。
- **未提交**:以上任何内容、以及 R4 落地(Chart 一行)均未 git add/commit——需时 `git status`/`git diff` 即可复核。

## G. 待拍板(带约束)

1. R5 死配置 / R7 复制口径:留白(记录现状)/删声明/补消费(须连空口令防线)三选;不可逆点低但补消费路径需重新设计安全边界。
2. `usage_history.agent_id`:写侧补传(需上游可得标识,调用点已定位两处)vs 口径收口改文档/聚合。
3. swarm userId 取法:在途文件,显式参数/单一权威口(对照 HEAD 版与 §3 裁定);不自判违宪。
4. 08-research 文件名级旧引用扫荡 + 0-index 多层目录登记补列——归改名方/文档纪律。
5. 保护名单 2 条:判退役→出正确条目,或判定移除。
6. `skills/models.py` 词表×knowledge 底座×测试 手抄收口方向。
7. bundled 树溯源要构建链证据;双检索门禁收敛记录;`webhooks.secret` 摘/存真签名;`_is_youtube_url` 等校验宽口径、Mobile 配对面、计数口径复核("42/82/60")。

---

*审计其中 7 个发现/结论系子代理在本对话内产出、统筹者去重+核验后合并;引证原序已在各条注明。记录日期 2026-11-18。*

---

## H. 复核与修复执行记录（2026-11-19 接手批，会话唯一无并发）

**复核结论**：本报告主体属实；三处更正——① §A 复跑附带现状里「R5-env 死配置」系误报：`NEUROVA_MASTER_RECOVERY_PASSWORD` 经 `auth.py` 的 `_MASTER_RECOVERY_PASSWORD_ENV` 常量真被 `os.environ.get` 读取（守卫扫描器不解析常量间接），helm `deployment-backend.yaml:102` 注入同样有效；② §B2 所指 swarm.py 已无在途 diff，且 `current_user_id` 是 turn_state 明文的「唯一通道直读转发」，真问题仅是台账行被发送者优先顶掉属主裁定；③ §D「notifications auth_code 明文」实际在 `negative_screen_settings.py`（响应侧已 masked），「单条读无属主」实为仅测试消费、无 HTTP 暴露的 `manager.get_notification`。

**已修复（每笔先红后绿+回归）**：R4 Chart beta14（a606f3bf8）；R5 守卫常量间接（a7213a8e0）；B1 webhook 属主门六端点 + live-verify 12/12（34decf4f2）；B2 子代理台账身份属主优先（51ed34649）；C1 usage.agent_id 接 cost_tracking 既有上下文（0c5507af2）；C3 保护清单两条目随 `8003eb949` 改名迁移+退役署名（ec48d4912）；C4 四份历史快照文档补沿革横幅（30369f0c6）；C6 改名引用面扫荡+断链清零（673 条 0 BROKEN）+0-index 补登 12 份+重复终评件退役（037b73bdd）；C8 端点计数对齐现读 115 路由模块/136 .py（c508bd548）；D 组 plugin grants 内层校验（cd76105bf）、`_is_youtube_url` host 边界（268f377cc）、发布脚本版本单源+删死链（450fe9666）、start.sh .venv 优先（49c923da9）；另清偿登记史守卫预存红——字面 `\n` 坏行拆解+两笔历史退役署名（4cc505d43）。

**仍开放**：C7 Mobile 配对 scheme（待鸿蒙侧数据）；browser 工具 url 策略、`.cf_doc.md`/`.roles.md` 去留、skills 词表收口方向、R7 副本口径（产品/运维裁定）；swarm 回路的 cost 上下文写点（现仅 chat_pipeline 每轮写入，子代理 usage 行留空串不劣化）；`INTENT_CHANNEL_WEIGHTS` 两表数值确证不同（非重复实现，合并须裁定）。

**全量验证**：tests/unit/api 18 failed 均为预存（15 项见 S1/R4 台账，另 3 条经基线工作树 A/B 实证）；tests/unit/ci 修复前 26 failed → 修复后 18 failed，经基线 A/B 实证全部为预存 meta 守卫红，零新增；tests/llm 75P、plugins 128P、web_reach 84P、memory_ingest 296P、deploy_config_guard 38P、登记史守卫 9P。