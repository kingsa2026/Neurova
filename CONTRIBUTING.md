# 贡献指南（CONTRIBUTING）

感谢参与 Neurova（智星）。本文覆盖环境搭建、代码规约、测试纪律与提交流程。架构全貌见 [README](README.md) 与 [文档总索引](docs/INDEX.md)；**纪律与约定的事实源见 [AGENTS.md](AGENTS.md)**（修复教义/代码规约/测试纪律/提交纪律），项目上下文见 [docs/CONTEXT.md](docs/CONTEXT.md)。

## 快速开始

```bash
# 后端（端口 9527）
python start.py --backend

# 前端（端口 8100）
cd NeurUI && npm install && npm run dev

# 后端+前端+浏览器
python start.py --chat

# 服务健康检查
python start.py --check
```

环境要求：Python >= 3.10（`scripts/config.py` 强制）、Node.js 18+、`.env` 从 `.env.example` 复制。

## 修复纪律（最高优先级）

完整条款见 [AGENTS.md](AGENTS.md) 第 1 节「修复教义」。四条硬纪律，写码与修 bug 一律适用：

1. **TDD 红绿灯**：先写断言缺陷/期望行为的失败测试并**跑出红灯**，再最小实现转绿，最后重构。
   提交说明附红→绿实测输出。红灯文件转绿前不得进 `scripts/ci/protected_tests.txt`。
2. **修根因**：在产生非法状态的上游修（解耦门/契约归一/事实源唯一），严禁 consumer-only guard ——
   不许在报错处加判空、加兜底默认来消错。判据：把报错恢复原状后，根因处不修则故障必然复现。
3. **放大视角**：一个断链被点名后，grep 同契约的**全部**消费方/生产方一并修；修不了的要登记台账。
4. **禁止抹除或规避表面报错**：不得删报错信息、吞异常、降级断言、把失败改写成 warning，
   也不得用「跑不起来就算过」短路门禁。报错要么被根修，要么以诚实形态暴露（显式 4xx/5xx、`not_supported`、点名原因）。

## 测试纪律（重要）

- **红绿灯 TDD**：新增功能与缺陷修复先红灯后绿灯（见上节第 1 条），不接受「实现写完再补绿灯测试」。
- 唯一测试根 `tests/` 已在 `.gitignore` 里整根豁免（`!tests/**`），普通 `git add` 即可入库——
  **不再需要** `git add -f`。跑测产物（`__pycache__` / `.pytest_cache` / `htmlcov`）与敏感件
  仍单独挡在门外，提交前 `git status` 复核即可。
- 正式测试放 `tests/unit|integration|e2e|performance/` 对应层级；临时验证脚本即用即删，不留仓库。
- 跑测试用项目解释器 `.venv/Scripts/python.exe -m pytest`（系统 Python 与项目依赖不一致）。
- 已知预存失败基线见 `docs/04-plans/` 各计划文档"预存失败 stash 实证"节——**预存失败不算回归，新增失败才算**；提交前用 `git stash push <files> && pytest && git stash pop` 做 A/B 验证。
- 前端：`npm run test`（vitest）、`npm run lint`、`npx vue-tsc --noEmit`（CI 同款检查）。

## 代码规约

- **深模块模式**：模块经 `agent_ref` 依赖注入访问 Agent，禁止直接 import（循环依赖靠懒加载 `__getattr__` 打破——不要随手把局部 import 提到模块级）。
- **单例**：懒创建型单例必须走 DCL（double-checked locking）+ RLock，`neurova/agent/` 包的 `__init__` 链回 tool_executor——新增模块导入注意懒加载。
- **SQLite**：多线程访问走 `threading.RLock`，WAL 已在 `core/connection_pool.py` 开启；schema 变更加入 `core/db_migration.py` 注册表（PRAGMA user_version），不要只写 IF NOT EXISTS。
- **i18n**：11 语言与 zh-CN 严格对齐（`src/i18n/__tests__/locale-consistency.test.ts` 守卫）；新增键用 additions+merge 工作流；法语等含撇号文案注意转义。
- **前端主题**：全站禁硬编码色值（`themes.test.ts` 契约），颜色令牌见 `src/styles/variables.css`。

## 提交规约

- Conventional Commits：`feat(scope): ...` / `fix(scope): ...` / `docs: ...` / `chore: ...` / `refactor(scope): ...`。
- 单任务单 commit；commit message 正文说明动机与根因（不只是改了什么）。
- **提交前 A/B 自证**：涉及共享文件（chat_pipeline/tool_executor/mem_core 等）时，stash 验证失败是否预存，避免把别人的基线失败算作自己引入。
- 并行会话协作：`git add` 只加本任务文件（`--only` 或显式路径），**不要 `git add -A`**——工作树常含其他会话未提交工作。

## 安全

发现安全漏洞请勿公开 issue——流程见 [SECURITY.md](SECURITY.md)。

## 文档

- 结构性文档进 `docs/` 编号分层目录（0-index 至 11-legacy，索引在 [docs/INDEX.md](docs/INDEX.md)）。
- 过程性分析/临时报告不进 docs 根目录（历史教训：根目录曾堆 40+ 散落文件）。
