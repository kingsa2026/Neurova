"""endpoints 模块分层架构守卫（2026-09-16 knowledge/growth 拆分后冻结）。

2026-09-16 两次拆分把单文件多域端点拆为「聚合器 + 叶子模块」
（knowledge.py 1338→聚合器、growth.py 1078→聚合器），其收益完全建立在三条
架构不变量上；本文件把它们钉成可执行契约，防止后续改动把耦合悄悄长回来：

1. **叶子不依赖聚合器** —— 聚合器只是组装点。叶子 import 它会形成反向边
   （循环依赖的前身），并使「聚合器整体替换/重排」的假设失效。
2. **同层零交叉** —— knowledge 的四个叶子之间、growth 的两个 router 之间
   不得互相 import（含函数内懒导入）；共享需求一律下沉共享层。跨层依赖
   只允许指向更底层，不允许同层或反向。
3. **聚合器不承载端点处理函数** —— knowledge.py 是纯聚合器：零模块级函数，
   34 条路由的处理函数全部住在叶子模块。growth.py 是**混合体**（仍保留
   reflection/questions/proactive/motivation/overview 共 13 条未拆域路由），
   故对它只钉「已拆出的 /personality*、/constitution* 路由不得由聚合器提供
   处理函数」这一条可成立的子集；对未拆域路由只要求处理函数归属在已登记的
   模块内（防第三方模块偷偷接管）。

依赖边用 AST 静态扫描（覆盖函数内懒导入与 `importlib.import_module("...")`
字面量），不依赖 import 副作用；处理函数归属用运行时 `__module__` 核对。
另有一条「无模块漏网」检查：同包内名字像本域的模块必须显式分类，避免将来
新增叶子模块时守卫静默失守。
"""
import ast
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_module_layering_0123")

import pytest

import neurova.api.endpoints as endpoints_pkg
from neurova.api.endpoints import growth as growth_aggregator
from neurova.api.endpoints import knowledge as knowledge_aggregator

PKG = "neurova.api.endpoints"
_ENDPOINTS_DIR = Path(endpoints_pkg.__file__).parent


@dataclass(frozen=True)
class DomainSpec:
    """一个域的模块分层声明（由低到高）。"""

    name: str
    aggregator: str
    layers: tuple[tuple[str, ...], ...]
    # 已拆出、必须由叶子承载的路径前缀；None 表示全部路由都必须由叶子承载
    delegated_prefixes: tuple[str, ...] | None
    # 同包内名字匹配本域但**不属于**本域、且允许 import 聚合器的模块（显式登记）
    co_tenants: tuple[str, ...]
    glob_patterns: tuple[str, ...]

    @property
    def layer_members(self) -> set[str]:
        return {m for layer in self.layers for m in layer}


DOMAINS = (
    # knowledge：纯聚合器（34 条路由全部住在叶子），共享层只有 knowledge_common，
    # 四个叶子彼此独立 → 同层零交叉即「叶子之间零交叉」。
    DomainSpec(
        name="knowledge",
        aggregator="knowledge",
        layers=(
            ("knowledge_common",),
            (
                "knowledge_core",
                "knowledge_sharing",
                "knowledge_remote",
                "knowledge_ingestion",
            ),
        ),
        delegated_prefixes=None,
        co_tenants=(
            # 外部消费方：经 knowledge 的兼容 re-export 调 _default_llm_call
            # （这正是 re-export 块存在的理由），非本域成员
            "knowledge_graph_api",
            # 同包另一套端点（Memory↔Knowledge 集成），与本域模块零依赖
            "knowledge_integration",
        ),
        glob_patterns=("knowledge.py", "knowledge_*.py"),
    ),
    # growth：混合聚合器（仍保留 13 条未拆域路由）+ 两个 router 叶子，
    # 共享层为 growth_common，持久层叶子彼此独立且不得反向依赖 router。
    DomainSpec(
        name="growth",
        aggregator="growth",
        layers=(
            ("growth_common", "personality_persistence", "constitution_persistence"),
            ("personality_router", "constitution_router"),
        ),
        delegated_prefixes=("/personality", "/constitution"),
        co_tenants=(),
        glob_patterns=("growth.py", "growth_*.py", "personality_*.py", "constitution_*.py"),
    ),
)

DOMAIN_IDS = tuple(spec.name for spec in DOMAINS)


def _source_path(short_name: str) -> Path:
    path = _ENDPOINTS_DIR / f"{short_name}.py"
    assert path.is_file(), f"声明的模块不存在：{path}（守卫不能对着空气断言）"
    return path


def _edges_from_source(source: str, module_name: str) -> set[str]:
    """静态提取源码里的全部 import 目标，返回绝对点分模块路径集合。

    覆盖四种真实写法（漏掉任何一种，依赖检查就会静默空转）：
      - `import a.b.c`
      - `from a.b import c`   （含函数内懒导入）
      - `from a import b`     —— b 可能是子模块，故对每个别名追加一节候选
                                （`from neurova.api.endpoints import knowledge`
                                是导入聚合器最自然的写法，不追加即盲区）
      - 相对导入（解析成本包内绝对路径）
      - `importlib.import_module("...")` / `__import__("...")` 的字面量实参

    只读调用实参里的字符串，不扫 docstring 与普通字面量——文档里提到兄弟模块
    名不构成依赖边。
    """
    tree = ast.parse(source, filename=module_name)
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入 → 解析成本包内绝对路径
                base = module_name.rsplit(".", node.level)[0]
                target = ".".join(part for part in (base, node.module) if part)
            else:
                target = node.module or ""
            if not target:
                continue
            edges.add(target)
            edges.update(f"{target}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            callee = getattr(func, "attr", None) or getattr(func, "id", None)
            if callee in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    edges.add(arg.value)
    return edges


def _dotted_edges(short_name: str) -> set[str]:
    source = _source_path(short_name).read_text(encoding="utf-8")
    return _edges_from_source(source, f"{PKG}.{short_name}")


def _layer_index(spec: DomainSpec, dotted: str) -> int | None:
    aggregator = f"{PKG}.{spec.aggregator}"
    if dotted == aggregator or dotted.startswith(f"{aggregator}."):
        return len(spec.layers)  # 聚合器视作最顶层
    for index, layer in enumerate(spec.layers):
        if dotted in {f"{PKG}.{m}" for m in layer}:
            return index
    return None


def _domain_targets(spec: DomainSpec) -> set[str]:
    """本域全部已登记模块的绝对路径（含聚合器）。"""
    return {f"{PKG}.{m}" for m in spec.layer_members} | {f"{PKG}.{spec.aggregator}"}


def test_edge_extraction_sees_every_import_form():
    """守卫自检：依赖边的提取能力必须先被证明，否则上面的不变量会静默空转。

    2026-09-16 实锤：初版把 `from x import y` 的绝对导入拼成 `.x.y`（前导点），
    全部跨模块边因此匹配不上本域模块——不变量 2 与 1 的检查是对着空气断言。
    本用例用合成源码把四种写法一次钉死。
    """
    source = '''
import neurova.api.endpoints.knowledge_sharing
from neurova.api.endpoints.knowledge_common import get_agent
from neurova.api.endpoints import knowledge, knowledge_remote
from . import knowledge_ingestion


def _lazy():
    from neurova.api.endpoints.knowledge import router as _agg
    import importlib
    importlib.import_module("neurova.api.endpoints.constitution_router")
'''
    edges = _edges_from_source(source, f"{PKG}.knowledge_core")
    for expected in (
        f"{PKG}.knowledge_sharing",
        f"{PKG}.knowledge_common",
        f"{PKG}.knowledge",
        f"{PKG}.knowledge_remote",
        f"{PKG}.knowledge_ingestion",
        f"{PKG}.constitution_router",
    ):
        assert expected in edges, f"提取器漏掉了 {expected}：{sorted(edges)}"
    # 前导点伪路径必须不存在（初版 bug 的形态）
    assert not [e for e in edges if e.startswith(".")], sorted(edges)
    # 文档里的模块名不算依赖边
    docstring = '"""文档里提及 knowledge_sharing 与 knowledge_remote 不构成依赖"""'
    assert _edges_from_source(docstring, f"{PKG}.knowledge_core") == set()


@pytest.mark.parametrize("spec", DOMAINS, ids=DOMAIN_IDS)
def test_no_module_escapes_the_spec(spec: DomainSpec):
    """同包内名字像本域的模块必须显式分类（聚合器/分层成员/已登记同租户）。

    守卫的失效方式是静默的：将来新增一个 knowledge_xxx.py 而忘了登记，上面
    三条不变量对它就完全不生效。此检查把「漏网」变成红灯。
    """
    matched: set[str] = set()
    for pattern in spec.glob_patterns:
        matched.update(p.stem for p in _ENDPOINTS_DIR.glob(pattern))
    classified = spec.layer_members | {spec.aggregator} | set(spec.co_tenants)
    assert matched == classified, (
        f"{spec.name} 域模块分类不全：未登记 {sorted(matched - classified)}、"
        f"声明了不存在的 {sorted(classified - matched)}"
    )


@pytest.mark.parametrize("spec", DOMAINS, ids=DOMAIN_IDS)
def test_leaves_never_depend_on_aggregator(spec: DomainSpec):
    """不变量 1：叶子（含共享层）不得 import 聚合器——反向边即循环依赖前身。"""
    aggregator = f"{PKG}.{spec.aggregator}"
    for member in sorted(spec.layer_members):
        offending = {
            edge
            for edge in _dotted_edges(member)
            if edge == aggregator or edge.startswith(f"{aggregator}.")
        }
        assert not offending, (
            f"{member} import 了聚合器 {aggregator}（{sorted(offending)}）："
            "拆分后的依赖必须单向 —— 聚合器 ─▶ 叶子"
        )


@pytest.mark.parametrize("spec", DOMAINS, ids=DOMAIN_IDS)
def test_dependencies_only_point_downward_no_same_layer_coupling(spec: DomainSpec):
    """不变量 2：跨层依赖只许指向更底层；同层模块之间零交叉。

    knowledge：四个叶子互为同层 → 即「叶子间零交叉」。
    growth：两个 router 同层 → 即「router 之间零交叉」，且持久层不得反向
    依赖 router（持久层在更低层）。
    """
    edges_by_module = {member: _dotted_edges(member) for member in spec.layer_members}
    violations: list[str] = []
    for member, edges in edges_by_module.items():
        own_layer = _layer_index(spec, f"{PKG}.{member}")
        assert own_layer is not None, f"{member} 未在自己的分层声明里"
        for edge in edges:
            if edge == f"{PKG}.{member}":  # 函数内自我重导入不算依赖边
                continue
            target_layer = _layer_index(spec, edge)
            if target_layer is None:
                continue  # 非本域模块（基础设施/其他域）不在本守卫范围
            if target_layer >= own_layer:
                violations.append(
                    f"{member}(L{own_layer}) → {edge}(L{target_layer})"
                )
    assert not violations, (
        f"{spec.name} 域存在同层交叉或反向依赖：{violations}；"
        "共享需求请下沉到共享层（knowledge_common / growth_common）"
    )


def _routes(router):
    return [
        (r.path, sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}), r.endpoint)
        for r in router.routes
        if getattr(r, "methods", None) and not r.path.startswith(("/openapi", "/docs"))
    ]


def _module_level_function_names(short_name: str) -> list[str]:
    tree = ast.parse(_source_path(short_name).read_text(encoding="utf-8"), filename=str(short_name))
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_knowledge_aggregator_defines_no_functions_at_all():
    """不变量 3（knowledge）：纯聚合器零模块级函数——挂载 + re-export，无逻辑。"""
    assert _module_level_function_names("knowledge") == [], (
        "knowledge.py 出现模块级函数：聚合器不得承载业务逻辑或处理函数，"
        "处理函数一律住在叶子模块"
    )


@pytest.mark.parametrize("spec", DOMAINS, ids=DOMAIN_IDS)
def test_route_handlers_live_in_registered_modules(spec: DomainSpec):
    """不变量 3：处理函数归属核对（运行时 __module__，非静态猜测）。

    - 任何路由的处理函数必须住在已登记模块内（防第三方模块接管路由）；
    - knowledge（delegated_prefixes=None）：全部 34 条路由都不得由聚合器承载；
    - growth：/personality*、/constitution* 不得由聚合器承载（未拆域路由仍由
      聚合器承载，故不作全量约束——这是该文件当前的真实形态）。
    """
    module = globals()[f"{spec.name}_aggregator"]
    declared = _domain_targets(spec)
    checked = 0
    for path, methods, endpoint in _routes(module.router):
        owner = endpoint.__module__
        assert owner in declared, (
            f"{spec.name} 路由 {methods} {path} 的处理函数住在未登记模块 {owner}"
        )
        delegated = (
            spec.delegated_prefixes is None or path.startswith(spec.delegated_prefixes)
        )
        if delegated:
            assert owner != f"{PKG}.{spec.aggregator}", (
                f"{spec.name} 路由 {methods} {path} 的处理函数仍定义在聚合器 "
                f"{spec.aggregator}.py —— 该路由应交给叶子模块"
            )
        checked += 1
    assert checked, f"{spec.name} 聚合器未暴露任何路由（守卫失效，检查挂载）"
