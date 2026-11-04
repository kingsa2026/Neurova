"""拒因必须念得出「哪一条规则、包内哪个文件、第几行」（欠账①，§6-511 的下游缺口）。

现量根据（动手前实测，不沿用台账旧描述）：
- `Finding` 早就有定位字段：内容扫描两处在填（`skill_scanner.py:338`／`:545` 的
  `file_path=skill_file.path` ＋ `line_number`），名称级两处也填了 `file_path`（`:787`／`:805`）。
- 可安装门的拒因文本（`skill_install_gate.py:163`）只拼 `severity`／`rule_id`／`message`，
  把已有定位整条丢掉 ⇒ 台账 §6-511 追「到底哪一行触发 `dangerous_exec`」追不到。
  那句原判写的「findings 缺定位字段」是**取错了面**：字段在，出口没念——修法在出口侧。
- 同一个「哪个文件」在三处三种口径：`SkillFile(path=str(file_path))`（`:743`，绝对）、
  名称级 `file_path=str(file_path)`（`:787`/`:805`，绝对）、而内容哈希的 census 用
  **相对技能根 posix**（`:869`）。`SkillFile.path` 在仓内从不被当文件系统路径打开
  （`scan_text_for_injection`／`tool_executor` 传进去的就是 `source` 标签）⇒ 它的真语义是
  「包内定位」：绝对路径换台机器就换值（不是产物的身份），也不该念进面向用户的文本。
"""

import ast
from pathlib import Path

import pytest

from neurova.security import skill_scanner as SS
from neurova.skills.skill_install_gate import reset_install_gate_scanner, scan_skill_for_install
from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_FILE = REPO_ROOT / "neurova" / "skills" / "skill_install_gate.py"
SYNTHESIS_FILE = REPO_ROOT / "neurova" / "agent" / "chat_pipeline.py"
SCANNER_FILE = REPO_ROOT / "neurova" / "security" / "skill_scanner.py"

BENIGN_MD = """---
name: demo
description: 演示技能
---

# 演示

按说明使用本技能即可。
"""

#: 第 2 行才是触发行——行号由拒因念出来，不由测试猜
BAD_PY = "payload = read_input()\nexec(payload)\n"


@pytest.fixture(autouse=True)
def _freshScanner():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _pkg(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text(BENIGN_MD, encoding="utf-8")
    (root / "scripts" / "bad.py").write_text(BAD_PY, encoding="utf-8")
    return root


def test_内容级拒因念得出相对定位与行号(tmp_path):
    root = _pkg(tmp_path)
    outcome = scan_skill_for_install("locate-content", str(root))
    assert outcome["passed"] is False, outcome
    error = outcome["error"]
    assert "dangerous_exec" in error, error
    assert "scripts/bad.py:2" in error, error


def test_名称级拒因念得出包内定位(tmp_path):
    root = _pkg(tmp_path)
    (root / ".env").write_text("API_KEY=abcdefghijkl\n", encoding="utf-8")
    outcome = scan_skill_for_install("locate-name", str(root))
    hit = [f for f in outcome["findings"] if f.get("rule_id") == "credential_artifact_name"]
    assert [f.get("file_path") for f in hit] == [".env"], hit
    assert ".env" in outcome["error"], outcome["error"]


def test_拒因不把机器绝对路径念进面向用户的文本(tmp_path):
    root = _pkg(tmp_path)
    error = scan_skill_for_install("locate-abs", str(root))["error"]
    assert str(root) not in error, error
    assert root.name + "/" not in error.replace("\\", "/"), error


def test_定位口径只剩相对技能根一份(tmp_path):
    root = _pkg(tmp_path)
    (root / ".env").write_text("API_KEY=abcdefghijkl\n", encoding="utf-8")
    findings = scan_skill_for_install("locate-single-source", str(root))["findings"]
    located = [f["file_path"] for f in findings if f.get("file_path")]
    assert located, findings
    bad = [fp for fp in located if Path(fp).is_absolute() or str(root) in fp]
    assert bad == [], "定位出现第二种口径（绝对路径）：%s" % bad


def test_元项无定位时拒因照旧出且不留孤立符号(tmp_path):
    outcome = scan_skill_for_install("locate-meta", str(tmp_path / "absent"))
    assert outcome["passed"] is False
    assert "no_files" in outcome["error"], outcome["error"]
    assert "@:" not in outcome["error"] and " @" not in outcome["error"], outcome["error"]


def test_内容面读过的文件不被名称面报成没被读过(tmp_path):
    """收口径时最容易被自己绊倒的一格：`SkillFile.path` 改成相对后，
    「谁没被读过」的对账两侧必须一起改——一侧绝对一侧相对时，**每个读过的文件都会落进
    unscanned 名单**，而 `unscanned_file_count` 是 `len(allPaths) - len(files)` 的算术，
    数字照旧对得上，只有那条报告项会出卖它。
    """
    root = _pkg(tmp_path)
    findings = scan_skill_for_install("locate-census", str(root))["findings"]
    ghosts = [f for f in findings if f.get("rule_id") == "unscanned_artifact"]
    assert ghosts == [], "读过的文件被报成未扫描：%s" % ghosts


def _callsNamed(tree: ast.AST, name: str) -> int:
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            fname = getattr(func, "attr", None) or getattr(func, "id", None)
            if fname == name:
                hits += 1
    return hits


def test_定位格式化只有一份实装且两处出口都经它():
    tree = ast_scan.parseSource(SCANNER_FILE.read_text(encoding="utf-8"), str(SCANNER_FILE))
    defs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "findingLocator"]
    assert len(defs) == 1, "定位文本的格式化落点必须恰有一处（实测 %d 处）" % len(defs)

    for path in (GATE_FILE, SYNTHESIS_FILE):
        consumer = ast_scan.parseSource(path.read_text(encoding="utf-8"), str(path))
        assert _callsNamed(consumer, "findingLocator") >= 1, (
            "%s 把 finding 拼成人读文本却不经单源定位格式化" % path.name)
