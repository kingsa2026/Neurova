# U2 收尾修复台账（MemorySecurity encrypt 读侧透明解密·补漏批）

会话：U2 · 日期：2026-11-17 · 依据：R3 台账 3.3-5 遗留移交 + 用户拍板（本轮做读侧）

---

## 勘查结论（现读 HEAD，含前批落地形态）

**前批（fdf72ba4b，2026-11-17）已落地读侧主体**：`Memory.to_dict → plaintextContent()`
统一解密出口——按 `metadata._security.encrypted == "fernet"` 标记调
`decrypt_sensitive_content`，模型层唯一读出口（`test_memoryCipherFailFast`
守卫钉死收敛面）；写侧维持 R3 形态（remember 咽喉入口加密，内存态与库一致
存密文，标记随行进 metadata）。本批任务据此转为：**勘查 → 补漏 → 闭环举证**。

**密文形态与标记方式**：
- encrypt 态落库内容 = Fernet 令牌（`gAAAAA…` ASCII）；标记 = 行
  `metadata._security.encrypted`（`fernet`/`mask`），mask 行内容是掩码文本
  （不可逆，读侧原样）。**无独立标记列、无内容前缀**——memories 表零 schema
  变更，本批不需要 db_migration 注册。
- 内存态不变量（本批补钉）：`metadata._security.encrypted=fernet ⇔ 行内容是
  密文`，即「带标记行的 content 只能以密文形态落行」——此前内容改写边界不
  维持它，改一次内容该行即永久读不出（本批红灯第 3 面实测炸出）。

**读点清单（R3 台账有底，grep 全量复核当前 HEAD 后定性）**：

| 读点 | 装配方式 | 定性 |
|------|----------|------|
| `_row_to_memory`（manager.py:666，7 处 SELECT 全收敛：`_load_from_db`/`reload_memories`/`searchMemoriesFulltext`/`iterBodyMemories`/`bodyMemoryById`/`get_top_memories_by_temperature`/`get_top…` 行取） | 行→Memory | 读面经 `to_dict` 已解密（前批）；本批补温度出口自拼 dict |
| `Memory.to_dict`（models.py:428→411 `plaintextContent`） | Memory→dict | 前批已修，唯一模型读出口 |
| `get_top_memories_by_temperature`（manager.py:3071） | Memory→自拼 dict | **本批修**（neurova_recall 温度通道消费） |
| 图谱 traverse 节点（manager.py:4966） | Memory→自拼 dict | **本批修**（用户可见读出口） |
| `explain_memory`（manager.py:5057） | Memory→自拼 dict | **本批修**（用户可见读出口） |
| MoE `ExpertDrilldownRetriever._layer0_exact_index`（moe_router.py:211） | SELECT * 直取 dict，绕过 `_row_to_memory` | **本批修**（高温行必入候选，密文进上下文） |
| `UnifiedMemoryNode.from_memory`（cognitive_storage_engine.py:212） | Memory→节点（reasoning_trace/unified_retriever/结晶巡检消费） | **本批修**（节点层纯读装配面） |
| `_applyContentChange`（manager.py，`update_memory`+睡眠合并两调用方） | 内容改写→落行 | **本批修**（不变量维护） |
| MoE 向量索引灌库（mem_core.py:787/849） | SELECT 行 content→`index_memories` | 域外（文件域边界）→**移交** |
| 线索派生 pending 行（manager.py:2194） | Memory→LLM 提示行 | 域内派生面→按既有「检索面按密文建索引」拍板口径维持退化，登记 |
| FTS 影子同步（manager.py:253 `INSERT … SELECT rowid, content`） | 行→FTS 索引 | 既有拍板退化族（密文建索引），不动 |
| `home.py:81`/`pollution_purge`/`db_indexes`/`creditRecallHits`/`adjustBodyTemperature`/`_seed_counter_from_db` | 计数/id/EXPLAIN 探针/非内容列 | 不消费 content，无需解密 |
| `version_control`（rollback_to_version） | 版本恢复→Memory | 生产零调用（预存）；恢复若接线必须经 `_applyContentChange`（本批不变量已覆盖）或 remember 重筛 |

---

## 根因与修复点（补漏 6 处 + 诚实化 3 处）

**根因**：前批把解密收敛在 `to_dict`，但「读出口」不止 to_dict 一族——
① 自拼 dict 的读出口、② 行直读装配面、③ 内容改写边界，三族绕过面上
encrypt 行仍以密文流出（或改写后永久读不出）。同根因全命中点按上表扫荡。

**修复点**（教义第 1/6 条：实现单源仍在 security.py，出口消费同一原语）：

1. `manager.get_top_memories_by_temperature`：`"content": mem.content` →
   `mem.plaintextContent()`（温度通道自拼 dict）。
2. `manager` 图谱 traverse 节点：同形改 `plaintextContent()`。
3. `manager.explain_memory`：同形改 `plaintextContent()`。
4. `manager._applyContentChange`（live 行内容变更唯一入口）：带
   `encrypted=fernet` 标记的行改内容时按标记重加密落行（标记是行自带属性，
   不重查当下写处置开关——运维翻回 log_only 不得把已加密行降级成
   「明文+标记」坏行）；`update_memory` 与睡眠合并两调用方一轮覆盖。
5. `moe_router._decryptRowContent` + `_layer0_exact_index` 接线：行直读面按
   标记解密；解不开的行 ERROR 点名跳过（一行坏密文不打空整条 L0 通道）。
6. `cognitive_storage_engine.UnifiedMemoryNode.from_memory`：`content=
   mem.plaintextContent()`（节点层纯读装配面——grep 证实无 `to_memory` 写回
   路径，解密不毒化写回；解密失败诚实上抛，损坏行按 loud 故障暴露）。
7. `security.py`：新增 `MemoryDecryptError(ValueError)`（`_FernetCipher.decrypt`
   改抛专用异常）；`encrypt_sensitive_content`/`decrypt_sensitive_content` 在
   「fernet 被要求但加密器缺席」时由 warning+明文/密文回落改为 **fail-fast**
   ——静默回落明文会让标记行以明文落库，静默回密文等于把乱码当原文交付。
8. `manager._load_from_db` / `reload_memories`：解密失败从泛 `except Exception→
   debug 跳行` 拆出 `except MemoryDecryptError → ERROR 点名（行仍在盘上，需
   恢复密钥后重载）`——解密失败不再吞成 debug（教义第 2 条）。

---

## 红灯证据（先红后绿，教义第 3 条）

新增 `TestEncryptReadSideBypassingToDict` 4 面，修前实跑 **4 failed**：

- `test_top_temperature_lane_returns_plaintext`：
  `assert 'gAAAAABq-4Kg…-fmHqBRR2E8g=' == '我的服务器密钥是 sk-…'`——温度通道密文直出。
- `test_moe_l0_lane_returns_plaintext`：同形——L0 行直读密文直出。
- `test_update_content_keeps_encrypted_row_readable`：
  `ValueError: Fernet 解密失败（令牌或密钥不匹配）: 'ascii' codec can't encode…`
  ——带标记行改内容后 get_memory 直接炸，该行永久读不出（不变量缺失活伤）。
- `test_fernet_without_cipher_fails_fast`：`DID NOT RAISE RuntimeError`——
  no-cipher 静默回落（encrypt 返明文 / decrypt 返密文）。

## 绿灯证据

- 定向三套：`test_memory_encrypt_read_side.py` + `test_memory_security_wiring.py`
  + `test_memoryCipherFailFast.py` = **21 passed**。
- 回归：`tests/unit/memory/` **1218 passed** + 2 failed（test_storage×2——
  stash 本批 4 个生产文件后 A/B 复跑仍红，证实预存）；`tests/unit/cognitive_layers/`
  **612 passed** + 1 failed（`test_futureNotRecalled`——同法 stash A/B 证实预存）。
  合计 1830 passed，新增失败 0。
- 守卫：`testCipherChainCallersStayPinnedToTheSingleReadOutlet` 收敛面判据随
  接线合法扩为 {models.py, moe_router.py, manager.py}（实现单源不变，出口集
  显式钉死，集合外直调即红）。

## live-verify（教义第 4 条：真 MemoryManager + 真 SQLite WAL 库）

env `NEUROVA_MEMORY_SECURITY_WRITE_ACTION=encrypt`，临时脚本即用即删，实测：

1. 写入：`remember` → 行 content 以 `gAAAAA…` 密文落库，标记 `fernet`；
   body 库 `journal_mode: wal`（真 SQLite WAL）。
2. 同实例读面：`get_memory` 原文 ✓；`get_top_memories_by_temperature` 原文 ✓；
   `recall("服务器密钥")` 语义命中且原文 ✓。
3. 重启装载（新实例，`memories_loaded=1` 走 `_load_from_db`）：`get_memory`
   原文 ✓。
4. 内容改写（`update_memory`）：改写后行内容仍密文 ✓（不变量维持），
   `get_memory` 读出轮换新原文 ✓。
5. MoE L0 行直读面：捞到该行且 content 原文 ✓。
6. 对照面：mask 行读出掩码、密钥前缀无泄漏 ✓；log_only 行零漂移 ✓。

## 遗留移交

1. **mem_core.py:787/849（域外）**：MoE 向量索引直读行 content 灌
   `index_memories`——encrypt 行建在密文上的向量是垃圾，L3 向量兜底通道对
   encrypt 行检索退化（`_layer3_vector_fallback` 命中质量不可靠）。本批
   moe_router 出口已保证命中行**内容**读原文；索引侧接线属 mem_core.py
   （文件域边界外），移交下一批。
2. **manager.py:2194 线索派生（域内，维持退化）**：线索生成 pending 行直用
   `mem.content` 作 LLM 提示素材——按 R3 既有拍板「encrypt 态检索面按密文建
   索引」口径维持；解密会让密文外的明文出域流转给模型面，不在读侧透明化
   口径内，登记备议。
3. **version_control.rollback_to_version 生产零调用（预存）**：若未来接线，
   恢复路径必须经 `_applyContentChange`（本批不变量覆盖）或 remember 重筛，
   不得直写 `mem.content`。
4. **不可读行管理面**：解密失败当前形态 = ERROR 点名 + 跳行（行仍在盘上）；
   「管理页显式列出不可读行 + 密钥恢复引导」属产品拍板项，未在本批口径。
