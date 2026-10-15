"""context 台账的 FTS 分词器必须跟 `sql_like.FTS_TOKENIZER` 那一份（§6-210 登记的老账⑤）。

现量形状：`neurova/core/sql_like.py:44` 立了 `FTS_TOKENIZER = "trigram"` 并写明理由（默认
`unicode61` 把整段中文当一个 token，对文本里就存在的中文子串**恒 0 命中**——「建了 FTS 表」
不等于「能检索」）；而 `neurova/context/eviction_ledger_db.py:120` 又写了一份
`_FTS_TOKENIZE = "trigram"`。取值今天相同，所以这是**纪律问题不是行为问题**——但第二份定义
正是漂移的入口：哪天单源改了分词器（或反过来），台账那张表就悄悄回到"中文检索恒 0 命中"，
而且没有任何一格会红。

改这一处有一个真约束要钉住：影子表是 `CREATE ... fts5(...)` 后按 `rowid` 回填再 RENAME 的，
**分词器不是改常量就生效**——已有库要换分词器必须走重建。所以本批只收"谁定义这个词"，
不动迁移语义；判据一头钉定义面（`eviction_ledger_db` 里不得再出现这个字面量），一头钉行为
（真建出来的建表 SQL 里 tokenize 仍是单源那份的值）。
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from neurova.core import sql_like

LEDGER_SRC = Path(__file__).resolve().parents[3] / "neurova" / "context" / "eviction_ledger_db.py"


def _stringConstants(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def testLedgerDoesNotCarryASecondTokenizerVocabulary():
    """主红：台账模块里不许再有那份分词器的字面量——它只能引用单源。"""
    assert LEDGER_SRC.exists(), "被测档不在 expected 处（%s）⇒ 这格会空转" % LEDGER_SRC
    assert sql_like.FTS_TOKENIZER not in _stringConstants(LEDGER_SRC), (
        "eviction_ledger_db 自己又定义了一遍分词器字面量 ⇒ 第二份定义（教义第 6 条）"
    )


def testLedgerTakesTheTokenizerFromTheSingleSource():
    """接线锁：不收字面量的话就得真的取单源，否则只是把值删了没接上。

    按**代码形态**判（`sql_like.FTS_TOKENIZER` 这一处属性取值），不钉 import 写法——
    本文件对 `sql_like` 用的是模块式 import（`matchQuery`/`shouldMatch` 都这么走，同仓一致），
    只认 `from … import FTS_TOKENIZER` 会把正当形态判成没接线。
    """
    tree = ast.parse(LEDGER_SRC.read_text(encoding="utf-8"))
    takesIt = any(isinstance(n, ast.Attribute) and n.attr == "FTS_TOKENIZER"
                  and isinstance(n.value, ast.Name) and n.value.id == "sql_like"
                  for n in ast.walk(tree))
    assert takesIt, "eviction_ledger_db 没从 sql_like 取那份分词器 ⇒ 收口没接通"


def testCreatedFtsTableStillUsesTheSingleSourcedTokenizer(tmp_path: Path):
    """行为钉：收口之后真建出来的建表 SQL，tokenize 仍是单源那份值。

    只钉"引用了常量"测不到这条路——建表语句是 `%` 拼出来的，拼错形态（漏引号、拼进错误的
    CREATE）在 AST 上一样干净。
    """
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    dbPath = str(tmp_path / "ledger.db")
    EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")

    con = sqlite3.connect("file:%s?mode=ro" % dbPath.replace("\\", "/"), uri=True)
    try:
        sqls = [r[0] or "" for r in con.execute(
            "select sql from sqlite_master where type='table' and sql like '%fts5%'")]
    finally:
        con.close()
    assert sqls, "没建出任何 fts5 虚表 ⇒ 这格没被测到"
    assert all("tokenize='%s'" % sql_like.FTS_TOKENIZER in s for s in sqls), (
        "建表 SQL 里的分词器与单源不符（实得 %s）" % sqls
    )
