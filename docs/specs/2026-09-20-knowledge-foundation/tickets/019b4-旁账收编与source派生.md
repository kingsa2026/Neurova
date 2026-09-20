# 019b-4（前两件）冲突旁账收编 + source 派生

**Blocked by**: 019b-2c
**阶段**: E3（§4.1 旁账不持第二权威、G01）

## 做完的两件
1. **冲突旁账进底座**（迁移 v7 建 `knowledge_entry_conflicts`）。仍只换 `_load` /
   `_save_conflicts` 两个边界，`self._conflicts` 的 dict 与 `list_conflicts` 的返回形状一字不改。
2. **`source` 改成从断言派生**：条目的 `source` 由治理层的 `medium_ref` 回写。
   来源为空的实时写入条目，medium 兜底成 `entry:<kid>`（"来源就是这条条目本身"），
   而**回填行仍用 `legacy:knowledge.json`** —— 搬家不许给历史行安一个新出处。
   两条兜底是同一函数 `_assertionFor(..., mediumFallback=…)` 的一个参数，不另写第二套映射。

## 一条刻意的设计边界
条目级冲突**没有**塞进 007 的 `knowledge_conflicts`。那张表成员是事实行、要求 `policy_basis`
与严重度；这里记的是"两个条目标题一致、内容相异 + 相似度"。硬塞要么丢相似度、
要么靠 fact↔entry 来回翻译。真正的合一在 017（事实层成为条目唯一权威源之后）——
这片只搬存储，不动语义。

## 验收标准与实测
| 判据 | 结果 |
|---|---|
| v7 到位，`knowledge_entry_conflicts` 建表 | 通过（链尾 v7） |
| 闸内检测到冲突 → 重启仍可见；不产生 `knowledge_conflicts.json` | 通过 |
| 记录逐键相同（含 `conflict_id`、相似度、reason、detected_at） | 通过 |
| 裁决（keep_both / supersede_old）落表，且墓碑与冲突两条账同时更新 | 通过 |
| 旧 JSON 一次性搬入并归档；关闸态逐字旧行为 | 通过 |
| `source` 有声明值时原样回来；为空时得到 `entry:<kid>` 且与断言 `medium_ref` 一致 | 通过 |
| 回填行 medium 仍是 `legacy:knowledge.json` | 通过 |
| 真数据三方同数 | 92 事实 / 87 主体不变 |
| 真数据开闸对等 | 除 confidence/source 两个派生字段外 `_items` 逐字段相等；130 份索引文档逐字节相同；检索读数三位同基线 |
| `source` 实际被改写的范围 | **3 / 130**（只有无来源串的条目），不是全表抖动 |
| 套件 | `tests/unit/knowledge/` 530 passed；`core + agent + tests/api` 3144 passed / 1 例已登记预存 |

## 没做的那件（下一刀）
**JSON 条目路径退役**要把 `NEUROVA_KB_NARRATIVE_STORE` 默认翻向 SQLite 并删掉 JSON 分支，
顺带收编 12+ 直连写入方。这一步会改变生产默认行为、且要在跑着的服务上验证一次冷启动，
不适合跟在上面那片里顺手做。
