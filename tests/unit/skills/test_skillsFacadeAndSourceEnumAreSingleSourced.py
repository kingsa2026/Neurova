# -*- coding: utf-8 -*-
"""skills 门面只留有消费者的名字，`SkillSource` 全仓一份（§6-200 挂的两次裁定，批 46 落地＝乙）。

建档时读到的实状（现算，非记忆）：
- `neurova/skills/__init__.py` 挂 47 个再导出名字，**生产侧只有 2 个被经门面取用**
  （`create_default_skills`←`neurova/agent_core.py` 三处、`get_skill_registry`←`api/endpoints/skill.py`
  三处）；其余 45 个生产与测试两侧都零消费者——两边用的都是
  `from neurova.skills.models import ...` 这种直取。批 42 已经把那 48 个 `X = None`
  占位符摘掉，但"门面挂一份没人读的词汇表"这条 §2 断点留在原地。
- `SkillSource` 有**两份类定义**：`models.py`（LOCAL/MARKETPLACE/BUILTIN，纯 `Enum`，
  注在 `models.Skill.source` 上，答"技能从哪装来"）与 `hub_client.py`
  （GITHUB/CLAWHUB/LOBEHUB/MODELSCOPE/LOCAL，`(str, Enum)`，注在 `RemoteSkill.source` 上，
  答"从哪个市场取来"）。此前两条 import 先后绑同一个门面名字，给出去哪一份取决于书写顺序。

裁定＝合并成一份。类型一旦并起来，"哪个字段只许取哪一段词汇"就不再被类型约束，
所以那层区分必须作为**数据**显式钉住（`installSources()` / `marketSources()` 两个子集 +
`RemoteSkill` 构造时按子集验值）——今天 `SkillSource("marketplace")` 喂给 `RemoteSkill`
会在 hub 那份枚举上 ValueError，合并后仍须拒，这不是新增限制而是保住既有行为。
"""

import ast
import io
import subprocess
from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"
FACADE = "neurova/skills/__init__.py"

# 现算：这两个是唯一经门面被生产代码取用的名字
FACADE_KEEP = {"create_default_skills", "get_skill_registry"}


def _facadeReexports():
    """门面包级 `from X import (...)` 绑定的名字 → 来源模块。"""
    tree = ast.parse((PROJECT_ROOT / FACADE).read_text(encoding="utf-8"))
    bound = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound[alias.asname or alias.name] = node.module or ""
    return bound


def _facadeConsumers():
    """生产侧**经门面**取用的原名集合（取法口径收在 `ast_scan.namesTakenFrom`，本档不再自写一份）。

    两处都是 §6-211 档案实测过的坑：按 `asname` 记账会把活着的名字读成零消费者
    （`from neurova.skills import get_skill_registry as gsr`），不解析相对导入则
    `from .skills import …`／`from ..skills import …` 整形看不见——两者都让上一格假红。
    预筛 hint 给两条：绝对形含 `neurova.skills`，相对形必含 `.skills`。
    """
    used = {}
    for name, path, lineno in ast_scan.namesTakenFrom(
            ast_scan.nodeScan(NEUROVA, hints=("neurova.skills", ".skills")),
            "neurova.skills"):
        if ast_scan.relativeToRepo(path) == FACADE:
            continue
        used.setdefault(name, []).append(f"{ast_scan.relativeToRepo(path)}:{lineno}")
    return used


def test_facadeCarriesOnlyNamesThatAreConsumed():
    """门面只许挂"确实有人经它取"的名字——零消费者的再导出就是把同一词汇表抄第二份。"""
    bound = set(_facadeReexports())
    assert bound, "门面一个再导出都没有——那本档失去对象，先确认取数口径"
    consumers = _facadeConsumers()
    unbound = sorted(name for name in bound if name not in consumers)
    assert not unbound, (
        f"这些名字挂在技能门面上却无人经门面取用（子模块取法另计）：{unbound}")


def test_theTwoLiveNamesStillResolveThroughTheFacade():
    """反空转配对格：退役不许顺手把活着的那两个也带走（agent_core / skill.py 真的从门面取）。"""
    consumers = _facadeConsumers()
    for name in sorted(FACADE_KEEP):
        assert consumers.get(name), f"{name} 经门面被消费的落点读不到了——上一格会假绿"
    import importlib

    skills = importlib.import_module("neurova.skills")
    for name in sorted(FACADE_KEEP):
        assert callable(getattr(skills, name, None)), f"门面上的 {name} 不是可调用对象"


def test_skillSourceIsDefinedOnceInThePackage():
    """`SkillSource` 全仓只许有一份类定义（两份同名＝门面给出去哪份取决于书写顺序）。"""
    defs = [
        ast_scan.relativeToRepo(path)
        for path, _lineno in ast_scan.classDefsIn(NEUROVA, "SkillSource")
    ]
    assert defs == ["neurova/skills/models.py"], (
        f"SkillSource 的定义应当只有一份且在 models.py，实得 {defs}")


def test_mergedEnumKeepsEveryPersistedValueVerbatim():
    """合并后的成员并集，值逐字不变——`.value` 就是写进 manifest 的那串字。"""
    from neurova.skills.models import SkillSource

    expected = {
        "LOCAL": "local", "MARKETPLACE": "marketplace", "BUILTIN": "builtin",
        "GITHUB": "github", "CLAWHUB": "clawhub", "LOBEHUB": "lobehub",
        "MODELSCOPE": "modelscope",
    }
    got = {m.name: m.value for m in SkillSource}
    assert got == expected, f"成员或值与两份合并前的并集不一致：{got}"


def test_eachFieldKeepsItsOwnVocabularyAsData():
    """类型并成一个之后，"哪个字段只许取哪一段"必须显式存在（今天靠两份枚举天然挡住）。"""
    from neurova.skills.models import SkillSource

    missing = [n for n in ("installSources", "marketSources") if not hasattr(SkillSource, n)]
    assert not missing, (
        f"枚举上缺 {missing}——类型并成一份后，字段的取值域必须由数据说出来，"
        "不然 `RemoteSkill.source` 与 `Skill.source` 会互相能塞对方的词")
    install = SkillSource.installSources()
    market = SkillSource.marketSources()
    assert install == frozenset({SkillSource.LOCAL, SkillSource.MARKETPLACE, SkillSource.BUILTIN}), \
        f"装载来源子集变了：{sorted(m.value for m in install)}"
    assert market == frozenset({
        SkillSource.GITHUB, SkillSource.CLAWHUB, SkillSource.LOBEHUB,
        SkillSource.MODELSCOPE, SkillSource.LOCAL}), f"市场源子集变了：{sorted(m.value for m in market)}"

    from neurova.skills.hub_client import RemoteSkill

    ok = RemoteSkill(name="x", source=SkillSource.GITHUB, description="", version="1",
                     url="", download_url="")
    assert ok.to_dict()["source"] == "github", "RemoteSkill 的序列化值变了"
    with pytest.raises(ValueError):
        RemoteSkill(name="x", source=SkillSource.MARKETPLACE, description="", version="1",
                    url="", download_url="")


def test_noConsumerReachesSkillSourceThroughHub():
    """合并之后，`SkillSource` 的取径只许指向定义处，不许借 `hub_client` 转手。

    hub 里那个名字如今是 import 带进来的附属属性，不是定义；哪天 hub 不再用它，
    `from neurova.skills.hub_client import SkillSource` 就当场 ImportError——而它今天
    照样能过，正是"隔着转手点认词汇"的形状（本批把 `skill_service.py:652` 改成直取 models）。
    """
    offenders = []
    for path, node in ast_scan.nodeScan(NEUROVA, hints=("neurova.skills.hub_client",)):
        if not isinstance(node, ast.ImportFrom) or node.module != "neurova.skills.hub_client":
            continue
        for alias in node.names:
            if (alias.asname or alias.name) == "SkillSource":
                offenders.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
    assert not offenders, (
        f"这些落点仍经 hub_client 转手取 SkillSource（定义处只有 models.py）：{offenders}")


def test_skillFieldStillAcceptsWhatStorageWrites():
    """`Skill.source` 的默认值与取值面：本批**不给它加运行时拒绝**。

    现算的理由：`api/endpoints/skill.py:247,373` 是 `SkillInfo(**s)` 直接摊平存储字典，
    里面 `source` 今天是裸字符串；manifest 那侧还写着 `auto`/`synthesized`（第三套词汇，
    未裁）。给这个字段加"越段即拒"的检查＝把那条未裁的事偷偷上线成一条会拒数据的门。
    域约束这一批只加在 `RemoteSkill` 上——它今天本就靠 hub 那份枚举挡住市场源之外的值。
    """
    from neurova.skills.models import Skill, SkillSource

    fresh = Skill(name="s")
    assert fresh.source is SkillSource.LOCAL and fresh.source.value == "local"
    fromStorage = Skill(name="s", source="auto")   # 摊平存储字典的真实形状，不得因此炸
    assert fromStorage.source == "auto"
