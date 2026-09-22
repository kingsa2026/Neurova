# AGENTS.md —— 开发上下文速查与关键约定

> 本文件是**纪律与约定的唯一权威出处**（`docs/INDEX.md` 阅读顺序第 2 位），
> 亦是工作区 AI 指令文件（`neurova/context/workspace_docs.py` 运行时读取）。
> 文档各领域权威源见 [`docs/INDEX.md`](docs/INDEX.md)；人类贡献者入口见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
> 本文件被全仓 90+ 处以「`AGENTS.md` 修复教义第 N 条」编号引用——**改条款编号前先 grep 引用方**。

---

## 0. 无人值守 AI 协作（NPC）必读

在本仓被 `@` 唤起执行的 NPC，以及任何自动化改码流程，**一律**按本文件执行。
机器可读落点有三处，改任一处必须同步另两处（守卫：`tests/unit/test_repair_discipline_guard.py`）：

| 落点 | 作用 |
|------|------|
| `.cnb/settings.yml` 的 `npc.roles[].prompt` | 平台配置期唯一必达通道——NPC 被 `@` 时加载的就是它 |
| 本文件 `/AGENTS.md` | 纪律事实源；被 90+ 处编号引用 |
| `CONTRIBUTING.md` 测试纪律节 | 人类贡献者入口 |

---

## 1. 修复教义（Repair Doctrine）

修 bug 与写代码的**最高纪律**。每条都要求机器可验证，不靠自觉。

**第 1 条 · 根因处修复，禁止 consumer-only guard。**
在报错出现的地方加判空、吞异常、加兜底默认、改 try/except 把异常包住——都只是把症状挪走。
判据：**把报错恢复原状后，若不修根因，故障必然复现**。修复点应当在上游生产该非法状态的地方（解耦门、契约归一、事实源唯一），而不是在下游补 None 检查。

**第 2 条 · 禁止表面抹除与规避报错。**
不得删除报错信息、不得吞异常（`except: pass`）、不得降级断言、不得把失败改写成 warning 了事、不得用"跑不起来就算过"短路门禁。
报错要么被根修，要么以**诚实形态**暴露（显式 4xx/5xx、`not_supported`、点名失败原因）。净新增 LOC 默认 ≤ 0，为正必须在提交说明里逐条列明去向；测试代码不计入。

**第 3 条 · 先红后绿 TDD 红绿灯。**
新增功能与缺陷修复一律走：**红灯**（先写断言缺陷/期望行为的失败测试并实证它真的红）→ **绿灯**（最小实现让它转绿）→ **重构**（绿着收拾）。
提交说明必须附红→绿的实测输出；不许"写完实现再补个绿灯测试"充数。
禁止的测试写法：`MagicMock` 冒充业务对象（`MagicMock().get("success", True)` 恒真）、恒真断言、绕过生产装配点（手工传阈值/手工传 `agent_id`）直接赋私有字段、以"库里能查到一行"代替"判据咬合"。
红灯文件在转绿前**不得**进 `scripts/ci/protected_tests.txt`（该清单只收逐文件单跑确定全绿的）。

**第 4 条 · live-verify。**
改完必须跑真实链路自证（真后端启动 + 真端点/真管线），不以单元测试全绿代替端到端活体验证。证据（命令 + 输出原文）进提交说明。

**第 5 条 · 放大视角，同一根因全命中点扫荡。**
一个断链被点名后，必须 grep 同契约的**全部**消费方/生产方一并修；不能修报告的那一条链就当完事。
命中点无法当场处理时，登记到台账里，不许静默遗留。
本条同样适用于威胁处置：同一根因的攻击面在所有命中点闭环。

**第 6 条 · 单一事实源，不新造平行体系。**
参数、枚举、口径、配置只允许一处定义。发现第二份定义时，收口到一份并删掉另一份（含其测试与死码），而不是"两边都留着、加个同步脚本"。

---

## 2. 协作红线（Issue #68 定稿）

Issue #68 明确要求写进"项目配置"的通用准则。与修复教义同为本仓最高纪律。

- **交流语言**：面向用户的回复、Issue/PR 评论、提交信息正文、文档正文**一律使用中文**。
  代码标识符、命令、路径、第三方 API 字段名保持原文，不做翻译；面向国际化的产品文案仍按
  `docs/03-user-guide/i18n/` 的多语言对齐纪律执行，不因本准则放宽。
- **原创性与自主性**：**严禁**在代码注释、技术文档或提交信息中引用、模仿或对齐任何第三方项目
  （不写"参考 XX 项目""对齐 XX 实现""与 XX 保持一致"之类表述，不搬运其命名、结构与措辞）。
  所有产出必须基于本项目的独立设计与实现；外部依赖只作为**功能依赖**登记（版本、许可、用途），
  不引入其设计标准；研究参考类文档仅作背景，**不可作事实源**。
- **命名风格（Neurova 技术美学）**：变量、函数、方法用 **camelCase**
  （`resolveMemoryAnchor()`、`memoryTemperature`）；类、模块、类型用 **PascalCase**
  （`MemoryRecallEngine`、`ContextPoolIndex`）；常量用全大写下划线（`MAX_RECALL_DEPTH`）。
  命名以**简洁、语义清晰**为准，体现功能意图与业务领域；**禁用** `data`/`info`/`temp`/
  `handler`/`manager`/`util`/`helper`/`process` 这类通用模糊词，除非叠加领域限定。
  新增测试用例名用驼峰时，pytest 收集由 `pyproject.toml` 的
  `python_functions = ["test_*", "test[A-Z]*"]` 放开（由 `tests/unit/core/test_pytest_collection_hygiene.py` 反向锁住）。
- **规则文档与测试目录归属**：规则/准则/约定类文档统一存放于 `docs/`，仓库根目录不再新增；
  新增准则须在 `docs/0-index/README.md` 登记。测试用例统一存放于本仓**唯一测试根 `tests/`**，
  并按功能模块分子目录（`tests/unit/<module>/`、`tests/integration/`、`tests/e2e/`、
  `tests/performance/`、`tests/fixtures/`、`tests/runners/`）；不得另建第二个测试根造成双源。
- **功能与升级改造**：全局视角，先看全链路（数据从哪来、经谁处理、到哪去、谁消费），不留断点——
  写出无人读的字段、注册无消费者的模块、只写不读的配置、只读不写的指标均属断点，
  必须接线或删除；老路径退役与新路径接线同批完成，形成**写入 → 读取 → 反馈 → 再写入**的闭环。

**无例外条款**：本准则无"紧急可绕过"入口。确需偏离时，必须在 PR 描述中显式说明偏离点、
原因与补偿措施，并同步更新本文件——规则与行为不一致时，以**改规则**为准，不以"默认这么做"为准。

---

## 3. 代码规约

- **深模块模式**：模块经 `agent_ref` 依赖注入访问 Agent，禁止直接 import Agent（循环依赖靠懒加载 `__getattr__` 打破——不要随手把局部 import 提到模块级）。
- **单例**：懒创建型单例必须走 DCL（double-checked locking）+ `threading.RLock`；`neurova/agent/` 包的 `__init__` 链回 `tool_executor`，新增模块导入注意懒加载。
- **可选依赖**：一律惰性 import + fail-soft，不得在模块顶层裸 import 重型可选依赖（torch 等）。
- **SQLite**：多线程访问走 `threading.RLock`；WAL 已在 `core/connection_pool.py` 开启；schema 变更加入 `core/db_migration.py` 注册表（PRAGMA user_version），不要只写 `IF NOT EXISTS`。
- **尺寸棘轮**：`agent_core.py` 有常驻尺寸门禁（`tests/unit/agent/test_agent_core_size_ratchet.py`，基线只降不升）——新装配逻辑落独立模块，不要回填。
- **i18n**：11 语言与 zh-CN 严格对齐（`src/i18n/__tests__/locale-consistency.test.ts` 守卫）。
- **前端主题**：全站禁硬编码色值（`themes.test.ts` 契约），颜色令牌见 `src/styles/variables.css`。

## 4. 测试纪律

- 正式测试落 `tests/unit|integration|e2e|performance/<模块>/`；临时验证脚本即用即删，不留 `tests/` 根目录。
- 唯一测试根 `tests/` 已在 `.gitignore` 里整根豁免，**不得**再依赖 `git add -f` 兜底：
  提交前用 `git status` 确认新文件处于跟踪态即可。守卫
  `tests/unit/test_dev_path_and_runtime_dep_guards.py::TestProtectedSubsetEntriesAreTracked`
  双向钉住——测试根下的正当文件名不得被忽略、跑测产物与敏感件不得被放行。
- 跑测试用项目解释器：`.venv/Scripts/python.exe -m pytest`（Windows）或 `.venv/bin/python -m pytest`。
- **预存失败不算回归，新增失败才算**：涉及共享文件时提交前做 A/B 自证
  （`git stash push <files> && pytest <套件> && git stash pop`），失败集合修复前后逐行比对。
- 前端：`npm run test`（vitest）、`npm run lint`、`npx vue-tsc --noEmit`。

## 5. 提交纪律

- Conventional Commits：`feat(scope): ...` / `fix(scope): ...` / `docs: ...` / `chore: ...` / `refactor(scope): ...`；单任务单 commit。
- commit 正文说明**动机与根因**（不只是改了什么），附红灯/绿灯实测证据与净 LOC 去向。
- 工作树常含其他会话的在途改动：`git commit --only -- <paths>`，**严禁 `git add -A`**。
- 文档：结构性文档进 `docs/` 编号分层目录，过程性分析不留 `docs/` 根目录。

## 6. 安全

发现安全漏洞请勿公开 Issue——流程见 [`SECURITY.md`](SECURITY.md)。
