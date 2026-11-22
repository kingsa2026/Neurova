# -*- coding: utf-8 -*-
"""neurova-ontology CLI 薄壳（升级卡 U11）：本体域四命令的命令行入口。

**薄壳纪律（修复教义第 6/7 条）**：本模块零业务逻辑复制——每个子命令只做
「解析参数 → 转交既有处理函数 → rich 呈现」：

- `terms list|get <id>` → `OntologyTermRegistry.terms()/term()`（term_registry 读面）；
- `export --format <fmt>` → export/ 既有导出函数（turtle/jsonld/owl/shacl/prov/
  graphml/gexf/cypher/csv 九格式闭集，以 export/ 实际函数为准）；
- `sparql "<SELECT ...>"` → `sparql_query.runSparqlQuery`（只读投影查询；
  写形被拒的错误如实透出，不吞不改写）；
- `validate [--subject <key>]` → `shacl_runtime.validateShapesRuntime`（dry-run
  只读；mode 显式传参，不走环境档）。

store 打开方式与既有脚本同源：显式 `--db` 原样承载；缺省走
`get_knowledge_fact_store()`（DEFAULT_FACT_DB ← dataPath("knowledge")，
随 `NEUROVA_DATA_DIR` 注入）。与既有 MCP 面（mcp_ontology_server.py）的关系
（教义第 7 条先比后合）：MCP 服务 Agent 的远程工具调用（ASGI 挂 /v1/mcp），
本 CLI 服务本地运维/开发查询；两者都只转交同一批处理函数，互不替代、
无第二实现，故接通共存而非退役。

用法示例::

    neurova-ontology terms list
    neurova-ontology terms get is_a
    neurova-ontology export --format turtle --out onto.ttl
    neurova-ontology sparql "SELECT ?s ?o WHERE { ?s kbg:linked ?o }"
    neurova-ontology validate --subject <subject_key> --mode shadow
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.text import Text

from neurova.core.logger import get_logger
from neurova.knowledge.ontology.shacl_runtime import _VALID_MODES as SHACL_MODES

logger = get_logger(__name__)

console = Console()
errConsole = Console(stderr=True)

#: 导出格式闭集——每个格式一个转交目标（_dispatchExport），与 export/ 实际函数一一对应
EXPORT_FORMATS = ("turtle", "jsonld", "owl", "shacl", "prov",
                  "graphml", "gexf", "cypher", "csv")


# ── 装配（与既有脚本同源，不另造路径口径）────────────────────────────


def openStore(dbPath: Optional[str] = None) -> Tuple[Any, bool]:
    """打开事实底座库，返回 (store, 是否本函数新建)。

    显式 `--db` 原样承载（测试隔离与多库场景用，与既有测试夹具同一形态）；
    缺省走生产单例 `get_knowledge_fact_store()`——其默认路径即
    `NEUROVA_DATA_DIR/knowledge/` 惯例。新建的实例由调用方负责关闭；
    单例不关（进程级共享）。
    """
    from neurova.knowledge.foundation.knowledge_facts import (
        KnowledgeFactStore,
        get_knowledge_fact_store,
    )

    if dbPath:
        return KnowledgeFactStore(dbPath), True
    return get_knowledge_fact_store(), False


# ── 转交目标（每格式一个既有函数，本表即格式闭集的落点）──────────────


def _dispatchExport(store: Any, tenantId: str, agentId: str, fmt: str) -> str:
    """格式 → 既有导出函数的唯一下发；agentId 缺省口径与 REST 导出端点一致。"""
    if fmt == "turtle":
        from neurova.knowledge.ontology.turtle import serializeAll

        return serializeAll(store, tenantId=tenantId, agentId=agentId or None)
    if fmt == "jsonld":
        from neurova.knowledge.ontology.export.jsonld import exportJsonLd

        return exportJsonLd(store, tenantId, agentId or "")
    if fmt == "owl":
        from neurova.knowledge.ontology.export.owl import exportOwlAxioms

        return exportOwlAxioms(store, tenantId)
    if fmt == "shacl":
        from neurova.knowledge.ontology.export.shacl import exportShaclShapes

        return exportShaclShapes(store, tenantId)
    if fmt == "prov":
        from neurova.knowledge.ontology.export.prov import exportProv

        return exportProv(store, tenantId)
    if fmt == "graphml":
        from neurova.knowledge.ontology.export.graph_exchange import exportGraphML

        return exportGraphML(store, tenantId, agentId or "")
    if fmt == "gexf":
        from neurova.knowledge.ontology.export.graph_exchange import exportGexf

        return exportGexf(store, tenantId, agentId or "")
    if fmt == "cypher":
        from neurova.knowledge.ontology.export.graph_exchange import exportCypher

        return exportCypher(store, tenantId, agentId or "")
    if fmt == "csv":
        from neurova.knowledge.ontology.export.graph_exchange import exportCsv

        return exportCsv(store, tenantId, agentId or "")
    raise ValueError("未知导出格式 %r（有效值: %s）" % (fmt, "/".join(EXPORT_FORMATS)))


# ── 命令：terms ─────────────────────────────────────────────────────


def _cmdTerms(args: argparse.Namespace) -> int:
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store, owned = openStore(args.db)
    try:
        registry = OntologyTermRegistry(store)
        if args.termCommand == "get":
            term = registry.term(args.termId, tenantId=args.tenant)
            if term is None:
                errConsole.print(Text("✕ 术语未登记: %s" % args.termId, style="bold red"))
                return 1
            _printTermDetail(term)
        else:
            _printTermsTable(registry.terms(tenantId=args.tenant))
    finally:
        if owned:
            store.close()
    return 0


def _printTermsTable(terms: List[dict]) -> None:
    table = Table(title="本体术语（共 %d 条）" % len(terms), header_style="bold cyan")
    table.add_column("术语 ID", overflow="fold")
    table.add_column("类别")
    table.add_column("标签", overflow="fold")
    table.add_column("父类", overflow="fold")
    table.add_column("版本")
    table.add_column("模块")
    for term in terms:
        table.add_row(
            str(term.get("term_id", "-")),
            str(term.get("kind", "-")),
            str(term.get("label", "")) or "-",
            str(term.get("parent_term_id", "")) or "-",
            str(term.get("version", "-")),
            str(term.get("module", "")) or "-",
        )
    console.print(table)


def _printTermDetail(term: dict) -> None:
    table = Table(title="术语 %s" % term.get("term_id", "?"), header_style="bold cyan",
                  show_header=False)
    table.add_column("字段", style="bold cyan")
    table.add_column("值", overflow="fold")
    for key in sorted(term.keys()):
        value = term[key]
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = "" if value is None else str(value)
        table.add_row(key, rendered or "-")
    console.print(table)


# ── 命令：export ────────────────────────────────────────────────────


def _cmdExport(args: argparse.Namespace) -> int:
    store, owned = openStore(args.db)
    try:
        text = _dispatchExport(store, args.tenant, args.agent, args.format)
    except ValueError as exc:  # 闭集外的格式等参数错误：如实点名
        errConsole.print(Text("✕ %s" % exc, style="bold red"))
        return 1
    finally:
        if owned:
            store.close()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        console.print("[green]✓[/green] 已导出 %s → %s（%d 字符）"
                      % (args.format, args.out, len(text)))
    else:
        # 文档内容含 Turtle/JSON/CSV 原文，走裸输出通道不经 rich 标记解析
        print(text)
    return 0


# ── 命令：sparql ────────────────────────────────────────────────────


def _cmdSparql(args: argparse.Namespace) -> int:
    from neurova.knowledge.ontology.sparql_query import (
        SparqlNotSupported,
        runSparqlQuery,
    )

    store, owned = openStore(args.db)
    try:
        result = runSparqlQuery(store, args.query, agentId=args.agent,
                                tenantId=args.tenant)
    except (ValueError, SparqlNotSupported) as exc:
        # 空查/写形/依赖缺位：处理函数的拒绝原因如实透出（诚实形态，不吞不改写）
        errConsole.print(Text("✕ SPARQL 查询被拒: %s" % exc, style="bold red"))
        return 1
    finally:
        if owned:
            store.close()
    _printSparqlResult(result)
    return 0


def _printSparqlResult(result: dict) -> None:
    variables = list(result.get("variables") or [])
    rows = list(result.get("rows") or [])
    table = Table(title="SPARQL 查询结果（%d 行）" % result.get("row_count", len(rows)),
                  header_style="bold cyan")
    for var in variables:
        table.add_column(var, overflow="fold")
    for row in rows:
        table.add_row(*[str(row.get(var, "")) for var in variables])
    console.print(table)
    if result.get("truncated"):
        console.print("[yellow]! 结果超过行数上限，已截断[/yellow]")


# ── 命令：validate ──────────────────────────────────────────────────


def _cmdValidate(args: argparse.Namespace) -> int:
    from neurova.knowledge.ontology.shacl_runtime import validateShapesRuntime

    store, owned = openStore(args.db)
    try:
        report = validateShapesRuntime(
            store, args.tenant, agentId=args.agent or None,
            mode=args.mode,  # 显式 mode：CLI 档位由参数决定，不读环境
            subjectKeys=[args.subject] if args.subject else None)
    finally:
        if owned:
            store.close()
    if not report.get("supported"):
        errConsole.print(Text("✕ SHACL 校验不可用: %s" % report.get("reason", "未知原因"),
                              style="bold red"))
        return 1
    _printValidateReport(report)
    return 0


def _printValidateReport(report: dict) -> None:
    console.print("SHACL 校验（mode=%s）：conforms=%s，违规 %d 条"
                  % (report.get("mode", "-"),
                     "True" if report.get("conforms") else "False",
                     len(report.get("violations") or [])))
    if report.get("note"):
        console.print("[yellow]○ %s[/yellow]" % report["note"])
    violations = report.get("violations") or []
    if violations:
        table = Table(title="违规清单", header_style="bold yellow")
        table.add_column("严重级")
        table.add_column("focus 节点", overflow="fold")
        table.add_column("路径", overflow="fold")
        table.add_column("值", overflow="fold")
        table.add_column("消息", overflow="fold")
        table.add_column("组件")
        for item in violations:
            table.add_row(
                str(item.get("severity", "-")),
                str(item.get("focusNode", "")) or "-",
                str(item.get("path", "")) or "-",
                str(item.get("value", "")) or "-",
                str(item.get("message", "")) or "-",
                str(item.get("component", "")) or "-",
            )
        console.print(table)


# ── 参数装配与入口 ──────────────────────────────────────────────────


def _dispatch(args: argparse.Namespace) -> int:
    return {
        "terms": _cmdTerms,
        "export": _cmdExport,
        "sparql": _cmdSparql,
        "validate": _cmdValidate,
    }[args.command](args)


def buildParser() -> argparse.ArgumentParser:
    # 公共参数组（parents 复用）：--db/--tenant/--agent 在主命令或子命令后均可给
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=None,
                        help="事实底座库路径（缺省走 NEUROVA_DATA_DIR 惯例的生产路径）")
    common.add_argument("--tenant", default="default", help="租户 ID（默认 default）")
    common.add_argument("--agent", default="default", help="agent ID（默认 default）")

    parser = argparse.ArgumentParser(
        prog="neurova-ontology", parents=[common],
        description="Neurova 本体域命令行：术语查询 / 互操作导出 / SPARQL 只读查询 / SHACL 校验")
    sub = parser.add_subparsers(dest="command", required=True)

    pTerms = sub.add_parser("terms", parents=[common],
                            help="术语查询（转交 term_registry 读面）")
    termsSub = pTerms.add_subparsers(dest="termCommand", required=True)
    termsSub.add_parser("list", parents=[common], help="列出本租户全部术语")
    pGet = termsSub.add_parser("get", parents=[common], help="查单个术语的完整声明")
    pGet.add_argument("termId", help="术语 ID")

    pExport = sub.add_parser("export", parents=[common],
                             help="互操作导出（转交 export/ 既有函数）")
    pExport.add_argument("--format", required=True, choices=EXPORT_FORMATS,
                         help="导出格式闭集（以 export/ 实际支持为准）")
    pExport.add_argument("--out", default=None,
                         help="输出文件路径（缺省打印到 stdout）")

    pSparql = sub.add_parser("sparql", parents=[common],
                             help="SPARQL 只读查询（写形不支持）")
    pSparql.add_argument("query", help="SELECT/ASK 查询文本（kbg: 前缀自动补齐）")

    pValidate = sub.add_parser("validate", parents=[common],
                               help="SHACL 运行时校验 dry-run（只读）")
    pValidate.add_argument("--subject", default=None,
                           help="主体 key（缺省全库投影）")
    pValidate.add_argument("--mode", default="shadow", choices=SHACL_MODES,
                           help="运行档位（显式传参，不走环境档；默认 shadow）")

    parser.set_defaults(func=_dispatch)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口（console_scripts 约定：返回值即退出码）。"""
    parser = buildParser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # 诚实形态：点名失败原因后非零退出，不吞不改写
        logger.exception("neurova-ontology %s 执行失败", args.command)
        errConsole.print(Text("✕ %s: %s" % (type(exc).__name__, exc), style="bold red"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
