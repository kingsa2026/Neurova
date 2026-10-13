# -*- coding: utf-8 -*-
"""A9 memory_layer 换代残留：四件已退役，两件按需人裁留在案上（§6-113；§9 序 5 复算）。

台账原判（§3-A9）「`memory_layer/` 换代残留 ≈2460 行，判定：删」。本轮复算改了两处：
① **体量不对**——A9 点名的六个文件实为 1850 行，凑到 2460 得把未点名的 `explainability.py`(646)
   算进来；② **替代说法有两处不实**——见下面 `PENDING` 那两件的说明。所以"整批删"不成立，
   本批只删**四件**（AST 复算：生产与测试消费者**都是 0**，删它们带不走任何覆盖）：

| 退役件 | 行数 | 为什么是残留（不是"没接线的可用能力"） |
|---|---|---|
| `search_mixin.py` | 346 | 六个检索入口（`:87/:104/:167/:189/:210/:231`）**全部硬返 `[]`**，RRF 只是对两张空表融合；现役搜索走 `manager.py:1939 search_memories` / `:1339 recall` |
| `dream_mixin.py` | 257 | 梦境日志现役在 `sleep.py:205 _dream_logs`（`:199` 还记着"曾只增不减"的资源修复），REST 面在 `api/endpoints/sleep.py` |
| `explainability_storage_mixin.py` | 294 | 被 `explainability.py` 超集覆盖，而两者**都无人装配**；在役的是 `manager.py:4006 _ensure_explainability_module` → `modules/explainability_module.py:52`（扁平记录形态） |
| `modules/storage_module.py` | 206 | "backend 未注入即 warning + 返 None"的静默失败门面（违教义第 2 条）；在役存储走 `MemoryStorage` |

**两件按需人裁留下，并由本格钉住"未裁不许顺手删"**（这是判据里少见的"反向存在断言"，
理由写在下面）：
- `relation_mixin.py`(400)——`graph_density`/`most_connected`(`:335-385`) 全仓唯一实装，
  现役 `relation_module.py` 只到 depth-1 且 `:111` 用 `{src}_{type}_{tgt}` 复合键去重，
  与 mixin 的 uuid4 多边语义**不等价**；
- `forgetting_recovery_storage_mixin.py`(347)——归档/恢复主体被 `manager.py:4057/4075` 实质
  覆盖，但 `cleanup_old_archived:300`（30 天过期清理）与 `get_forgetting_statistics:261/297`
  （recovery_rate）**全仓唯一**；台账把它当"已有替代"的那格是错的——
  `modules/forgetting_recovery_module.py` 是间隔复习，不同功能。
裁下来之前不许删：这两件一旦被静默删除，`graph_density` / `recovery_rate` 这类
"看着像统计、其实是唯一实装"的格子会无声消失，而本仓没有任何测试钉它们。

与另两路复算的边界：`shared_core/plan_orchestrator.py`(453) 与 `core/config_manager.py`(118)
也各自复算过，但前者属序 5 的另一般（批 D）、后者挂着 4 份真行为单测要先做取长补短（批 E），
**都不在本批射程**。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import pytest

REPO = Path(__file__).resolve().parents[3]
LAYER = REPO / "neurova" / "cognitive_layers" / "memory_layer"
PKG_ROOT = REPO / "neurova"
TESTS_ROOT = REPO / "tests"
NS = "neurova.cognitive_layers.memory_layer"

#: 本批已退役（不许再被引用，也不许回到包树）
RETIRED = {
    f"{NS}.search_mixin": "search_mixin.py",
    f"{NS}.dream_mixin": "dream_mixin.py",
    f"{NS}.explainability_storage_mixin": "explainability_storage_mixin.py",
    f"{NS}.modules.storage_module": "modules/storage_module.py",
}
#: 需人裁、暂未退役——本批用"仍在位 + 仍零消费者"两格把它们钉住
PENDING = {
    f"{NS}.relation_mixin": "relation_mixin.py",
    f"{NS}.forgetting_recovery_storage_mixin": "forgetting_recovery_storage_mixin.py",
}

pytestmark = pytest.mark.timeout(120)


def _importedNames(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                out.append(node.module)
                out += [f"{node.module}.{a.name}" for a in node.names]
            elif node.level and node.module:
                # 包内相对导入（`from . import search_mixin` 形态）也算引用
                out.append(f"__REL__.{node.module}")
    return out


def _hits(root: Path, names: dict) -> list[str]:
    """子树里仍引用这批 mixin 的文件清单。

    取数走 `tests/ast_scan` 的共享解析预算（`sourceRefsUnder` + 文本预筛），
    不私有 `rglob + ast.parse`——后者把判据成本绑在代码总量上
    （`tests/unit/test_ci_ast_scan_budget_guard.py` 判红的正是这处）。
    预筛词取**模块末段**（`search_mixin` 等），是判据的**充分条件**：无论绝对
    还是相对 import，真引用它的文件必然含这一段字样。
    """
    found = []
    hints = tuple(sorted({dotted.rsplit(".", 1)[1] for dotted in names}))
    for ref in ast_scan.sourceRefsUnder(root, ".py", hints):
        imported = _importedNames(ref.code)
        for dotted in names:
            tail = dotted.rsplit(".", 1)[1]
            if any(n == dotted or n.startswith(dotted + ".") or n == f"__REL__.{tail}"
                   for n in imported):
                # 注入探针在 tmp 下：relative_to(REPO) 会抛 ValueError 冒名成被测故障
                # （同一坑在 §6-107 刚栽过一次，这次照搬修好的形态）
                try:
                    shown = ref.path.relative_to(REPO).as_posix()
                except ValueError:
                    shown = ref.path.relative_to(root).as_posix()
                found.append(f"{shown} → {dotted}")
                break
    return found


def test_retiredMixinsHaveNoImporter():
    """四件退役面：生产与测试都不许再引用（删之前实测两侧都是 0）。"""
    found = _hits(PKG_ROOT, RETIRED) + _hits(TESTS_ROOT, RETIRED)
    assert not found, f"已退役的 mixin 又被人引用了：{found}"


def test_retiredFilesAreGone():
    back = [rel for rel in RETIRED.values() if (LAYER / rel).is_file()]
    assert not back, f"四件换代残留又回到包树里：{back}"


def test_pendingRulingsAreStillUnruled():
    """需人裁的两件：仍在位（未裁不许删）且仍零消费者（不许偷偷接线后再裁）。

    这是一格**反向存在断言**——与"防再生"相反，它防的是"裁决还没下，代码先没了"。
    裁下来之后要动这条判据，就得同时改台账 §6-113：那笔改动本身就是留痕。
    """
    still_there = [rel for rel in PENDING.values() if (LAYER / rel).is_file()]
    assert sorted(still_there) == sorted(PENDING.values()), (
        f"未裁的两件少了：{sorted(PENDING.values())} → 实存 {still_there}。"
        "删它们之前先出裁决（graph_density/recovery_rate 是全仓唯一实装，"
        "现役 relation_module 只到 depth-1 且按键去重，不等价）")
    wired = _hits(PKG_ROOT, PENDING)
    assert not wired, f"未裁的两件被接线进生产了：{wired}"


def test_liveSubstitutesStillWired():
    """反向对照（防删过头）：替代者必须仍在装配链上，且是"实质在跑"不是"文件在"。"""
    mgr = (LAYER / "manager.py").read_text(encoding="utf-8")
    assert "_ensure_explainability_module" in mgr and "_ensure_relation_module" in mgr, \
        "manager 的两个懒装配工厂不见了——那正是本批四件对应的现役入口"
    assert "def search_memories" in mgr and "def recall(" in mgr, \
        "现役搜索面不在了（本批删的 search_mixin 六个入口全硬返 []，靠的就是这两条）"
    sleep = (LAYER / "sleep.py").read_text(encoding="utf-8")
    assert "_dream_logs" in sleep, "现役梦境日志面不在了"


def test_scannerCatchesARevival(tmp_path):
    """注入探针：造一处对退役 mixin 的引用必须抓到，现役模块名不误伤。"""
    bad = tmp_path / "revival.py"
    bad.write_text(f"from {NS}.search_mixin import SearchMixin\n", encoding="utf-8")
    assert _hits(tmp_path, RETIRED) == ["revival.py → " + f"{NS}.search_mixin"]
    bad.write_text("from neurova.cognitive_layers.memory_layer.modules.relation_module import x\n",
                   encoding="utf-8")
    assert not _hits(tmp_path, RETIRED), "误伤了现役 relation_module"


def test_scanRootActuallyCoversTheTree():
    mods = [p for p in PKG_ROOT.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(mods) > 500, f"扫描根只覆盖 {len(mods)} 个 .py，层级写错了"
