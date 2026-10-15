"""同一 `identity_key` 导入给两个属主时，检索面不得互相顶掉（§6-229 仍开① / §6-231 收紧过前提）。

前提先按现量收紧，别再照着"跨作用域同名 id 会撞"这句话动手：
- **auto 号撞不了**：`mem_%06d`（`manager.py:1372`）由每 agent 单实例的 `_counter` 单调发，
  且 `_seed_counter_from_db:728-733` 取的是**全库** `MAX(...)`（WHERE 只按 `id LIKE 'mem_%'`，
  不按作用域过滤，docstring 自陈"跨作用域取全局最大 id"）⇒ 同 agent 下不同 (neuser,user)
  共用同一条序列，永不重号。
- 唯一真会撞的是 **ingest**：`_ingest_memory_id = "ing-"+sha256(identity_key)[:16]`（`:140-144`）
  只由 `identity_key` 决定，而属主在 `:1933-1934` 另设为 `owner or eff` ⇒ 同一条历史被导入给
  两个 owner 时，业务 id 相同、三层隔离的后两层不同。持久层自 §6-229 起已按作用域限定行存
  （不覆盖），但**关键词倒排与运行期向量索引仍按业务 id 建**（`semantic_search.py:199/217/230`、
  `unified_vector_store.py:690-706`）⇒ 后导入那份把前一份的索引位覆盖掉，检索面少一条事实。

现网读数（2026-10-15 现场）：`default` 14 行、`kai` 4 行里 `ing-` 行 **0**，同业务 id 跨作用域 **0**
⇒ 这是潜在缺陷而非现役故障。但修法不选"给索引层处处加作用域键"（那要动召回读面一整片），
而选**在产生该 id 的这一侧**把属主并进哈希（教义第 1 条）：同一 owner 反复导入仍然幂等，
不同 owner 从此拿到不同业务 id，"每业务 id 只留一份"那族歧义在导入路上不再被触发。

**一条被实测否掉的旧前提，记在这里免得下次再照着动手**：本票原文写"同业务 id ⇒ 后导入那份
把前一份的关键词倒排/向量槽位顶掉，召回少一条事实"。变异反证（把 owner 从哈希输入里摘掉、
退回旧公式，跑真 API 链：两份实例、各自 reload 后按属主召回）实得
`{'alice': ['甲的那段历史'], 'bob': ['乙的那段历史']}` —— **两个属主都召得回**。
机制在 §6-229 那一轮就变了：持久层按作用域限定行存（日志当场打出"持久化 id 与既有行冲突
…改为作用域限定行"），而读侧每次只装一个作用域。所以那句"顶掉"今天不成立 ⇒ 本档**不以召回
为主证**（主证只有 id 形状那条，旧公式下它确实相同、格会红）；召回两格降格为**反向钉**：
不许因为改了 id 公式而让任一属主召不回来。

判据三格：主格（两属主必须拿到不同业务 id——旧公式下这条会红）、同格内的**反向钉**
（各属主仍召自己那条）、幂等格（同 owner 重复导入不新增第二行）＋前缀格（`ing-` 是撤销口径
与本仓其它判据认的形状，不许顺手改掉）——后两格合在两个函数里，共三档函数、四处断言。
"""
from __future__ import annotations

from pathlib import Path

from tests.cognitive_body_store import bodyManager

AGENT = "ingestscope"


def _record(identityKey: str, content: str):
    from neurova.memory_ingest.bundle.records import MemoryRecord

    return MemoryRecord(identity_key=identityKey, content=content,
                        memory_type="semantic", category="general", origin="owner",
                        importance=60.0, ts="2026-05-01T10:00:00+00:00")


def _import(manager, identityKey: str, content: str, owner: str) -> str:
    manager.import_memories([_record(identityKey, content)],
                            ingest_run_id="nvimp-scope-1", owner_user_id=owner)
    rows = [m for m in manager.get_all_memories() if content in (m.get("content") or "")]
    assert len(rows) == 1, "导入后正文里数到 %d 行（内容 %s）" % (len(rows), content)
    return rows[0]["id"]


def testTwoOwnersGetDistinctBusinessIdsAndEachStillRecallsOwnRow(tmp_path: Path):
    """主证＝两个属主拿到不同业务 id（旧公式下这条确会相同，格会红）。

    后半段的召回断言是**反向钉**，不是主证——变异反证证明它在旧公式下也绿（档头写时机理）。
    留着是因为本批改的是 id 公式，最容易犯的错就是"改完 id 之后某属主再也召不回来"。
    读面为什么开**第二份 manager**（同库不同实例）：`import_memories` 的 docstring 自陈
    "不喂关键词倒排、不同步 MoE 向量库"——回填的历史不是"刚发生的经验"，生产读法本就是
    另一个进程 reload 之后再召回。
    """
    manager = bodyManager(tmp_path, agentId=AGENT)
    idA = _import(manager, "ik-shared", "甲属主的那段历史", "alice")
    idB = _import(manager, "ik-shared", "乙属主的那段历史", "bob")
    assert idA != idB, (
        "两个属主拿到同一个业务 id（%s）⇒ 索引层按业务 id 单槽，后导入那份会顶掉前一份" % idA
    )

    reader = bodyManager(tmp_path, agentId=AGENT)   # 正文库同份（tmp_path 下），快照独立
    # 导入行的三元组是 (agent, owner, owner)——`_build_imported_memory` 把 neuser 与 user
    # 都设成 `owner or eff`，所以作用域要按这个形状请求；写成 ("ne-x","x") 就根本装不进来。
    with reader.request_scope("alice", "alice"):
        reader.reload_memories()
        contentsA = [h.get("content") for h in reader.recall(query="甲属主的那段历史", limit=5)]
    with reader.request_scope("bob", "bob"):
        reader.reload_memories()
        contentsB = [h.get("content") for h in reader.recall(query="乙属主的那段历史", limit=5)]

    assert any("甲属主" in (c or "") for c in contentsA), (
        "甲召回不到自己那条（实得 %s）⇒ 被乙的导入顶掉了" % contentsA
    )
    assert any("乙属主" in (c or "") for c in contentsB), (
        "乙召回不到自己那条（实得 %s）" % contentsB
    )


def testRepeatedImportUnderTheSameOwnerStaysIdempotent(tmp_path: Path):
    """反向钉：同 owner 反复导入同一条 identity_key 仍命中同一行——幂等是这套 id 的存在理由。"""
    manager = bodyManager(tmp_path, agentId=AGENT)
    first = _import(manager, "ik-once", "只属于甲的那段历史", "alice")
    manager.import_memories([_record("ik-once", "只属于甲的那段历史")],
                            ingest_run_id="nvimp-scope-2", owner_user_id="alice")

    rows = [m for m in manager.get_all_memories() if "只属于甲" in (m.get("content") or "")]
    assert len(rows) == 1, "同 owner 重复导入插出了 %d 行 ⇒ 撤销与去重都靠这个 id，它必须稳定" % len(rows)
    assert rows[0]["id"] == first


def testIngestIdKeepsTheIngPrefix(tmp_path: Path):
    """形状锁：`ing-` 前缀是撤销口径与本仓其它判据认的形状，收口只许改哈希输入。"""
    manager = bodyManager(tmp_path, agentId=AGENT)
    landed = _import(manager, "ik-prefix", "带前缀的那段历史", "carol")
    assert landed.startswith("ing-"), "导入行 id 形状变了（实得 %s）" % landed
