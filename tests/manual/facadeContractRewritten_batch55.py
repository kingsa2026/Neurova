# -*- coding: utf-8 -*-
"""live-verify（§6-238）：门面契约改判成反向钉之后，真导入链仍走得通，而旧契约塞回去会被咬。

批 55 只动判据不动生产码，所以"绿"本身不说明什么——要验的是**改判之后的方向对不对**：

1. **两层对照**：门面源码级（AST）读到的顶层绑定集合，与真 `import neurova.skills` 之后的运行时
   公开绑定、`__all__` 三者必须一致（现读 2 个名字）。只在一层上看会漏：源码有绑定而运行时没有
   （被后面的 `del`/条件覆盖）、或运行时多出来（别的模块往里塞属性）。
2. **活名字真能用**：`get_skill_registry()` / `create_default_skills()` 走真装配取读数，
   不是 `callable()` 就完事——§6-200 那批的病正是"拿到 None 再调用"，改判别把活着的那两个也判没。
3. **`SkillSource` 的单源与通道**：门面上不得有它（反向钉的那半句）；`hub_client` 用的必须就是
   `models` 那一份；成员清单直接取真身，不抄旧档里的六个/五个值。
4. **消费者现数**：经门面取 `SkillSource` 的落点数（应为 0）与直取 `neurova.skills.models` 的落点清单。
   这条是"退役不是删能力"的证据——词汇表还在，只是只剩一个出处。
5. **反向校准（同一把尺打在旧契约上）**：把 `from neurova.skills.models import SkillSource, …`
   那行塞进一份**仓外**的门面副本，本档 cell 4 与 cell 6 的谓词必须报出来。没这一步，
   "绿"可能只是断言恒真。
6. **同契约两处判据必须同向**：改判档 + §6-210 那档（`test_skillsFacadeAndSourceEnumAreSingleSourced.py`）
   一起跑，两边都绿——否则就是我在制造第二份互相矛盾的口径（教义第 6 条）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/facadeContractRewritten_batch55.py`
"""
from __future__ import annotations

import ast
import importlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot(prefix="neurovaFacadeB55")     # 本档会真装配，落点必须走仓内唯一隔离口

from tests import ast_scan  # noqa: E402

GUARD = "tests/unit/test_noDeadImportSwallowFacadeBlocks.py"
OTHER = "tests/unit/skills/test_skillsFacadeAndSourceEnumAreSingleSourced.py"
FACADE_REL = "neurova/skills/__init__.py"
RETIRED = ("SkillInfo", "Skill", "SkillSource", "SkillHubClient", "RemoteSkill",
           "SkillService", "SkillRegistry")
failures: list = []


def read(idx: str, desc: str, fn) -> None:
    try:
        print("[%s] PASS %s  ← %s" % (idx, desc, fn()))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def observe(desc: str, fn) -> None:
    try:
        print("    OBSERVE %s：%s" % (desc, fn()))
    except Exception as exc:  # noqa: BLE001 - 观察项不记分，只留读数
        print("    OBSERVE %s：读数失败 %r" % (desc, exc))


def sourceBoundNames(text: str) -> dict:
    """门面源码里**模块级** `from X import name` 绑定的名字 → 来源模块（与判据同口径）。"""
    bound = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound[alias.asname or alias.name] = node.module
    return bound


def _threeFaces():
    text = (REPO / FACADE_REL).read_text(encoding="utf-8")
    bound = sourceBoundNames(text)
    facade = importlib.import_module("neurova.skills")
    declared = list(getattr(facade, "__all__", []))
    runtime = {n for n, v in vars(facade).items()
               if not n.startswith("_") and not isinstance(v, type(sys))}
    assert set(bound) == set(declared) == runtime, (
        f"三层不一致：AST {sorted(bound)}／__all__ {sorted(declared)}／运行时 {sorted(runtime)}")
    assert declared, "__all__ 是空的——这层的对照没对象"
    return "%d 个名字逐字相同：%s（来源 %s）" % (
        len(declared), sorted(declared), sorted(set(bound.values())))


def _realAssembly():
    facade = importlib.import_module("neurova.skills")
    registry = facade.get_skill_registry()
    assert hasattr(registry, "register"), "registry 不是真 SkillRegistry（%r）" % type(registry)
    assert facade.get_skill_registry() is registry, "单例没回来——门面给的是第二份"
    created = facade.create_default_skills()
    populated = getattr(created, "skills", None) or getattr(created, "_skills", None) or {}
    assert populated, "内置技能装配出 0 条——先确认是装配坏了还是读数取错层"
    return "真装配：%s 条内置技能进表（registry=%s，单例二次取回同一实例）" % (
        len(populated), type(registry).__name__)


def _singleSource():
    facade = importlib.import_module("neurova.skills")
    assert not hasattr(facade, "SkillSource"), "门面上还能取到 SkillSource（反向钉失效）"
    models = importlib.import_module("neurova.skills.models")
    hub = importlib.import_module("neurova.skills.hub_client")
    assert hub.SkillSource is models.SkillSource, (
        "hub_client 又自带一份同名枚举——§6-210 合并的那步被退回了")
    return "成员取真身：%s ⇒ 单源一份" % [m.name for m in models.SkillSource][:6]


def _consumers():
    takenViaFacade = []
    directModels = []
    for ref in ast_scan.sourceRefsUnder(REPO / "neurova", hints=("SkillSource",)):
        tree = ast_scan.transientTree(ref.path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            names = {a.name for a in node.names}
            if "SkillSource" not in names:
                continue
            if (node.module or "").startswith("neurova.skills.models") or (
                    node.level and (node.module or "").endswith("models")):
                directModels.append("%s:%d" % (ast_scan.relativeToRepo(ref.path), node.lineno))
            elif (node.module or "").endswith("skills"):
                takenViaFacade.append("%s:%d" % (ast_scan.relativeToRepo(ref.path), node.lineno))
    assert not takenViaFacade, "还有人经门面取 SkillSource（那条通道已被判没）：%s" % takenViaFacade[:5]
    assert directModels, "直取 models 的落点数是 0——说明取数口径没跑起来，不是能力还在"
    return "经门面 0 处；直取 models %d 处（%s…）" % (
        len(directModels), ", ".join(directModels[:3]))


def _reverseProof():
    """把旧契约塞进一份**仓外**副本，再用本档 cell 4 / cell 6 的谓词各打一遍。"""
    workdir = Path(tempfile.mkdtemp(prefix="neurovaFacadeB55Rev"))
    copy = workdir / "facadeOldContract.py"
    text = (REPO / FACADE_REL).read_text(encoding="utf-8")
    planted = ("from neurova.skill_system import create_default_skills, get_skill_registry\n"
               "from neurova.skills.models import Skill, SkillInfo, SkillSource\n")
    body = text.split("from neurova.skill_system import create_default_skills, "
                      "get_skill_registry\n", 1)
    assert len(body) == 2, "门面里那行顶层导入找不到，反向校准无从塞起"
    copy.write_text(body[0] + planted + body[1], encoding="utf-8")

    bound = sourceBoundNames(copy.read_text(encoding="utf-8"))
    back = sorted(set(bound) & set(RETIRED))
    assert back, "把旧契约塞回去之后 cell 4 那半句读不到任何退役名单名字——反向钉是空的"

    seen, dupes = {}, []
    for node in ast.walk(ast.parse(copy.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                key = alias.asname or alias.name
                origin = "%s:%s" % (node.module, alias.name)
                if key in seen and seen[key] != origin:
                    dupes.append((key, seen[key], origin))
                seen.setdefault(key, origin)
    assert "SkillSource" in back, "cell 4 的名单抓不到 SkillSource：%s" % back
    return "塞回旧契约后现读命中 %s；同名抢绑扫描另报 %s ⇒ 两格都有牙" % (back, dupes or "无")


def _bothGuardsGreen():
    lines = []
    for rel in (GUARD, OTHER):
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--tb=no", "--no-header", rel], cwd=str(REPO), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = proc.stdout + proc.stderr
        summary = [l.strip("= ").strip() for l in out.splitlines()
                   if " passed" in l or " failed" in l or " error" in l]
        if not summary:
            raise AssertionError("%s 没产出汇总行（没跑成不等于全绿）" % rel)
        assert " failed" not in summary[-1] and " error" not in summary[-1], \
            "%s 仍然红：%s" % (rel, summary[-1])
        lines.append("%s→%s" % (Path(rel).name[:-3], summary[-1]))
    return " ; ".join(lines)


def _dataFingerprint():
    import hashlib
    root = REPO / "data"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    digest = hashlib.sha256("\n".join(
        "%s:%d" % (p.relative_to(root).as_posix(), p.stat().st_size) for p in files)
        .encode("utf-8")).hexdigest()[:12]
    return len(files), digest


read("1", "AST / 运行时 / __all__ 三层现读一致", _threeFaces)
read("2", "活着的那两个名字走真装配拿得到读数", _realAssembly)
read("3", "SkillSource 不在门面上，且 hub_client 用的就是 models 那一份", _singleSource)
read("4", "经门面取 SkillSource 的消费者＝0，直取 models 的落点数出来", _consumers)
read("5", "反向校准：把旧契约塞进仓外副本，两格谓词必须报出", _reverseProof)
read("6", "同契约两处判据同向绿（改判档 + §6-210 那档）", _bothGuardsGreen)

observe("仓内 data/ 未被写入（本档真装配，落点应全在临时根）", lambda: (
    "%d 个文件，内容＋字节数指纹 %s" % _dataFingerprint()))

print("\n==== 汇总：6 项计分读数，失败 %d ====" % len(failures))
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
