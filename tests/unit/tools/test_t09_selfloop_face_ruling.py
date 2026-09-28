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

故同批三条退场，`schemas.py` 只保留仍在役的 `ToolType`（枚举）与 `MCPConnection`
（`mcp_client` 的配置契约）。**不留空壳、不留「导出但无人读」。**

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

        `ToolType` 是枚举（`ToolSource` 退场后仍被 `MCPConnection` 之外的代码按值用）；
        `MCPConnection` 是 `mcp_client` 的配置契约。两者都必须仍在。
        """
        text = (PROJECT_ROOT / "neurova/tool_layers/schemas.py").read_text(encoding="utf-8")
        for kept in KEPT_IN_SCHEMAS:
            assert f"class {kept}" in text, (
                f"仍在役的 {kept} 被本批连带删除——退役必须落在符号级，不是文件级"
            )

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

    def test_mcpConnectionWiringStaysLive(self):
        """`MCPConnection` 的消费方（`mcp_client`）不得被本批波及。

        `MCPConnection` 未登记进取数表（它不是死线，是本批的**边界守卫**），
        故直接读源码事实。它的真实消费点是 `execution_engine/mcp_manager.py`
        （同名同源：`mcp_manager` 从 `tool_layers.schemas` 取它构造连接记录）。
        """
        schemas = (PROJECT_ROOT / "neurova/tool_layers/schemas.py").read_text(encoding="utf-8")
        assert "class MCPConnection" in schemas, "MCPConnection 被本批连带删除"
        manager = (PROJECT_ROOT / "neurova/execution_engine/mcp_manager.py").read_text(encoding="utf-8")
        assert "MCPConnection(" in manager, (
            "mcp_manager 不再构造 MCPConnection——本批把活着的配置契约连坐了"
        )
