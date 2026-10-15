"""M-25 作用域限定行的"行自带 id"必须活过一整条持久路径（§6-227 那条缺陷的根修判据）。

现网量到的形状（§6-227）：产物 id 是确定性的，跨作用域同名时 M-25 把持久行 id 重写成
`agent\x1fneuser\x1fuser\x1f业务id`（这步对，绝不覆盖别人作用域的行）；但读回时
`_row_to_memory` 用 `_plain_memory_id()` **剥掉前缀**，内存对象只剩业务 id ⇒ 此后任何一次
`_persist_memory`（现网是睡眠温度腿的 `update_memory` 触发的）都按业务 id 另插一行 ⇒
同一条事实两行。现网读数：14→16、四条产物行两两同内容。

`manager.py:617` 的注释早已写明"按业务 id 更新会插出重复行"，并让 `creditRecallHits` 改按
**行自带 id**——同一根因在**持久路径**上没扫干净（教义第 5 条的第二命中点）。本档把这条口径
钉成会红的判据：装载 → 改一点 → 写回去，必须落在它自己那一行上。
"""
from __future__ import annotations

from pathlib import Path

from tests.cognitive_body_store import bodyManager

AGENT = "rowid"
BUSINESS_ID = "dup_x"
SEP = "\x1f"


def _rows(dbPath: Path) -> list:
    import sqlite3

    persist = Path(dbPath).parent / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % persist.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "select id, content, temperature, neuser_id, user_id from memories order by id"
        ).fetchall()]
    finally:
        con.close()


def _seedCollidingPair(manager):
    """两个作用域写同一个自定义 id：先普通行，再被 M-25 重写成作用域限定行。"""
    with manager.request_scope("ne-a", "a"):
        manager.remember(content="甲作用域的那件事", id=BUSINESS_ID)
    with manager.request_scope("ne-b", "b"):
        manager.remember(content="乙作用域的那件事", id=BUSINESS_ID)


def test_scopedRowSurvivesReadModifyWrite(tmp_path: Path):
    """主格：装载作用域限定行 → 改温度 → 写回，**不许**插出业务 id 的第二行。

    先把业务 id 那行删掉（现网就是这么发生的：我硬删残迹后，作用域限定行还在、
    业务 id 空出来了）——这时按业务 id 写回不再冲突，于是今天会 INSERT 出一行新的重复。
    """
    manager = bodyManager(tmp_path, agentId=AGENT)
    _seedCollidingPair(manager)
    # 快照每个业务 id 只留一份（M-25 那条既定取舍：当前生效作用域优先），所以"要动哪一行"
    # 由装载时的生效作用域决定。先把甲那行装进来并删掉它——现网就是这个形状：
    # 我硬删残迹后，业务 id 空了出来，而作用域限定行还在。
    with manager.request_scope("ne-a", "a"):
        manager.reload_memories()
        assert manager.forget(BUSINESS_ID, soft=False, agent_wide=True) is True
    # 再把乙那条作用域限定行装进快照，走一遍"读 → 改一点 → 写回"
    with manager.request_scope("ne-b", "b"):
        manager.reload_memories()
        manager.update_memory(memory_id=BUSINESS_ID, temperature=11.0)

    rows = _rows(Path(manager._persist_db_path))
    carriers = [r for r in rows if (r["content"] or "") == "乙作用域的那件事"]
    assert len(carriers) == 1, (
        "同一条事实在盘上有 %d 行 %s ⇒ 持久路径按业务 id 写回，把作用域限定行又复制了一份"
        % (len(carriers), [(r["id"], r["neuser_id"]) for r in carriers])
    )
    assert carriers[0]["id"].endswith(SEP + BUSINESS_ID) or SEP in carriers[0]["id"], (
        "幸存行的 id 是 %r ⇒ 它不是那一行作用域限定行，说明写回的仍是业务 id"
        % carriers[0]["id"]
    )
    assert float(carriers[0]["temperature"]) == 11.0, (
        "改的温度没落到那一行上（实得 %s）⇒ 更新打到了别的行" % carriers[0]["temperature"]
    )


def test_loadedObjectKeepsItsRowIdButTheApiFaceDoesNotLeakIt(tmp_path: Path):
    """装载保真：内存对象同时留着"业务 id"与"行自带 id"；跨界字典仍只出业务 id。

    行自带 id 是**持久细节**，把它放进 `to_dict()` 就是让 `\x1f` 泄漏给 13 个 REST 端点与前端；
    可它又必须在对象上活着，否则写回就认错行。两个方向各钉一头。
    """
    manager = bodyManager(tmp_path, agentId=AGENT)
    _seedCollidingPair(manager)
    # 快照每个业务 id 只留一份，装载时"生效作用域匹配者优先"⇒ 要在快照里看到那条作用域限定行，
    # 就得在乙的作用域里装载（这与主格用同一条形，不是为本格另造场景）。
    with manager.request_scope("ne-b", "b"):
        manager.reload_memories()
        scoped = [m for m in manager._memories.values()
                  if SEP in (getattr(m, "row_id", "") or "")]
    assert scoped, "装载后没有任何对象记得自己的行 id ⇒ 写回只能猜"
    mem = scoped[0]
    assert mem.id == BUSINESS_ID, "业务 id 被前缀污染（实得 %r）⇒ API 身份与行 id 混成一件事"
    assert mem.row_id.endswith(BUSINESS_ID) and SEP in mem.row_id
    assert "row_id" not in mem.to_dict(), (
        "to_dict() 出现了 row_id ⇒ 持久细节泄漏到 API 面（前端与端点读的是业务 id）"
    )


def test_agentWideHardDeleteRemovesTheRowItActuallyOwns(tmp_path: Path):
    """同根因第三击：`forget(..., agent_wide=True)` 是管理页口径，能删**他人作用域**的行——
    但持久层删除一直按"调用现场"的三元组算，于是内存删了、盘上那行还在，重启即复活。
    """
    manager = bodyManager(tmp_path, agentId=AGENT)
    with manager.request_scope("ne-b", "b"):
        manager.remember(content="只在乙作用域存在的那件事", id="b_only")
    manager.reload_memories()

    assert manager.forget("b_only", soft=False, agent_wide=True) is True, "前置：管理页口径要能删"
    survivors = [r for r in _rows(Path(manager._persist_db_path)) if r["id"].endswith("b_only")]
    assert survivors == [], (
        "内存里没了、盘上还在 %s ⇒ 按调用现场三元组删，跨作用域那一行永远删不掉（重启复活）"
        % [(r["id"], r["neuser_id"]) for r in survivors]
    )


def test_plainRememberStillWritesUnderItsBusinessId(tmp_path: Path):
    """反向钉（不许收得过紧）：普通新建行没有"另一个作用域占着同名 id"这回事，
    写回必须仍按业务 id 原位落一行——不许凭空给每行都套上作用域前缀。"""
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="普通一行", id="plain_row")
    manager.update_memory(memory_id="plain_row", temperature=42.0)

    rows = [r for r in _rows(Path(manager._persist_db_path)) if "plain_row" in r["id"]]
    assert [r["id"] for r in rows] == ["plain_row"], (
        "普通行的落点或行数变了（实得 %s）⇒ 行 id 这层抽象漏进了正常路径" % [r["id"] for r in rows]
    )
    assert float(rows[0]["temperature"]) == 42.0
