# 知识库（CNB 内置索引）

> 更新时间: 2026-09-25 · 关联 Issue: #242 · 守卫: `tests/unit/ci/test_knowledge_base_index_wiring.py`

把本仓文档与 Issue 切片、向量化写入 CNB 知识库，供仓库页面 AI 对话与
Open API 检索使用，从而搭出 RAG 应用。本文是这条链路的**唯一事实源**。

## 1. 接线（谁在什么时候建库）

| 环节 | 落点 | 说明 |
|------|------|------|
| 建库 | `.cnb.yml` 的 `main.commit.add` → `knowledge-base` | main 分支被推送新提交即增量索引 |
| 索引面 | `docs/**/*.md`（排除见下） | 文档正文 |
| 同步 Issue | `issueSyncEnabled: true` | Issue 与评论一并进库 |
| 读取面 | `.cnb/settings.yml` 各角色 prompt 的「知识库作答」条 | 被 @ 时优先依据知识库作答并注明路径 |

**为什么挂在 `commit.add` 而不是 `push`**：`main` 的 `push: &pipelines` 被
`pull_request: *pipelines` 以锚点别名共用（同一个对象）。把建库塞进 `main.push`
等于「每提一次 PR 就重建整个知识库」——PR 内容尚未定稿，且建库不裁决任何合并
契约。`commit.add` 与 `push` 同为「分支被推送新提交」的入口，却是独立的事件键，
故建库只跑推送侧，PR 侧不受影响。

这条偏离由守卫常驻钉住：PR 侧出现建库任务即红。

## 2. 被排除的面（每条都必须真的改变索引面）

| 排除项 | 理由 |
|--------|------|
| `docs/11-legacy/**` | 正文自述「历史/过时文档……不再维护」，喂给 RAG 会让已被取代的旧方案与现行文档同权回答用户 |

**空转的排除项会被守卫拦下**。`docs/**/*.md` 这类 glob 按 unix 通配语义
**不匹配前导点**，故 `docs/.cf_doc.md` / `docs/.roles.md`（第三方产品文档）
本就不在命中面内 —— 给它们各写一条 exclude 看着尽责，其实一个文件都没排掉，
而平台不报任何错。判据即「排除前后索引面必须真的变小」。

本节不写篇数：读数的事实源是仓库文件系统本身，写进正文的数字是第二份定义，
且它会在**同批合并的另一条 PR** 动到 `docs/` 时当场过期（平台与 CI 都不报错，
同型收口见 `tests/unit/test_docs_index_hand_copied_counts.py`）。需要读数时现场复算：

```bash
# 索引面（unix 通配口径，与平台的 glob 语义一致）
python -c "import glob; print(len(glob.glob('docs/**/*.md', recursive=True)))"
# 排除目录的篇数
find docs/11-legacy -name '*.md' | wc -l
# 点文件（不匹配前导点，故不在命中面内；两者之差即这两个文件）
find docs -maxdepth 1 -name '.*.md'
```

## 3. 参数口径

参数允许集的事实源是 `.cnb/knowledge_options_keys.txt`（抓自平台 Schema 的
`knowledge:update` 定义）。平台 `options` 不受 `additionalProperties:false` 约束，
**写错的键不报错、不告警、静默忽略** —— 本仓曾把行为约束写进
`npc:go.options.prompt`，整条从未生效。

现行取值：

| 参数 | 值 | 口径 |
|------|-----|------|
| `chunkSize` | `1500` | 平台默认值；改大减少切片数（省嵌入调用），代价是跨段落召回变粗 |
| `chunkOverlap` | `50` | 平台默认 `0`；留重叠让跨段落内容在检索时更完整 |
| `embeddingModel` | `hunyuan` | 平台当前唯一支持的嵌入模型 |
| `forceRebuild` | `false` | 增量更新。需**删除并重建**时改为 `true`，跑完记得改回 |
| `ignoreProcessFailures` | `true` | 个别文档处理失败仍更新知识库，避免单文件坏掉导致整库不更新 |

嵌入调用按文档量计费：改 `include` / `chunkSize` 前先估命中文件数
（`find docs -name '*.md' | wc -l`），别让一次提交把整库重算。

## 4. 读取面（写入之后谁在用）

- **仓库页面 AI 对话**：知识库建成后即可在对话中启用，让 AI 基于本仓文档作答。
  页面入口由 `.cnb/settings.yml` 的 `npc.button`（按钮名与描述）与 `npc.defaultRole`
  （默认选中角色）给出 —— 按钮缺名字就没有入口，`defaultRole` 写错名字平台
  **静默回落**且不报错，故两者都由守卫盯住；
- **评论里 @ 角色**：`.cnb/settings.yml` 的在册角色（`DSCoder` / `DSCoder-max` /
  `GLMCoder`）prompt 里都载明「优先依据本仓知识库作答……知识库中没有相关内容时
  明确说明」。这一段是**唯一必达通道**：`npc:go.options` 没有 `prompt` 键，
  写在那里会被静默忽略；
- **Open API**：供外部应用自建 RAG，见下节。

## 5. Open API 检索

令牌需 `repo-code:r`（仓库读）权限。

```bash
curl -G "https://api.cnb.cool/kingsa2026/neurova/-/knowledge/base/query" \
  -H "accept: application/json" \
  -H "Authorization: Bearer ${token}" \
  --data-urlencode "query=如何配置 xx" \
  --data-urlencode "top_k=5"
```

响应是结果数组，每条含 `score`（相关性 0-1）、`chunk`（命中片段）、
`metadata`（`path` 即来源文档路径，可直接作为引用来源）。

对应 CLI（需 `repo-code:r`）：

```bash
cnb knowledge-base query-knowledge-base-get --repo kingsa2026/neurova --query "如何配置 xx" --top-k 5
cnb knowledge-base get-knowledge-base-info --repo kingsa2026/neurova   # 库未建时返回 404
```

## 6. 排障

| 现象 | 先看什么 |
|------|----------|
| 检索不到内容 | 库是否已建：`cnb knowledge-base get-knowledge-base-info --repo kingsa2026/neurova`；404 说明还没成功建过库 |
| 答案引用了旧方案 | `docs/11-legacy/**` 的排除项是否还在 |
| 改文档后召回未更新 | `main.commit.add` 那条流水线是否执行成功；改的是否属于 `include` 的命中面 |
| 怀疑漏了某个目录 | 用 `include` 的模式实测命中数，别凭印象加减 exclude（见第 2 节） |
| 页面上找不到入口 | `.cnb/settings.yml` 的 `npc.button.name` 是否为空、`npc.defaultRole` 是否是在册角色名 |
| 建库跑得很久/很贵 | 本次改动的 `docs/**/*.md` 命中数；必要时调大 `chunkSize` |

## 7. 契约守卫

`tests/unit/ci/test_knowledge_base_index_wiring.py`（已进
`scripts/ci/protected_tests.txt`），六组判据 + 四条反向锁：建库流水线的挂载事件、
options 键集、include 真命中且 exclude 未空转、每个在册角色的作答纪律、
页面入口指向真实角色、指南的导航可达性。注入任一静默失效形态
（未知键、摘掉流水线、空转 exclude、删掉作答条）即红。
