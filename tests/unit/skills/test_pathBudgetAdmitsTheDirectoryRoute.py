# -*- coding: utf-8 -*-
r"""目录形安装的落点预算是**准入条件**，不是拷贝失败的注脚（§6-503 裁"接闸"的落地）。

复算出来的实形（§6-500 入账、§6-503 定取向）：本地目录／zip／`install-from-zip` 三支
都汇到 `skill_service.install_skill` 这个咽喉，zip 那支早在**解包之前**就用
`refusalForPathBudget` 判过落点预算，目录这支直接 `shutil.copytree` —— 同一只包换个入口
就绕过了准入。于是失败由这台机器的文件系统决定：受保护子集里三格红的读数正是
`[WinError 206] 文件名或扩展名太长`，而那条路径里还留着 `.incoming_<纳秒>` 的**半棵树**
（`copytree` 非事务，炸在中间不清理）。讽刺的是被拦那格的名字正是
`test_studioPackageBudgetIsDecidedByTheGateNotByTheOs`。

取向是"接闸"而不是"真支持长路径"或"改短暂存名"，理由记在 §6-503：
`\\?\` 前缀要连路径比较与 `artifact_digest` 的落锤口径一起改（同一份字节因前缀不同算出
两个摘要就是新病），且要带安装包活体；改短暂存名是治标；按宿主条件 skip＝把已知失效藏起来。

预算数字与文案都**不在这个档里重写**：判定取 `market_sources._pathBudgetExceeded`、
文案取 `pathBudgetRefusal`（与 zip 那支同一份），本档只钉"这条路由它"以及"两个落点根都要量"。
"""

import ast
import json
from pathlib import Path

import pytest
from tests.ast_scan import parseSource

from neurova.skills import market_sources as ms
from neurova.skills.skill_service import SkillService

REPO = Path(__file__).resolve().parents[3]
SKILL_SERVICE = REPO / "neurova" / "skills" / "skill_service.py"

#: 深成员相对路径：目录名堆到一定长度就够越界，不必依赖本机绝对根长
DEEP_MEMBER = "assets/builtin_templates/codex-grid-layout-library/artifact-tool-compose/run.sh"


def _srcWithDeepMember(base: Path, skill_id: str) -> Path:
    src = base / skill_id
    (src / "assets" / "builtin_templates" / "codex-grid-layout-library"
        / "artifact-tool-compose").mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}), encoding="utf-8")
    (src / "assets" / "builtin_templates" / "codex-grid-layout-library"
        / "artifact-tool-compose" / "run.sh").write_text("echo ok\n", encoding="utf-8")
    return src


@pytest.fixture
def svc(tmp_path):
    return SkillService(agent_id="budget-t", skills_dir=str(tmp_path / "installed"))


def test_directoryRouteRefusesDeepLandingAndNamesTheCause(svc, tmp_path, monkeypatch):
    """长落点必须**当场被闸拒并点名原因**，且不在盘上留半棵暂存树。

    预算上限按既有那格的写法压小（不赌本机绝对路径长度）：判定与文案仍然全走生产实现。
    """
    monkeypatch.setattr(ms, "WINDOWS_MAX_PATH", 60)
    src = _srcWithDeepMember(tmp_path / "src", "deep1")

    result = svc.install_skill(str(src))

    assert result["success"] is False, f"深落点照样装成了（闸没接上这条路由）：{result}"
    assert "路径过长" in str(result.get("error", "")), (
        f"拒因没点名，读的人只会去改一个没坏的包：{result}")
    assert result.get("code") == "path_budget", result
    residue = sorted(Path(svc.skills_dir).glob(".incoming_*"))
    assert residue == [], f"被拒的安装留下了半棵暂存树：{residue}"
    assert not (Path(svc.skills_dir) / "deep1").exists(), "被拒的落点不得存在"


def test_shallowLandingStillInstalls(svc, tmp_path):
    """正对照：**不误伤**是这条闸的另一半——正常预算内照装，读面必须看得见。"""
    src = _srcWithDeepMember(tmp_path / "src", "plain1")

    result = svc.install_skill(str(src))

    assert result["success"] is True, f"正常落点被拦＝闸算错了投影：{result}"
    assert svc.get_skill_info("plain1") is not None


def test_bothLandingRootsAreMeasured(tmp_path, monkeypatch):
    """暂存根 `.incoming_<纳秒>` 与最终根 `<skill_id>` 谁长没规律，只判一个就会漏。

    这一格钉的正是今天那 3 条红的形状：`WinError 206` 报在 `.incoming_...` 那一步，
    而按最终根投影时反而在预算内——只量最终根的闸会放行、真拷贝照样炸。
    预算取 240 来构造这个**不对称**（不依赖本机 tmp 根的绝对长度）：
    暂存根投影约 205＝在预算内，最终根加长约 298＝越界；反过来只量短根就会"放行后炸"。
    """
    src = _srcWithDeepMember(tmp_path / "src", "s1")
    monkeypatch.setattr(ms, "WINDOWS_MAX_PATH", 240)
    base = tmp_path / "installed"
    staging = base / ".incoming_1793000000000000000"
    finalShort = base / "s1"
    finalLong = base / ("y" * 120) / "s1"

    assert len(str(staging)) > len(str(finalShort)), "构造失效：暂存根本该比最终根长"
    assert ms.refusalForTreeBudget(src, [finalShort, staging]) == "", (
        "两个落点根都在预算内却拒了——不误伤是这条闸的另一半")

    onlyFinalChecked = ms.refusalForTreeBudget(src, [finalShort, finalLong])
    assert "路径过长" in onlyFinalChecked, (
        f"只量到短根就放行，真拷贝到长根照样炸：{onlyFinalChecked}")
    assert DEEP_MEMBER in onlyFinalChecked, f"点名要指到具体那个最长成员：{onlyFinalChecked}"


def test_refusalSaysItIsALandingProblemNotAPackageProblem(tmp_path):
    """文案的方向：`§6-259` 那条真实成因就是"落点根太长"被折进一句 zip refused，
    读的人去改了一个没坏的包。方向词必须有。"""
    src = _srcWithDeepMember(tmp_path / "src", "s2")
    reason = ms.refusalForTreeBudget(src, [tmp_path / ("y" * 250)])
    assert "落点问题，不是包的问题" in reason, reason


def test_directoryRouteJudgesWithTheOneBudgetSource(tmp_path):
    """结构面：`install_skill` 必须调那个单源判定，不许在这条路上另写一个 260。

    判定与文案分家＝"拒了说不清"或"说了没人拒"（`refusalForPathBudget` 的 docstring
    写的就是这条），所以这里钉的是**调用点存在**与**预算常量只有一处定义**。
    """
    tree = parseSource(SKILL_SERVICE.read_text(encoding="utf-8"), filename=str(SKILL_SERVICE))
    install = next(n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "install_skill")
    callees = {getattr(node.func, "id", None) or getattr(node.func, "attr", None)
               for node in ast.walk(install) if isinstance(node, ast.Call)}
    assert "refusalForTreeBudget" in callees, (
        f"目录形安装这条路没有走单源预算判定：{sorted(x for x in callees if x)[:8]}…")

    literal260 = [node.lineno for node in ast.walk(install)
                  if isinstance(node, ast.Constant) and node.value == 260]
    assert literal260 == [], f"install_skill 里另写了一份 260（第二个事实源）：{literal260}"

    definitions = [p.relative_to(REPO).as_posix() for p in [REPO / "neurova" / "skills" / "market_sources.py"]
                   if "WINDOWS_MAX_PATH = " in p.read_text(encoding="utf-8")]
    assert definitions == ["neurova/skills/market_sources.py"], definitions
