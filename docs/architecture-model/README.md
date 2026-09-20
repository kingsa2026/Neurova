# docs/architecture-model — Neurova 架构模型

证据接地的架构模型与其可视化产物。**这里的文本源是唯一权威**，任何导出图都是衍生物。

生成日期：2026-09-19　|　视图状态：current　|　产出技能：`architecture-visualization` 插件
（`explore` 路由 → `system-modeler` 主 + `flow-visualizer` / `dependency-impact-analyzer` /
`deployment-topology-analyzer` / `risk-quality-reviewer` 辅，基础层 `c4model` + `graphviz`）

## 文件

| 文件 | 回答的问题 | 格式 |
|------|-----------|------|
| [`architecture-findings.md`](architecture-findings.md) | 全部结论正文（先读这个） | Markdown |
| [`neurova-c4.dsl`](neurova-c4.dsl) | L0 景观 / L1 上下文 / L2 容器 / L3 前后端组件 | Structurizr DSL |
| [`neurova-flows.dot`](neurova-flows.dot) | 一次对话请求穿过的 8 个步骤 + 后处理旁路 + 成本支线，含 4 处 BREAK | Graphviz DOT |
| [`neurova-dependencies.dot`](neurova-dependencies.dot) | 依赖方向、反向回手、三组同域并行实现、129 个重名类 | Graphviz DOT |
| [`neurova-deployment.dot`](neurova-deployment.dot) | 本机 / Docker / Helm 三态拓扑 + 存储落点 + 迁移桩 + CI | Graphviz DOT |
| [`neurova-risks.dot`](neurova-risks.dot) | 13 条风险按 S/A/B/C 分级 + F1–F7 修复次序 | Graphviz DOT |
| [`evidence-model.json`](evidence-model.json) | 67 节点 / 34 边，带 `sourceRefs` 与置信度 | JSON |
| [`architecture-plan.md`](architecture-plan.md) | 范围、受众、证据计划、已知限制 | Markdown |
| [`lint-architecture-sources.py`](lint-architecture-sources.py) | 上述文件的结构自检 | Python |

## 怎么看

**Qoder 内（推荐，零依赖）**：直接打开 `.dsl` / `.dot` 文件，用对应的格式预览器查看。
DSL 含 5 个视图（landscape / context / containers / agent-core / frontend），切换视图即可下钻。

**需要位图时**（须先安装 Graphviz，本机当前没有）：

```bash
dot -Tsvg neurova-flows.dot -o neurova-flows.svg
```

**需要交互 C4 时**（须先安装 Java + structurizr-cli，本机当前没有）：

```bash
structurizr-cli export -workspace neurova-c4.dsl -format workscope-and-aws -output structurizr.json
```

## 阅读顺序

1. `architecture-findings.md` §0 一句话结论 → §6 三处静默失效 → §7 正确性缺陷
2. `neurova-c4.dsl` 视图 `02-context` → `03-containers` → `04-agent-core`
3. `neurova-flows.dot`（看断点在哪）
4. `neurova-dependencies.dot`（改代码前查波及面）
5. `neurova-risks.dot` + §11 修复次序（决定做什么）

## 图的视觉约定

- 红粗线：**反向 / 回手指向私有成员**，改动风险最高（例：`tool_router` 回手调 `_execute_builtin_tool`）
- 蓝虚线：**非正常 import 路径**（遮蔽、`spec_from_file_location`、幽灵模块名、终态未定）
- 橙线：同域概念重复定义且无收敛记录
- 灰点线：声明性 / 弱依赖
- 虚线框节点：stub、孤岛、proposed，或仅存在测试中
- `BREAK-n`：已证实的链路断点，不是画不出来的箭头

## 结构自检

```bash
cd docs/architecture-model && python lint-architecture-sources.py
```

检查项：花括号配平、引号状态扫描（未闭合字面量）、DOT 头与 `cluster_` 前缀、
边端点是否声明、DSL 禁用 `#` 注释与 `..>` 伪运算符、
JSON 模型中是否存在悬空边端点或无 `sourceRefs` 的节点。

当前状态：全部 OK（2026-09-19）。

## 保持新鲜（活文档约定）

模型会随代码过期。以下任一情况发生时需更新对应文件：

| 触发 | 需更新 |
|------|--------|
| 新增/删除 `neurova/api/endpoints/` 模块，或改 `endpoints/__init__.py` 白名单 | `neurova-c4.dsl` 的 `apiFace`、`neurova-flows.dot` 的入口段 |
| `ChatPipeline` 步骤增减或改序号 | `neurova-flows.dot`、`architecture-findings.md` §4 |
| 移动 `skill_system` / `memory` / `llm` 任一日命名称 | `neurova-dependencies.dot` 对应 cluster |
| 新增 ADR | `evidence-model.json` 的 `decisions`、`architecture-findings.md` §5.2 |
| `Dockerfile` / `docker-compose.yml` / `helm/` 端口或副本变更 | `neurova-deployment.dot`（`ci.yml` 的 `deploy-config` job 已钉住这类变更） |
| 修复了某条 Rn | 从 `neurova-risks.dot` 移除该节点，并在 findings §11 标注完成 |

重新采集证据的最短路径：用 `architecture-visualization:explore` 重新路由，
或按 `architecture-plan.md` 的「证据计划」表逐类复核。

## 本模型的已知限制（勿过度解读）

1. **未渲染**：本机无 `dot` / `java` / `mmdc`（已实测），只做了词法与结构校验。
2. **未启动服务**：§6.3 的 404 来自前缀静态推导，未核对 `openapi.json` 实际路由表。
3. **无运行时遥测**：部署图全部为脚本/配置静态推导，不代表生产观测。
4. **工作树未定型**：60 项未提交变更中，`neurova/{db,models,crdt,collaboration}`、
   7 个新端点、`.github/CODEOWNERS`、`cost-guards.yml` 均未跟踪。
   **这些内容一旦 checkout 丢弃，本模型的对应节点即失效**（见 findings §9 的 R11）。
5. `sourceRefPolicy` 为 `resolvable`：所有 `sourceRefs` 应可 grep 到；
   若发现某条已失效，那本身就是一个应当修复的架构漂移信号。
