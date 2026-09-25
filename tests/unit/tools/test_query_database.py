"""T-05：附件域只读数据集查询原语 `query_database`。

事故（2026-09-24 取证）：用户上传 `memory.db` 要求"看看有什么信息可以提炼"，
三轮未成。工具面里**没有任何一条原语**能读 SQLite —— `file_parse` 只收 agent
工作区内的 `file_path`，而附件落在 `data/storage/users/**`，结构上够不到。

本文件钉住工具的**注册面、真读链、四条安全红线与有界性**：

1. 注册不变量：schema 与分派表同批存在（防 asr_transcribe 那类"看得见调不动"）；
2. 真读：真 `.db` 字节经真 `files_api.get_attachment_bytes` → 表名/列/行数/样例行；
3. 安全：跨用户句柄拒（D1 属主校验）、写型 SQL 拒、`ATTACH` 拒、`PRAGMA …=` 拒；
4. 有界：`row_limit` 截断并标 `truncated`；
5. 落点：副本根可注入，测试后真实 `data/` 零新增文件。
"""

from __future__ import annotations

import sqlite3
from sqlite3 import Error as _sqliteError
from unittest.mock import Mock

import pytest


def _sqliteBytes(tmp_path, rows: int = 3) -> bytes:
    """造一份真 SQLite 附件字节（判据要真读，不能用替身库）。"""
    path = tmp_path / "source_memory.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, score REAL)")
    conn.execute("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, action TEXT)")
    for index in range(rows):
        conn.execute(
            "INSERT INTO memories (id, content, score) VALUES (?, ?, ?)",
            (index + 1, f"记忆条目 {index + 1}", 0.5 + index),
        )
    conn.commit()
    conn.close()
    return path.read_bytes()


def _registerAttachment(tmp_path, data: bytes, user_id: str = "u1", file_id: str = "file_db_1"):
    """把附件按**上传面的真实写入形状**登记进 files store。

    走的是生产同一条元数据通道（`_files_store` 的条目 + `get_attachment_bytes`
    的真实读盘），不手工把路径塞给被测函数。
    """
    from neurova.api.endpoints import files_api

    blob = tmp_path / f"{file_id}.db"
    blob.write_bytes(data)
    files_api._files_store[file_id] = {
        "file_id": file_id,
        "filename": "memory.db",
        "file_type": "file",
        "mime_type": "application/octet-stream",
        "size": len(data),
        "version": "1.0.0",
        "status": "active",
        "user_id": user_id,
        "agent_id": "kai",
        "path": str(blob),
        "created_at": 0,
        "updated_at": 0,
    }
    return file_id


def _makeExecutor(tmp_path, user_id: str = "u1"):
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.memory_manager = Mock()
    agent.asr_manager = None
    agent.tts_manager = None
    # 身份是请求级真值（三层隔离）：显式赋值，别让 Mock 的 auto-attr 顶包
    agent._current_user_id = user_id
    agent.agent_id = "kai"
    agent.workspace_path = str(tmp_path / "workspace")
    executor = ToolExecutor(agent)
    return executor


@pytest.fixture(autouse=True)
def _isolateQueryCache(tmp_path, monkeypatch):
    """副本根一律注入 tmp：严禁测试写真实 `data/`。"""
    cache = tmp_path / "query_cache"
    monkeypatch.setenv("NEUROVA_ATTACHMENT_QUERY_CACHE", str(cache))
    yield cache


class TestRegistration:
    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "query_database" in _BUILTIN_SCHEMAS
        props = _BUILTIN_SCHEMAS["query_database"]["parameters"]["properties"]
        assert "file_id" in props, "附件取用凭证只有 file_id（D1）"
        assert "file_path" not in props, "不得给模型一条按路径读的口子（D1）"
        assert _BUILTIN_SCHEMAS["query_database"]["parameters"]["required"] == ["file_id"]
        assert "【何时不用】" in _BUILTIN_SCHEMAS["query_database"]["description"]

    def test_dispatch_has_executable(self):
        from neurova.tool_executor import ToolExecutor

        assert "query_database" in ToolExecutor._builtin_dispatch
        method = getattr(ToolExecutor, ToolExecutor._builtin_dispatch["query_database"], None)
        assert callable(method)


class TestRealRead:
    @pytest.mark.asyncio
    async def test_sqliteAttachment_returnsTablesAndSampleRows(self, tmp_path):
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool("query_database", {"file_id": file_id})

        assert "error" not in result, result
        names = [table["name"] for table in result["tables"]]
        assert "memories" in names and "audit_logs" in names, result
        memories = next(table for table in result["tables"] if table["name"] == "memories")
        column_names = [column["name"] for column in memories["columns"]]
        assert column_names == ["id", "content", "score"], memories
        assert memories["row_count"] == 3, memories
        assert memories["sample_rows"], "schema 面必须带样例行（否则模型仍旧看不到内容）"

    @pytest.mark.asyncio
    async def test_explicitSelect_returnsRows(self, tmp_path):
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "SELECT id, content FROM memories ORDER BY id"}
        )

        assert "error" not in result, result
        assert [column["name"] for column in result["columns"]] == ["id", "content"]
        assert len(result["rows"]) == 3
        assert result["rows"][0][1] == "记忆条目 1"

    @pytest.mark.asyncio
    async def test_whereClauseEquality_isReadable(self, tmp_path):
        """带 `WHERE 列 = 值` 的只读查询必须读得出来。

        白名单的写型判定若在正文里扫关键字，裸等号会被当成写型 PRAGMA，
        于是**最常见的一类查询**（按条件取行）全被误拒——工具的显式查询面
        名存实亡（文档 §8 判据 5「读得到」）。
        """
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "SELECT id, content FROM memories WHERE id = 1"}
        )

        assert "error" not in result, result
        assert result["rows"] == [[1, "记忆条目 1"]], result

    @pytest.mark.asyncio
    async def test_scalarFunctionNamedReplace_isReadable(self, tmp_path):
        """`SELECT replace(...)` 是标量函数，不是写型 `REPLACE INTO`。"""
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool(
            "query_database",
            {"file_id": file_id, "sql": "SELECT replace(content, '记忆', 'mem') FROM memories WHERE id = 2"},
        )

        assert "error" not in result, result
        assert result["rows"] == [["mem条目 2"]], result

    @pytest.mark.asyncio
    async def test_readOnlyPragmaTableInfo_returnsColumns(self, tmp_path):
        """只读 PRAGMA（表结构）是白名单内的读取形态。"""
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "PRAGMA table_info(memories)"}
        )

        assert "error" not in result, result
        names = [row[1] for row in result["rows"]]
        assert names == ["id", "content", "score"], result

    @pytest.mark.asyncio
    async def test_rowLimitTruncatesAndMarks(self, tmp_path):
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path, rows=8))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool(
            "query_database",
            {"file_id": file_id, "sql": "SELECT id FROM memories ORDER BY id", "row_limit": 2},
        )

        assert len(result["rows"]) == 2, result
        assert result["truncated"] is True, "截断必须显式标出，不能静默少给几行"


class TestSafetyRedLines:
    @pytest.mark.asyncio
    async def test_nonOwnerFileId_denied(self, tmp_path):
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path), user_id="u1")
        executor = _makeExecutor(tmp_path, user_id="u2")

        result = await executor._execute_builtin_tool("query_database", {"file_id": file_id})

        assert result.get("error"), f"跨用户句柄必须被拒：{result}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO memories (id, content) VALUES (99, 'x')",
            "UPDATE memories SET content = 'x'",
            "DELETE FROM memories",
            "ATTACH DATABASE '/etc/passwd' AS leak",
            "PRAGMA journal_mode = WAL",
            # 写形态的 PRAGMA 不带等号也是写：只查等号会漏（同一根因的第二形态）
            "PRAGMA journal_mode(WAL)",
            "REPLACE INTO memories (id, content) VALUES (99, 'x')",
            # CTE 前缀后的写型语句：语句头是 WITH，正文里的 DELETE 才是最外层动作
            "WITH victim AS (SELECT id FROM memories) DELETE FROM memories",
            "SELECT load_extension('x')",
            "SELECT 1; DROP TABLE memories",
        ],
    )
    async def test_writeAndAttachRejected(self, tmp_path, sql):
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))
        executor = _makeExecutor(tmp_path)

        result = await executor._execute_builtin_tool("query_database", {"file_id": file_id, "sql": sql})

        assert result.get("error"), f"该 SQL 必须被拒：{sql} → {result}"

    @pytest.mark.asyncio
    async def test_attachmentUnchangedAfterWritesAttempted(self, tmp_path):
        """安全红线不是文案：被拒的写型 SQL 不得改动附件本体。"""
        from neurova.api.endpoints import files_api

        data = _sqliteBytes(tmp_path)
        file_id = _registerAttachment(tmp_path, data)
        executor = _makeExecutor(tmp_path)

        await executor._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "DELETE FROM memories"}
        )

        assert files_api.get_attachment_bytes(file_id) == data, "附件字节被改动了"


class TestCacheLanding:
    @pytest.mark.asyncio
    async def test_cacheRootInjectable_noRealDataWrite(self, tmp_path, _isolateQueryCache):
        from neurova.core.data_root import get_data_root

        repo_data = get_data_root()
        before = sorted(p.name for p in repo_data.iterdir()) if repo_data.exists() else []
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))

        await _makeExecutor(tmp_path)._execute_builtin_tool("query_database", {"file_id": file_id})

        after = sorted(p.name for p in repo_data.iterdir()) if repo_data.exists() else []
        assert after == before, f"真实数据根被写入：{set(after) - set(before)}"
        assert _isolateQueryCache.exists() and any(_isolateQueryCache.iterdir()), (
            "副本必须落在被注入的缓存根（SQLite 随机读要求本地稳定副本）"
        )


class TestPrimitiveWiring:
    def test_dbAttachmentNowNamesRealPrimitive(self):
        """T-02 的注入文案对 `.db` 从"无可用抽取原语"改为点名真名（单源）。"""
        from neurova.attachment_parser import suggestExtractionPrimitive

        assert suggestExtractionPrimitive("memory.db", "file") == "query_database"

    def test_synthesisAlphabetDatabaseCategoryPointsToIt(self):
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer

        synth = NLToolSynthesizer()
        assert "query_database" in synth.resolveAlphabetCandidates("database", "数据库 查询")


class TestReverseLock:
    @pytest.mark.asyncio
    async def test_withoutSqlWhitelist_writeReachesReadOnlyConnection(self, tmp_path, monkeypatch):
        """反向锁①：撤掉 SQL 白名单 ⇒ 写型 SQL 落到只读连接上被 SQLite 拒。

        判据咬合点：错误必须是**连接层**给的（只读库），而不是白名单层给的 ——
        否则"撤掉白名单"这件事在判据里看不见。
        """
        from neurova import attachment_dataset as dataset

        monkeypatch.setattr(dataset, "assertReadOnlySql", lambda sql, conn: sql)
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))

        result = await _makeExecutor(tmp_path)._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "DELETE FROM memories"}
        )

        assert result.get("error"), f"只读连接必须挡住写：{result}"
        assert "白名单" not in str(result["error"]), (
            f"白名单已撤，错误却仍来自白名单层，反向锁不成立：{result}"
        )
        assert "readonly" in str(result["error"]).lower(), (
            f"错误不是只读库给的：{result}"
        )

    @pytest.mark.asyncio
    async def test_withoutReadOnlyConnection_writeIsNotRefused(self, tmp_path, monkeypatch):
        """反向锁②：`mode=ro` + `query_only` 撤掉后，同一条写**不再被拒**。

        两道防线都在时它被 SQLite 以 readonly 拒掉；撤掉后无错通过 ——
        "只读连接确实在挡写"这件事因此可被单独观测。
        """
        import sqlite3 as _sqlite3

        from neurova import attachment_dataset as dataset

        monkeypatch.setattr(
            dataset, "openReadOnlyConnection", lambda path: _sqlite3.connect(str(path))
        )
        monkeypatch.setattr(dataset, "assertReadOnlySql", lambda sql, conn: sql)
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))

        result = await _makeExecutor(tmp_path)._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "DELETE FROM memories"}
        )

        assert "error" not in result, f"两道只读防线都撤掉后写仍被拒：{result}"

    @pytest.mark.asyncio
    async def test_withoutPragmaFormList_writeFormPragmaSlipsThrough(self, tmp_path, monkeypatch):
        """反向锁③：放宽 PRAGMA 形态名单 ⇒ `PRAGMA journal_mode(WAL)` 立即可达。

        这条钉住的是"白名单按**PRAGMA 形态**判读写"这件事本身：
        名单一旦退化成"只查名不查实参"，不带等号的写型 PRAGMA 就会被放行。
        """
        from neurova import attachment_dataset as dataset

        monkeypatch.setattr(dataset, "_pragmaFormAllowed", lambda name, argument: True)
        file_id = _registerAttachment(tmp_path, _sqliteBytes(tmp_path))

        result = await _makeExecutor(tmp_path)._execute_builtin_tool(
            "query_database", {"file_id": file_id, "sql": "PRAGMA journal_mode(WAL)"}
        )

        assert "error" not in result, f"名单已放宽，该写型 PRAGMA 应当可达：{result}"

    @pytest.mark.asyncio
    async def test_readOnlyDefensesHoldByDefault(self, tmp_path):
        """正向对照：默认两道防线都在时，副本上的写被拒。"""
        from neurova import attachment_dataset as dataset

        data = _sqliteBytes(tmp_path)
        copy_path = dataset.materializeReadOnlyCopy("file_db_1", data, "memory.db")
        conn = dataset.openReadOnlyConnection(copy_path)
        try:
            with pytest.raises(_sqliteError):
                conn.execute("DELETE FROM memories")
        finally:
            conn.close()


class TestEndToEndLoop:
    """端到端（进程内构造，不起常驻服务）：注入文案 → 工具真读出内容。

    这是 §8 总线判据 1 与 5 的合并判据：附件抽取失败后模型拿到的正文里带着
    `file_id` 与**真原语名**，用同一句柄调用该原语就能读出表结构 ——
    写入 → 读取 → 反馈的闭环在一条用例里咬合。
    """

    @pytest.mark.asyncio
    async def test_noticeNamesPrimitiveAndPrimitiveReadsTheSameHandle(self, tmp_path):
        from neurova.agent.chat_pipeline import ChatPipeline

        data = _sqliteBytes(tmp_path)
        file_id = _registerAttachment(tmp_path, data)
        pipeline = object.__new__(ChatPipeline)
        pipeline._read_attachment_bytes = lambda fid: __import__(
            "neurova.api.endpoints.files_api", fromlist=["get_attachment_bytes"]
        ).get_attachment_bytes(fid)

        notice, _vision = pipeline._inject_attachments_into_input(
            "看看有什么信息可以提炼",
            [{
                "file_id": file_id,
                "filename": "memory.db",
                "file_type": "file",
                "mime_type": "application/octet-stream",
            }],
        )

        assert "query_database" in notice, f"注入文案没有点名真原语：{notice}"
        assert file_id in notice, f"注入文案没有句柄：{notice}"

        result = await _makeExecutor(tmp_path)._execute_builtin_tool(
            "query_database", {"file_id": file_id}
        )
        assert "error" not in result, result
        assert "memories" in [table["name"] for table in result["tables"]]
