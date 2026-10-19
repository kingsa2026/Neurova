# -*- coding: utf-8 -*-
"""T-09 死码处置批：`tool_layers/schemas.py` 自循环面的终局（Issue #174 / #310）。

## 这一批处置的是什么

台账里 `ToolSchema` / `ToolParameter` / `ToolSource` 三条判据同为 `self_loop`
（有定义、消费点全落在自己定义文件内），同族根因也同一条：**定义完整，但外部零消费者**。

## 逐条裁定（每条都有机器可验的依据）

**① `ToolSource` / `ToolParameter` / `ToolSchema` 三者的真实消费点**

形态与上下文域实测过的 `dedup` / `clear` 反例**逐字同型**：按名字 grep 会把
**同名而不同源**的四处算成它们的可达性。故台账把「按名字计数会误判」写成依据，
而本批的裁定必须按**引用点的接收者/归属**逐条读：

```
ToolSchema    sites=4  api/endpoints/tool_schema.py:32  def   ← pydantic 响应模型（同名第二份）
                       api/endpoints/tool_schema.py:84  call  ← 构造的是那一份 pydantic 模型
                       tool_layers/__init__.py:24        import ← 孤立再导出（无消费）
                       tool_layers/schemas.py:139        def
ToolParameter sites=7  execution_engine/tool_engine.py:33   def   ← 同名第二份 dataclass
                       execution_engine/tool_engine.py:531  call  ← 构造的是那一份
                       execution_engine/__init__.py:14      import ← 占位 fallback
                       execution_engine/__init__.py:39      def    ← 同名占位类
                       tool_layers/__init__.py:24           import ← 孤立再导出
                       tool_layers/schemas.py:95 / :213     def/call ← 本行登记对象
ToolSource    sites=2  tool_layers/__init__.py:24 import ← 孤立再导出
                       tool_layers/schemas.py:35   def
```

**② 裁定：`已删除`。** 三条都不构成独立能力，且**真面已存在**：

- `ToolSchema.to_openai_format()` 想做的事情 = `openai_schema.ToolSchemaConverter`
  的 `openai_to_*` 家族（**T-03 已接线，有跨文件消费者**：`llm/providers/tool_transport.py`）；
- `ToolParameter.to_schema()` 想做的事情 = `OpenAIFunctionSchema.parameters` 的
  JSON-Schema dict 形态（LLMClient 实际收的就是这个 dict，不是 dataclass）；
- `ToolSource` 是 `ToolSchema.source` 字段的类型标注——**标注不构成消费点**，
  而 `ToolSchema` 自身已在本批退场，它随之失去唯一挂靠点。

故同批三条退场，`schemas.py` 保留 `ToolType` 与 `MCPConnection` 两条。

**2026-10-19 就地纠正本文件的两处假前提**（原判据把"保留"的理由写成
「`MCPConnection` 是 `mcp_client` 的配置契约」并拿 `mcp_manager` 里那句
`MCPConnection(` 当消费证据）。实读：`mcp_client.py` 里 `MCPConnection` 出现 0 次；
`mcp_manager.py:116` **自带同名类**（字段 `connection_id`／`server_config`），
它不 import `tool_layers.schemas`。而 `schemas.py:26` 那一份除门面 re-export 外
**零生产消费者**——`ToolType` 同样零消费者。也就是说下面这句原标准
「不留空壳、不留『导出但无人读』」当时就被自己违反了两条，只是那格绿着。
现由 `test_schemasModuleKeepsOnlyTheLiveContract` 真咬住，并把这两条登记为
待裁（`SCHEMAS_KEPT_UNREAD_PENDING`，裁它的票是 §6-334 的 D 票）。

## 与 `api/endpoints/tool_schema.py` 的边界（同名第二份不连坐）

`api/endpoints/tool_schema.py` 的 `ToolSchema` 是**独立的 pydantic 响应模型**，
与 `schemas.py` 的 dataclass 同名而不同源，且它自己**是活的**（端点 `POST /v1/tools/schema`
真实构造它）。本批**不动它** —— 这正是台账那一行依据「按名字 grep 会把 api 端点的
自消费算成本行的可达性」的落点。本条判据反向钉住它仍在。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

#: 本批退役的自循环面三符号。
RETIRED_BY_THIS_BATCH = ("ToolSchema", "ToolParameter", "ToolSource")

#: barrel 里必须逐条消失的名字（与上者同集；分开命名是因为后一条断言按**词边界**
#: 匹配，而 `AnthropicToolSchema` / `GoogleToolSchema` 含子串但是另一组符号）。
RETIRED_BY_THIS_TREE = RETIRED_BY_THIS_BATCH

#: 同批**必须保留**的符号：它们与退役面同文件但仍在役。
KEPT_IN_SCHEMAS = ("ToolType", "MCPConnection")

#: 保留但**零生产消费者**的符号——本表是"待裁"而不是"豁免"。
#: 双向咬合：新增零消费者的留下符号必须进来（否则第一问红），而它一旦被接线或被删
#: 就必须**从这里摘掉**（否则第二问红）。每条都要写清裁它的那张票。
SCHEMAS_KEPT_UNREAD_PENDING: dict[str, str] = {
    "ToolType": (
        "§6-334 D 票同源待裁：除门面 re-export 外零消费者。裁「接线」还是「随 schemas.py 一起退役」"
        "属人裁——本批只把假前提守卫改对，不动符号。"
    ),
    "MCPConnection": (
        "§6-334 D 票：与 `mcp_manager.py:116` 自带的那份同名而不同源；门面 re-export 之外零消费者。"
        "裁「接线／退役／留」都要先看 websocket 传输那一形（全仓唯一实装），故需人裁。"
    ),
}


def _schemasFace(symbol: str):
    """把 `symbol` 在生产面的落点分成三份：定义处 / 门面再导出 / 真消费者。

    按 AST 判代码身份，不按词：门面那行的 `from .schemas import X` 与 `__all__` 里的
    `"X"` 都是"导出"，不是"有人读"（本档上面给退役三符号用的正是这条口径——
    「import ← 孤立再导出（无消费）」）。取数走共享入口 + 文本预筛。
    """
    import ast

    from tests import ast_scan

    defs: list[str] = []
    facades: list[str] = []
    consumers: list[str] = []
    for ref in ast_scan.sourceRefsUnder(PROJECT_ROOT / "neurova", hints=(symbol,)):
        rel = ref.path.relative_to(PROJECT_ROOT).as_posix()
        owns_definition = False
        mentions = set()
        for node in ast.walk(ast_scan.transientTree(ref.path)):
            if isinstance(node, ast.ClassDef) and node.name == symbol:
                owns_definition = True
            elif isinstance(node, (ast.Name, ast.Attribute)):
                mentions.add(node.id if isinstance(node, ast.Name) else node.attr)
            elif isinstance(node, ast.ImportFrom):
                mentions.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                try:
                    mentions.update(ast.literal_eval(node.value))
                except (ValueError, SyntaxError):
                    pass
        if owns_definition:
            defs.append(rel)
        elif symbol in mentions and rel.endswith("__init__.py"):
            facades.append(rel)
        elif symbol in mentions:
            consumers.append(rel)
    return defs, facades, consumers


class TestSelfLoopFaceIsRetired:
    """自循环面三符号整体退场：真面已存在，留着就是第二份定义在自说自话。"""

    #: 登记对象各自的**拥有者**（哪一行定义才是本行登记的那一份）。
    #: 裸名判据对这三条给不出 `absent`：残留站点是同名而**不同源**的第二份
    #: （与上下文域 `dedup` / `clear` 同型——按名字计数不可判别）。
    #: 故本类只钉「拥有者级」事实：定义落在哪个文件。台账那一行同时显式记录了
    #: 判据轴收窄为「裸名」这件事，两边一致。
    OWNER_OF_RECORD = {
        "ToolSchema": "neurova/tool_layers/schemas.py",
        "ToolParameter": "neurova/tool_layers/schemas.py",
        "ToolSource": "neurova/tool_layers/schemas.py",
    }

    #: 同名第二份的拥有者（必须**仍在**，它们不是本行的登记对象）。
    SAME_NAME_OTHER_OWNERS = {
        "ToolSchema": "neurova/api/endpoints/tool_schema.py",
        "ToolParameter": "neurova/execution_engine/tool_engine.py",
    }

    @pytest.mark.parametrize("symbol", RETIRED_BY_THIS_BATCH)
    def test_symbolsAreAbsentInProduction(self, symbol):
        """拥有者级判据：登记那一份的定义必须从它的文件里消失。

        `ToolSource` 的裸名判据仍能给 `absent`（无同名第二份）；另两条给不出，
        故一律走**归属**（定义落在哪个文件），这是「某个拥有者的这个面已消失」
        唯一能被机器表达的口径。
        """
        sites = ledger.referenceSites(symbol)
        defining_files = {site.path for site in sites if site.form == "def"}
        own = self.OWNER_OF_RECORD[symbol]
        assert own not in defining_files, (
            f"{symbol} 仍在 {own} 有定义落点——「已删除」是口号，符号还在"
            f"（现有定义文件 {sorted(defining_files)}）"
        )

    @pytest.mark.parametrize("symbol", sorted(SAME_NAME_OTHER_OWNERS))
    def test_sameNameOtherOwnersStillDefineIt(self, symbol):
        """反向控制：同名第二份必须**仍在**——它们不是本行的登记对象。

        没有这一条，「拥有者级判据」就可能靠「全仓都删干净」冒充咬合，
        而那正是按名字 grep 判死会造成的事故（连带删掉活的面）。
        """
        sites = ledger.referenceSites(symbol)
        defining_files = {site.path for site in sites if site.form == "def"}
        other = self.SAME_NAME_OTHER_OWNERS[symbol]
        assert other in defining_files, (
            f"{symbol} 在 {other} 的定义消失了——本批连坐删掉了活着的同名第二份"
            f"（现有定义文件 {sorted(defining_files)}）"
        )

    @pytest.mark.parametrize("symbol", RETIRED_BY_THIS_BATCH)
    def test_ledgerDisposalMatches(self, symbol):
        entry = ledger.readLedger().get(symbol)
        assert entry is not None, f"{symbol} 从取数表与台账同时消失——判据丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_RETIRED, (
            f"{symbol} 台账处置为 {entry['disposal']}，未标「已删除」"
        )

    def test_schemasModuleKeepsOnlyTheLiveContract(self):
        """`schemas.py` 只留仍在役的契约——不留「导出但无人读」的空壳。

        这一格按它自己的名字（LiveContract）咬两问：
        ① 每个被留下的符号必须有**真生产消费者**（门面再导出不算——本档给退役三符号
           用的正是「import ← 孤立再导出（无消费）」这条口径），否则必须出现在
           `SCHEMAS_KEPT_UNREAD_PENDING` 里并写明裁它的票；
        ② 那张待裁表必须**恰好等于**实测的零消费者集合：漏一个＝把新空壳静默放行，
           多一个＝它已被接线或已删还挂着豁免。
        """
        text = (PROJECT_ROOT / "neurova/tool_layers/schemas.py").read_text(encoding="utf-8")
        unread: set[str] = set()
        for kept in KEPT_IN_SCHEMAS:
            assert f"class {kept}" in text, (
                f"仍在役的 {kept} 被本批连带删除——退役必须落在符号级，不是文件级"
            )
            _defs, facades, consumers = _schemasFace(kept)
            if not consumers:
                unread.add(kept)
            assert consumers or kept in SCHEMAS_KEPT_UNREAD_PENDING, (
                f"{kept} 零生产消费者（门面再导出 {facades} 不算有人读）却没登记待裁——"
                f"这正是本档声称「不留导出但无人读」要拦的形状。要么接线，要么进 "
                f"SCHEMAS_KEPT_UNREAD_PENDING 并写清裁它的票。"
            )
        assert unread == set(SCHEMAS_KEPT_UNREAD_PENDING), (
            f"待裁表与实测分叉：实测零消费者={sorted(unread)} 表内="
            f"{sorted(SCHEMAS_KEPT_UNREAD_PENDING)}（多了要摘行并附依据，少了要补行）"
        )
        for symbol, why in SCHEMAS_KEPT_UNREAD_PENDING.items():
            assert "§6-" in why, f"{symbol} 的待裁依据没写票号：{why!r}"

    def test_barrelNoLongerExportsTheRetiredThree(self):
        """barrel 的导入与 `__all__` 条目必须逐条消失。

        按**词边界**匹配，不按子串：`AnthropicToolSchema` / `GoogleToolSchema` 含
        `ToolSchema` 子串但**是另一组符号**（T-03 的真面，仍在役）。子串匹配会把
        它们误判成残留 —— 与台账那一行「按名字 grep 会误判」是同一条纪律。
        """
        import re

        text = (PROJECT_ROOT / "neurova/tool_layers/__init__.py").read_text(encoding="utf-8")
        for symbol in RETIRED_BY_THIS_TREE:
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
            assert not pattern.search(text), (
                f"barrel 仍导出/导入 {symbol}（词边界匹配）——"
                "符号已退场而导出还在，import 侧会拿到半死面"
            )

    def test_disposalConflictsAreEmpty(self):
        assert ledger.disposalConflicts() == [], repr(ledger.disposalConflicts())


class TestSameNameSecondCopiesAreNotCollateral:
    """同名第二份不连坐——这正是「按名字 grep 判死」会误删的形态。"""

    def test_apiToolSchemaResponseModelStaysLive(self):
        """`api/endpoints/tool_schema.py` 的 `ToolSchema` 是活的 pydantic 响应模型。

        它与 `schemas.py` 的同名 dataclass **不同源**，且被端点真实构造
        （`POST /v1/tools/schema`）。本批不得连坐删除。
        """
        endpoint = (PROJECT_ROOT / "neurova/api/endpoints/tool_schema.py").read_text(encoding="utf-8")
        assert "class ToolSchema(BaseModel)" in endpoint, (
            "api 端点的 ToolSchema 响应模型被本批连带删除——它是活的面，"
            "与 schemas.py 的 dataclass 同名而不同源（按名字判死的典型误伤）"
        )
        assert endpoint.count("ToolSchema(") >= 1, (
            "端点不再构造自己的 ToolSchema——它退化成没有消费点的第二份，"
            "那是另一个需要独立裁定的问题，不该由本批顺手带走"
        )

    def test_engineToolParameterStaysLive(self):
        """`execution_engine/tool_engine.py` 的 `ToolParameter` 同样同名不同源且在役。"""
        engine = (PROJECT_ROOT / "neurova/execution_engine/tool_engine.py").read_text(encoding="utf-8")
        assert "class ToolParameter" in engine, (
            "execution_engine 的 ToolParameter 被连带删除——它是签名内省的实际产出模型"
        )


class TestReverseControlsStillHold:
    """反向控制：本批的「删」不得波及真面与活着的接线。"""

    def test_converterFamilyStaysConsumed(self):
        """真面（`ToolSchemaConverter` / `ToolCallParser`）必须仍有跨文件消费者——
        它们正是本批三符号被裁定「真面已存在」的依据，退场后这一点不得改变。"""
        for symbol in ("ToolSchemaConverter", "ToolCallParser"):
            judge, _detail = ledger.classify(symbol)
            assert judge == ledger.JUDGE_CONSUMED, (
                f"{symbol} 判据类退成 {judge}——自循环面的退场依据（真面已存在）不成立"
            )

    def test_twoMCPConnectionClassesAreDistinctNotOneContract(self):
        """同名两枚 `MCPConnection` 是**两份不同的类**，不是一条契约的两个面。

        本格此前写的是「`MCPConnection` 的真实消费点是 `execution_engine/mcp_manager.py`
        （它从 `tool_layers.schemas` 取它构造连接记录）」——**那句是假的**，2026-10-19
        实读纠正：`mcp_manager.py` 在 `:116` **自带同名 `class MCPConnection`**
        （字段是 `connection_id`／`server_config`），它不 import `tool_layers.schemas`；
        而 `schemas.py:26` 那一份（字段 `server_id`／`transport`）除门面 re-export 外
        **零生产消费者**，且 `mcp_client.py` 里 `MCPConnection` 出现 **0 次**
        （旧文那句「消费方是 mcp_client」同样不成立）。

        所以旧断言 `"MCPConnection(" in manager` 一直为真，却真在**另一份类**上——
        典型的同名自咬（形态集 268／243）。本格改成钉住"两份独立"这件事本身：
        谁要是把它们并成一份、或给 schemas 那份接上真消费者，这格会改变状态，
        必须回来重判 §6-334 的 D 票（删｜接线｜留）。
        """
        import ast

        from tests import ast_scan

        manager_path = PROJECT_ROOT / "neurova/execution_engine/mcp_manager.py"
        managerTree = ast_scan.transientTree(manager_path)
        assert any(isinstance(n, ast.ClassDef) and n.name == "MCPConnection"
                   for n in ast.walk(managerTree)), (
            "mcp_manager 不再自带 MCPConnection——两份同名类的关系变了，"
            "本格与 §6-334 的 D 票都要重判"
        )
        importedFromSchemas = [
            node for node in ast.walk(managerTree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("tool_layers.schemas")
            or isinstance(node, ast.ImportFrom) and any(
                a.name == "MCPConnection" for a in node.names)
        ]
        assert not importedFromSchemas, (
            f"mcp_manager 现在从别处 import MCPConnection（{[n.module for n in importedFromSchemas]}）"
            "——两份已并成一条契约，本格前提没了：请把 §6-334 的 D 票按「接线」重判，"
            "并把 schemas 那份从待裁表里摘掉"
        )
        clientText = (PROJECT_ROOT / "neurova/tool_layers/mcp_client.py").read_text(encoding="utf-8")
        assert "MCPConnection" not in clientText, (
            "mcp_client 开始引用 MCPConnection——schemas 那份有了真消费者，"
            "SCHEMAS_KEPT_UNREAD_PENDING 必须摘行（上一格会红，那是对的）"
        )
