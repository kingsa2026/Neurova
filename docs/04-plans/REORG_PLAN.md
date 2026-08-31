# 文档重组计划（Document Reorganization Plan）

> 配套脚本：`scripts/reorg_docs.py`（默认 dry-run，安全）。
> 本计划是 `docs/INDEX.md` 的**执行细则**——单一事实源 = INDEX 导航 + 本计划的落地。

## 目标
将 `docs/` 下 139 个扁平 `.md` 文件按主题归入已有子目录，消除"一层平铺"导致的可检索性崩溃，
并删除已确认的冗余簇。**不**拼接成单一大文件（那会摧毁定位能力）。

## 执行步骤
1. 预览（不改任何文件）：
   ```bash
   python scripts/reorg_docs.py --dry-run
   ```
2. 审阅打印出的 MOVE/SKIP/PURGE 列表，确认无遗漏或误判。
3. 执行移动（保留 git 历史，用 `git mv`）：
   ```bash
   python scripts/reorg_docs.py --apply
   ```
4. （可选）删除白名单冗余，仅保留权威版：
   ```bash
   python scripts/reorg_docs.py --apply --purge
   ```

## 归类规则（`scripts/reorg_docs.py` 内 RULES）
按文件名关键词命中第一优先级：bug→`bug/`，memory→`memory/`，graph/architecture→`architecture/`，
voice/tts→`voice/`（新建），plugin/skill→`plugins-skills/`（新建），harmony→`harmony/`（新建），
ui/frontend→`web/`，comparison/对标→`research/`，report/总结→`reports/`，其余→`misc/`。

## 冗余白名单（`--purge` 仅删这些）
记忆升级 5 篇重复（保留 `memory-system-upgrade-plan-final.md` 为权威）：
- memory-system-upgrade-summary.md
- neurova-memory-system-upgrade-technical.md
- memory-nerf-upgrade-plan.md
- nerf-memory-system-analysis.md
- nerf-frontend-adaptation-summary.md

## 安全约束
- 目标目录已有同名文件 → **跳过并报警，绝不覆盖**。
- 未出现在白名单的文件**不会被删除**。
- 所有移动优先走 `git mv`，保留版本历史。

## 完成判据
- `docs/` 扁平 `.md` 文件数从 139 降至接近 0（仅剩 INDEX.md / REORG_PLAN.md 等导航文件）。
- 每个子目录文件数在 INDEX 第 2.1 节登记。
- 新人通过 `docs/INDEX.md` 可在 2 步内定位任意主题。
