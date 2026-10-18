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


def _hits(root: Path, names: dict) -> list[str]:
    """子树里仍引用这批 mixin 的落点（四种取法都认）。

    取数走 `tests/ast_scan` 的共享入口 `importersOfModule`：它自己按**末段名**预筛
    （`search_mixin` 等——那是判据的充分条件：无论绝对还是相对 import，真引用它的文件
    必然含这一段字样）。此前这里是私有 `_importedNames` 加一个 `__REL__.` 前缀补丁：
    相对形自己补上了一半，`from neurova.cognitive_layers.memory_layer import search_mixin`
    这种**父包取名形**（`node.module` 是父包）仍看不见。
    显示名：仓内给仓库相对路径，仓外（注入探针落在 tmp 下）只给文件名——
    否则判据自己会抛 `ValueError` 冒名成被测故障（§6-107 那坑在入口里收了一处）。
    """
    found = []
    for dotted in sorted(names):
        for rel, _lineno, _form in ast_scan.importersOfModule(root, dotted):
            shown = rel if rel.startswith(("neurova/", "tests/", "scripts/", "docs/")) \
                else Path(rel).name
            found.append(f"{shown} → {dotted}")
    return sorted(found)


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

    # 父包取名形：真引用，旧那份私有谓词（含它自造的 `__REL__.` 补丁）看不见这一形
    viaParent = tmp_path / "via_parent.py"
    viaParent.write_text(f"from {NS} import dream_mixin\n", encoding="utf-8")
    assert _hits(tmp_path, RETIRED) == [
        "revival.py → " + f"{NS}.search_mixin",
        "via_parent.py → " + f"{NS}.dream_mixin",
    ], "父包取名形没被抓到——导入通道判据又在学旧口径只比一种取法"

    bad.write_text("from neurova.cognitive_layers.memory_layer.modules.relation_module import x\n",
                   encoding="utf-8")
    viaParent.unlink()
    assert not _hits(tmp_path, RETIRED), "误伤了现役 relation_module"


def test_scanRootActuallyCoversTheTree():
    mods = [p for p in PKG_ROOT.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(mods) > 500, f"扫描根只覆盖 {len(mods)} 个 .py，层级写错了"
