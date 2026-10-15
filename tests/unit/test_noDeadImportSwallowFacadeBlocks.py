"""门面里的「空转 try / 假降级」清零（工单 2026-10-14 批 42，§6-200）。

现读实状（建档时对全仓 **3390** 个跟踪 .py 逐个 AST 数出来，语法解析失败 0 处）：

- 「try 体内只有 `pass`（或一句文档串）却 `except ImportError` 并打'模块未可用'日志」的纯空转段
  共 **35 段**，分布在 **9** 个文件：`neurova/skills/__init__.py` 13、
  `neurova/llm/providers/__init__.py` 11、`neurova/cognitive_layers/memory_layer/__init__.py` 4、
  `neurova/admin/__init__.py` 2，`neurova/auth/__init__.py`、`neurova/channels/xiaoyi.py`、
  `neurova/collaboration/__init__.py`、`neurova/recovery/__init__.py`、`neurova/tts/__init__.py` 各 1。
  体里什么都不执行 ⇒ 永远不会抛 ImportError ⇒ 那句 debug/warning 从不出现，而"模块未可用"
  成了一条**从不成立的自陈**。（§6-194 记的是「其余八段」——那是数错了，现值十三段。）
- `neurova/skills/__init__.py` 把 models / hub_client / skill_service / neurova.skill_system 四条
  **first-party** 导入包在 try 里，except 分支把 **48 个名字赋成 None**。现测四者都能导入，
  且顶层除 `__future__` 外没有第三方依赖 ⇒ 那条兜底今天不可达；它真可达的那天，
  `agent_core.py:862/1258/1517` 的 `from neurova.skills import create_default_skills` 拿到的是
  `None` 并在下一行调用 ⇒ TypeError。按教义第 1 条这就是"在下游补 None 兜底"，不是降级保护。
- 同文件档头自陈的三个模块/目录不存在：`pool/`、`pool_service.py`、`experience_caller.py`
  （`SkillPoolService` / `ExperienceCaller` 两个类名全仓零定义）。注释自陈不等于事实（§6-182 同族）。
- 顺带量出的一条同名抢绑：门面先从 `models` 导 `SkillSource`（LOCAL/MARKETPLACE/BUILTIN），
  再从 `hub_client` 导一个**同名但不同成员**的 `SkillSource`（GITHUB/CLAWHUB/LOBEHUB/MODELSCOPE/LOCAL），
  后者覆盖前者——现测 `neurova.skills.SkillSource is hub_client 那份`。按书写顺序决定给出去哪份，
  就是第二条通道（形态集"按符号局部名认通道"同族）。

不在本批范围（逐文件要判"真可选依赖 vs first-party"，登记待裁，见 §6-200）：
其余 39 个文件里 144 个 `except ImportError` 分支内的 `X = None` 占位符。

**批 46（§6-210）之后，本档三格的方向反过来了**（改判记录，不是放宽）：那批把技能门面从 47 个
再导出收成"只挂确实有人经门面取用的 2 个名字"（现读 `create_default_skills`/`get_skill_registry`，
出处 `agent_core.py` 与 `api/endpoints/skill.py`），并把 `hub_client` 那份同名 `SkillSource` 并进
`models` 那一份。于是本档原先当成**成功**来断言的那些输入——"四条 first-party 必须顶层直连"、
"门面上必须能拿到 `SkillSource` 且等于 models 那份"、"这九个符号必须非 None"——在同一份代码上
含义变成**缺陷**：它们要求的正是"门面再抄一份词汇表"这件事本身。处置不是删格（删了就不再有
人盯这条门被拉穿），而是把方向写成会自己复活的反向断言：**这些名字再回到门面上即红**。
"门面只准挂被经门面取用的名字"这条契约的判据在 `tests/unit/skills/test_skillsFacadeAndSourceEnumAreSingleSourced.py`
（同一契约只许一处判，教义第 6 条），本档只负责"空转 try / None 占位符 / 同名抢绑"这一族形状。
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

SKILLS_INIT = "neurova/skills/__init__.py"
FACADE_FIRST_PARTY = ("neurova.skills.models", "neurova.skills.hub_client",
                      "neurova.skills.skill_service", "neurova.skill_system")

#: 批 46（§6-210）从技能门面退役的再导出目标。**反向钉**用：它们再出现在门面顶层绑定里（AST 级）
#: 或真导入后的包属性上（运行时级）即红。旧判据把"这些名字必须在门面上"当成功来断，而批 46 之后
#: 同一输入的含义变成缺陷——那正是"门面再抄一份词汇表"这件事本身；只删不补就等于把这条门从
#: 验收面上擦掉（形态集第 196 条）。
FACADE_RETIRED_NAMES = ("SkillInfo", "Skill", "SkillSource", "SkillHubClient", "RemoteSkill",
                        "SkillService", "SkillRegistry")


def _trackedPyFiles() -> list:
    """扫描面＝已跟踪的 .py（走 `ast_scan` 的单点；这里不抄解码与退出码口径）。"""
    return ast_scan.trackedPyPaths()


def _importErrorHandlers(node: ast.Try) -> list:
    out = []
    for handler in node.handlers or []:
        t = handler.type
        if isinstance(t, ast.Name) and t.id in ("ImportError", "ModuleNotFoundError"):
            out.append(handler)
        elif isinstance(t, ast.Tuple) and any(getattr(e, "id", "") in ("ImportError", "ModuleNotFoundError")
                                              for e in t.elts):
            out.append(handler)
    return out


def deadSwallowBlocks(source: str, filename: str):
    """找出「try 体是惰性的（只有 pass 或文档串）却按 ImportError 兜底」的段。

    惰性体不可能抛任何异常，所以整段（含 handler 里的日志与降级赋值）都是不可达码。
    解析失败**不静默跳过**——按形态集口径，"跳过编译失败"这条兜底本身必须被报出来。
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [("无法解析，扫描面未覆盖该文件", 0, str(exc))]
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        inert = all(isinstance(st, ast.Pass)
                    or (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                        and isinstance(st.value.value, str))
                    for st in node.body)
        handlers = _importErrorHandlers(node)
        if inert and handlers:
            hits.append(("惰性 try 体配 except ImportError", node.lineno, filename))
    return hits


def nonePlaceholders(source: str, filename: str):
    """except ImportError 分支里把名字赋成 None 的那些行。"""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [(0, str(exc))]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in _importErrorHandlers(node):
            for st in handler.body:
                if (isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant)
                        and st.value.value is None):
                    for tgt in st.targets:
                        if isinstance(tgt, ast.Name):
                            out.append((st.lineno, tgt.id))
    return out


class TestNoDeadImportSwallowBlocks:
    def testRepoWideHasNoInertTryUnderExceptImportError(self):
        offenders = []
        for rel in _trackedPyFiles():
            text = io.open(REPO_ROOT / rel, encoding="utf-8", errors="replace").read()
            offenders += deadSwallowBlocks(text, rel.replace("\\", "/"))
        assert not offenders, (
            "存在「惰性 try 体 + except ImportError」的纯空转段：那行日志永远不会打印，"
            f"被点名的『模块未可用』是从不成立的自陈。命中 {len(offenders)} 段：{offenders[:12]}")

    def testScanSetCoversTheRepoAndDetectorSeesTheShape(self):
        """地板格＋反空转格：扫描面没收窄、探测器认得这一形——否则上一条绿得没道理。"""
        files = _trackedPyFiles()
        assert len(files) >= 3000, f"扫描集合只剩 {len(files)} 个 .py，口径被收窄了"

        planted = deadSwallowBlocks(
            "try:\n    pass\nexcept ImportError as e:\n    log.debug('x 未可用: %s', e)\n", "<plant>")
        assert len(planted) == 1, f"探测器漏认惰性 try：{planted}"
        # 控制样本：体内真会执行东西的 fail-soft 不算空转，不许误伤
        kept = deadSwallowBlocks(
            "try:\n    import optional_third_party as _m\nexcept ImportError:\n    _m = None\n",
            "<control>")
        assert not kept, f"探测器把真 fail-soft 也误伤了：{kept}"
        got = nonePlaceholders("try:\n    import x\nexcept ImportError:\n    x = None\n", "<p>")
        assert [n for _, n in got] == ["x"], f"None 占位符探测器没牙：{got}"

    def testSkillsFacadeHasNoNonePlaceholders(self):
        text = io.open(REPO_ROOT / SKILLS_INIT, encoding="utf-8").read()
        placeholders = nonePlaceholders(text, SKILLS_INIT)
        assert not placeholders, (
            "门面把 first-party 导入的失败兜成 None 占位符，共 "
            f"{len(placeholders)} 个：{[n for _, n in placeholders][:10]}——"
            "可达那天调用方拿到 None 再调用即 TypeError，这就是替不可能发生的场景兜底")

    def testSkillsFacadeImportsAreNotSwallowed(self):
        """门面的 first-party 导入必须在顶层直接执行；而批 46 退役过的那批名字不得回来（§6-238）。"""
        tree = ast.parse(io.open(REPO_ROOT / SKILLS_INIT, encoding="utf-8").read())
        swallowed = []
        for node in tree.body:
            if not isinstance(node, ast.Try):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.ImportFrom) and inner.module in FACADE_FIRST_PARTY):
                    swallowed.append((inner.lineno, inner.module))
        assert not swallowed, (
            f"这些导入仍被 try 包住：{swallowed}——包着就会把真故障吞成上面的 None 占位符")

        bound = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound[alias.asname or alias.name] = node.module
        back = sorted(set(bound) & set(FACADE_RETIRED_NAMES))
        assert not back, (
            "这些名字又被导回技能门面：" + ", ".join(f"{n}←{bound[n]}" for n in back)
            + "\n批 46（§6-210）已裁定门面只挂『确实有人经门面取用』的名字，零消费者的再导出就是"
              "同一词汇表的第二份抄本；这一格钉的是**别再退回去**，不是要求它们存在。")

    def testFacadeDocstringNamesExistingModules(self):
        """档头的结构清单（`- xxx.py` / `- xxx/` 那些行）点名的每一项都必须真存在。

        口径取"清单行"而不是全文：清单是这份文档对包结构的自陈，读它会去找那个文件；
        正文里顺带提到的别处文件名属叙述，不由这条管（同一条判据在全文口径上会假红，
        本批第一版就被自己那句提到 `agent_core.py` 的说明绊过一次）。
        """
        import re

        def inventoryLies(doc: str, pkgDir: Path) -> list:
            missing = []
            for line in doc.splitlines():
                item = re.match(r"^\s*-\s+([A-Za-z_][A-Za-z0-9_]*(?:\.py|/))", line.strip())
                if not item:
                    continue
                name = item.group(1)
                target = pkgDir / name.rstrip("/")
                if not (target.is_dir() if name.endswith("/") else target.is_file()):
                    missing.append(name)
            return missing

        text = io.open(REPO_ROOT / SKILLS_INIT, encoding="utf-8").read()
        doc = ast.get_docstring(ast.parse(text)) or ""
        pkgDir = REPO_ROOT / "neurova" / "skills"
        missing = inventoryLies(doc, pkgDir)
        assert not missing, (
            f"档头清单点了不存在的模块/目录：{missing}——读文档的人会去改一个不在这儿的东西"
            "（§6-182 同族：自陈不等于事实）")

        planted = inventoryLies("- models.py: ok\n- pool_service.py: 公共池服务\n- nope/ : 目录\n", pkgDir)
        assert planted == ["pool_service.py", "nope/"], f"清单探测器没牙：{planted}"


    def testFacadeBindsEachNameToExactlyOneDefinition(self):
        """门面上同一个名字不得被两条不同来源的 import 先后绑两次；`SkillSource` 不得再经门面给出。

        建档实状（批 42）：门面先从 `models` 导 `SkillSource`（LOCAL/MARKETPLACE/BUILTIN），后从
        `hub_client` 又导一个同名而**不同成员**的 `SkillSource`（GITHUB/CLAWHUB/…），后者盖掉前者——
        给出去哪份取决于书写顺序。批 46（§6-210）按"比-取-接-退"把两份并成一份：`hub_client` 现在
        用的就是 `models` 那份（本格下方现算 `is` 为真），而门面**根本不再挂这个名字**——消费者
        直取 `neurova.skills.models`（活体第 3 项现数）。⇒ 旧的那半句 `facade.SkillSource is
        models.SkillSource` 要求的是"门面上得有它"，方向已由本格反成"**有它就红**"。
        """
        tree = ast.parse(io.open(REPO_ROOT / SKILLS_INIT, encoding="utf-8").read())
        seen = {}
        dupes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                origin = f"{node.module}:{alias.name}"
                if bound in seen and seen[bound] != origin:
                    dupes.append((bound, seen[bound], origin))
                else:
                    seen.setdefault(bound, origin)
        assert not dupes, f"门面里同名被两处定义抢绑：{dupes}——给出去的是哪份取决于书写顺序"

        import neurova.skills as facade

        assert not hasattr(facade, "SkillSource"), (
            "`SkillSource` 又能在门面上取到了——批 46 已把它并成 `neurova.skills.models` 单源，"
            "经门面拿它就是第二条通道（要它的人直取 models）")

        from neurova.skills import hub_client as hub_mod, models as models_mod

        assert hub_mod.SkillSource is models_mod.SkillSource, (
            "合并掉的那份 `SkillSource` 又被另写了一遍——两份同名枚举的成员集不同，"
            "按 §6-210 只许留 `models` 这一份")


class TestFacadeExportsAreReal:
    def testKeyFacadeSymbolsAreNotPlaceholders(self):
        """门面上不许存在值为 None 的公开绑定，且 `__all__` 声明过的名字必须真绑得上。

        本档的主题是"假降级"，所以这一格钉的是**形状**而不是名字清单：批 42 之前门面把 48 个名字
        赋成 None，调用方拿到 None 再调用即 TypeError。旧版这里钉的是"这九个符号必须非 None"，
        而批 46 之后那九个已不在门面上——按名字清单写就会把"已退役"读成"是占位符"，红得没道理；
        改成形状扫描后两件事都还在：谁再往门面上放 None，以及谁在 `__all__` 里声明了却没绑上
        （后者让 `from neurova.skills import *` 当场 AttributeError，同 §6-200 那族"自陈不等于事实"）。
        """
        import neurova.skills as facade

        declared = list(getattr(facade, "__all__", []))
        assert declared, "门面没有 __all__——声明面无从比对，先确认这一格还在守什么"
        unbound = [name for name in declared if not hasattr(facade, name)]
        assert not unbound, f"__all__ 声明了却根本没绑定的名字：{unbound}（`import *` 会 AttributeError）"
        placeholders = [name for name in vars(facade)
                        if not name.startswith("_") and vars(facade)[name] is None]
        assert not placeholders, f"门面上有 None 占位符：{placeholders}——被包回 try/except 的那一形就长这样"
