# -*- coding: utf-8 -*-
"""H2-7 · ③：四列退役——停写、停读、白名单摘净，并防再生（§6-90）。

退役对象（逐项实证过"零读者"，见台账 §6-78 I 条 2026-10-09 复算更正格）：
`storyboards.bgm_prompt`、`storyboards.sound_effect`（拆解写、`PUT` 可编辑、LLM 侧还专门
在提示词里向模型索要，但合片/导出/前端**一处都不取用**；出片 BGM 走的是另一条活路——
用户上传文件后按合片请求参数 `bgm_path` 传进去，与镜头级 `bgm_prompt` 无关，且 AI BGM
无可用服务商）；`storyboards.subtitle_path`（建表以来全仓零写零读的真空列）；
`episodes.duration`（`PUT` 白名单可写、全仓无读取方——合片时长按各镜 `duration` 累加）。

**同名不同表的陷阱**是本批判据必须分表取形的主因：`subtitle_path` 在 **episodes** 表是
活列（字幕产物，SRT 落盘后回写并喂给 FFmpeg，`retention.py` 也点名它），在 **storyboards**
表才是空列；`duration` 在 **storyboards** 表是活列（提交视频与连播时序都读它），在
**episodes** 表无人读。按"名字在全仓消失"来判退役，会误删一条活着的字幕链路。

判据（缺一环就不是退役而是事故）：
1. 表名唯一的两件（`bgm_prompt`/`sound_effect`）在生产面零命中——`neurova/` 与 `NeurUI/src/`
   （含 schema、拆解写入、`PUT`/新增白名单、LLM 提示词索求、TS 类型面）；
2. **分表**取形：`storyboards` 表定义不含 `subtitle_path`、`episodes` 表定义不含 `duration`；
   TS 侧同理按接口切片判；
3. 对照格（防"扫平整表也绿"与删过头）：`storyboards` 仍含 `atmosphere`/`injected_prompt`/
   `duration`/`video_resolution`，`episodes` 仍含 `subtitle_path`；
4. 行为面：拆解替身返回 `bgm_prompt`/`sound_effect` 时，落库行不再有这两个键（写侧真停）；
5. 白名单 AST 面：`update_storyboard`/`add_storyboard_manually` 不含这两件，
   `update_episode` 不含 `duration`（不靠字面量计数——同表活列名会假红）；
6. 旧库兼容：老安装留下的这四列**不 DROP**（不可逆点写在正文与台账），新代码开库后
   读写如常，不因"库里多出一列没人管"而崩；
7. 反向对照：把含退役列的伪 schema / 伪 TS 接口喂给同一扫描器，必须报出来。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from tests import ast_scan

import pytest

pytestmark = pytest.mark.timeout(90)

REPO = Path(__file__).resolve().parents[3]
_STORE = REPO / "neurova" / "aigc_studio" / "store.py"
_SERVICES = REPO / "neurova" / "aigc_studio" / "services.py"
_API = REPO / "neurova" / "api" / "endpoints" / "studio_api.py"
_TS_TYPES = REPO / "NeurUI" / "src" / "api" / "modules" / "studio.ts"

#: 全仓唯一、可直接按名禁绝的两件（不会与别的表撞名）
GLOBALLY_BANNED = ("bgm_prompt", "sound_effect")
#: 分表判定的两件：(表名/接口名, 列名)
PER_TABLE_BANNED = (("storyboards", "subtitle_path"), ("episodes", "duration"))
#: 对照在役件——删了它们就是事故
LIVE_COLUMNS = {
    "storyboards": ("atmosphere", "injected_prompt", "duration",
                    "video_resolution", "first_frame_path"),
    "episodes": ("subtitle_path", "video_path", "content"),
}


def _assetText(path: Path) -> str:
    """`.ts` / `.vue` 里的代码文本（剥掉注释；这类文件不走 AST 预算，只读文本）。"""
    src = path.read_text(encoding="utf-8", errors="replace")
    stripped = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", " ", stripped, flags=re.M)


def _codeText(tree: ast.AST) -> str:
    """从**已解析的语法树**里只取代码里出现的名字（字符串常量 + 名字 + 属性名），不数注释。

    退役说明本身要在 `store.py` 里写清楚"哪四列退役、为何旧列不 DROP"——按原文扫描会把
    这段正当文档判成 offender（假红）。按 AST 取形后，注释与 docstring 之外的真实使用才咬合。
    语法树由 `tests/ast_scan` 的共享预算供给（调用方不再各自 `ast.parse`）。
    """
    chunks = [n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    chunks += [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    chunks += [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    return "\n".join(chunks)


def _tableColumns(src: str) -> dict:
    """`CREATE TABLE IF NOT EXISTS <表>(...)` 的列名集合（按 schema 文本取形）。"""
    out = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\n\);", src, re.S):
        cols = set()
        for line in m.group(2).splitlines():
            cols.update(re.findall(r"^\s*(\w+)\s+(?:TEXT|INTEGER|REAL)", line))
            cols.update(re.findall(r",\s*(\w+)\s+(?:TEXT|INTEGER|REAL)", line))
        out[m.group(1)] = cols
    return out


def _interfaceBody(src: str, name: str) -> str:
    start = src.index(f"export interface {name} ")
    return src[start:src.index("\n}", start)]


def _functionSource(path: Path, fn: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"{path.name} 里找不到 {fn}()")


class TestProductionFaceHasNoRetiredSymbols:
    @pytest.mark.parametrize("name", GLOBALLY_BANNED)
    def test_retiredSymbolGoneFromProduction(self, name):
        offenders = []
        # `.py` 侧的枚举与解析走 tests/ast_scan 的共享预算（`nodeScan` 一次给全
        # 节点流），不私有 `rglob("*") + ast.parse`：那条写法每次调用都要走遍整棵
        # 目录树、成本随代码总量涨（见 tests/unit/test_ci_ast_scan_budget_guard.py）。
        # 预筛词是判据的**充分条件**：连禁名都没出现的文件不可能命中。
        for root in (REPO / "neurova", REPO / "NeurUI" / "src"):
            for path, tree in ast_scan.parsedModules(root, ".py"):
                if "__tests__" in path.parts:
                    continue
                if name in _codeText(tree):
                    offenders.append(str(path.relative_to(REPO)))
            for suffix in (".ts", ".vue"):
                for path in ast_scan.filesUnder(root, suffix):
                    if "__tests__" in path.parts:
                        continue
                    if name in _assetText(path):
                        offenders.append(str(path.relative_to(REPO)))
        assert offenders == [], f"{name} 已退役却仍在生产面出现：{offenders}"

    @pytest.mark.parametrize("table,column", PER_TABLE_BANNED)
    def test_retiredColumnGoneFromThatTableDefinition(self, table, column):
        cols = _tableColumns(_STORE.read_text(encoding="utf-8"))
        assert column not in cols[table], (
            f"{table}.{column} 仍在建表定义里（只写不读的列不该留在 schema 上）")

    def test_typescriptFacesMatchTheRetirement(self):
        ts = _TS_TYPES.read_text(encoding="utf-8")
        assert "subtitle_path" not in _interfaceBody(ts, "StudioStoryboard")
        assert "duration" not in _interfaceBody(ts, "StudioEpisode")
        assert "subtitle_path" in _interfaceBody(ts, "StudioEpisode"), (
            "episodes.subtitle_path 是活列（字幕产物 + retention 点名），不得跟着退役")


class TestRetirementScannerFormIsRight:
    """`_codeText` 从"原文扫描"改成"按 AST/去注释取形"是为了让退役说明能写在代码旁边；
    但这一改也很容易把守卫改成永远绿，所以两个方向都要反证：注释不算使用，真使用必须算。"""

    @staticmethod
    def _pyCodeText(source: str) -> str:
        """把源码解析成树再取形（与生产扫描同一份口径：`_codeText(tree)`）。"""
        return _codeText(ast.parse(source))

    def test_pyCommentMentionIsNotAUsage_butStringConstantIs(self, tmp_path):
        assert "bgm_prompt" not in self._pyCodeText(
            "# bgm_prompt 与 sound_effect 已退役（见 §6-90）\nX = 1\n")
        assert "bgm_prompt" in self._pyCodeText("keep = ('bgm_prompt', 'title')\n")

    def test_tsCommentMentionIsNotAUsage_butFieldIs(self, tmp_path):
        commentOnly = tmp_path / "c.ts"
        commentOnly.write_text("// bgm_prompt 已退役\nexport interface A { title: string }\n",
                               encoding="utf-8")
        assert "bgm_prompt" not in _assetText(commentOnly)
        realUse = tmp_path / "u.ts"
        realUse.write_text("export interface A { bgm_prompt: string }\n", encoding="utf-8")
        assert "bgm_prompt" in _assetText(realUse)


class TestLiveColumnsSurvive:
    """对照面：扫描器不是"越空越绿"。"""

    @pytest.mark.parametrize("table", ("storyboards", "episodes"))
    def test_inServiceColumnsStillDefined(self, table):
        cols = _tableColumns(_STORE.read_text(encoding="utf-8"))
        missing = [c for c in LIVE_COLUMNS[table] if c not in cols[table]]
        assert not missing, f"{table} 的在役列被误删：{missing}"

    def test_schemaScannerActuallyBites(self):
        fake = ("CREATE TABLE IF NOT EXISTS storyboards(\n"
                "  id TEXT PRIMARY KEY, bgm_prompt TEXT DEFAULT ''\n"
                ");")
        assert "bgm_prompt" in _tableColumns(fake)["storyboards"], (
            "扫描器取不到列名——上面那些绿就都是空的")


class TestWhitelistsDroppedThem:
    def test_storyboardEndpointsNoLongerAcceptThem(self):
        for fn in ("update_storyboard", "add_storyboard_manual"):
            body = _functionSource(_API, fn)
            assert "atmosphere" in body, (
                f"{fn} 的切片里没有仍在白名单里的 `atmosphere`——函数体没取到，判据在演空转")
            for name in GLOBALLY_BANNED:
                assert name not in body, f"{fn} 的白名单还收 {name}"

    def test_episodePutNoLongerAcceptsDuration(self):
        body = _functionSource(_API, "update_episode")
        assert "title" in body and "content" in body, "切片切空了，缺 `duration` 是假绿"
        assert "duration" not in body, "episodes.duration 已退役，PUT 白名单还收它"

    def test_functionScannerBitesOnASyntheticOldForm(self, tmp_path):
        """反向对照：把退役名塞回一份伪端点源码，扫描器必须报出来。"""
        fake = tmp_path / "fake_api.py"
        fake.write_text('def update_episode(eid):\n    keep = ("title", "duration")\n'
                        "    return keep\n", encoding="utf-8")
        assert "duration" in _functionSource(fake, "update_episode")


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


class TestWriteSideActuallyStopped:
    @pytest.mark.asyncio
    async def test_break_storyboards_ignores_retired_fields_from_llm(self, store):
        """模型照旧回这两个字段（老提示词缓存/老服务商），落库行也不该有它们。"""
        from neurova.aigc_studio import services

        project = store.create_project(owner_user_id="u1", title="退役写入")
        ep = store.add_episode(project["id"], {"number": 1, "content": "客厅夜"})["id"]

        async def llm(prompt, system):
            return json.dumps([{"number": 1, "title": "镜一", "description": "推门",
                                "image_prompt": "push", "bgm_prompt": "古琴",
                                "sound_effect": "雨声", "duration": 3}], ensure_ascii=False)

        await services.break_storyboards(store, project["id"], ep, llm=llm)
        row = store.list_storyboards(ep)[0]
        for name in GLOBALLY_BANNED:
            assert name not in row, f"拆解仍把退役字段落库：{name}={row[name]!r}"
        assert row["title"] == "镜一" and row["duration"] == 3, (
            "同一次拆解里的在役列被顺手弄坏了")

    @pytest.mark.asyncio
    async def test_storyboardBreakerPromptNoLongerAsksForThem(self, store):
        """向模型索要一份落不了地的字段，等于制造永远没人读的读数。"""
        from neurova.aigc_studio import llm as llm_mod

        spec = llm_mod.STORYBOARD_BREAKER
        for name in GLOBALLY_BANNED:
            assert name not in spec, f"拆解提示词仍在索要 {name}"


class TestOldInstallsKeepWorking:
    """旧库残留列不 DROP（不可逆点），新代码必须容忍"库里有一列没人管"。"""

    def test_legacy_columns_do_not_break_readwrite(self, tmp_path):
        from neurova.aigc_studio.store import StudioStore

        db = str(tmp_path / "legacy.db")
        first = StudioStore(db_path=db)
        first.close()
        # 模拟老安装：手工把退役列加回去
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute("ALTER TABLE storyboards ADD COLUMN bgm_prompt TEXT DEFAULT ''")
        conn.execute("ALTER TABLE storyboards ADD COLUMN sound_effect TEXT DEFAULT ''")
        conn.execute("ALTER TABLE storyboards ADD COLUMN subtitle_path TEXT DEFAULT ''")
        conn.execute("ALTER TABLE episodes ADD COLUMN duration REAL DEFAULT 0")
        conn.commit()
        conn.close()

        second = StudioStore(db_path=db)
        project = second.create_project(owner_user_id="u1", title="旧库兼容")
        ep = second.add_episode(project["id"], {"number": 1, "content": "夜"})["id"]
        sb = second.add_storyboard(ep, {"number": 1, "title": "镜一",
                                        "image_prompt": "push", "duration": 4})["id"]
        second.update_storyboard(sb, {"status": "image_ready"})
        row = second.get_storyboard(sb)
        assert row["image_prompt"] == "push" and row["duration"] == 4, row
        assert second.get_episode(ep)["content"] == "夜"
        second.close()
