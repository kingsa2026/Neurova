# -*- coding: utf-8 -*-
"""安装咽喉的暂存目录名不许吃调 Windows 路径预算（真入口 500 的真实成因）。

实形是**本机真 HTTP 面量出来的**，不是台账里的旧描述：面板安装随包内置的
`builtin--adaptive-presentation-studio` 报 HTTP 500，拒因是一串 `shutil.Error` 元组、
strerror 为 `[WinError 3] 系统找不到指定的路径`，抛点在 `install_skill` 把 staging
拷进 `.incoming_<skill_id>_<毫秒>` 的那一步——**安装门根本没被调用**。那个名字比最终
目标目录名多占一整段 skill_id（本例 37 字符）+ 13 位时间戳，于是"在终点合法（投影 ≤259）"
的包在暂存处就撞过 260 上限。同一只包在解包那一步今天是过的（投影 204/240 < 260）。

本档钉四件事：
  1. 暂存名与 skill_id 长度**无关**（不整段嵌入 ID）；
  2. 暂存名有绝对上界——取"任何合理命名策略下都成立"的值，不钉实现选的那个数；
  3. 前缀 `.incoming_` 必须留着：`artifact_digest._VOLATILE_DIR_PREFIXES` 与
     `market_registry._STAGING_IGNORED` 两处豁免只认前缀，改名即**静默失效**；
  4. 终点合法的包必须装得成（Windows 行为格；POSIX 无 260 上限故如实跳过）。
"""

import ast
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

from neurova.security import artifact_digest as AD
from neurova.skills.market_registry import _STAGING_IGNORED
from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
SERVICE_SRC = REPO / "neurova" / "skills" / "skill_service.py"

#: 前缀是两处豁免表认的键，不许动（按值钉真源，不按"两边相等"钉——见形态集 242）。
STAGING_PREFIX = ".incoming_"
#: 与实现无关的上界：10 前缀 + 短标记 + 时间戳，任何合理策略都该装得进 40。
STAGING_NAME_MAX = 40
WINDOWS_MAX_PATH = 260
LONG_ID = "builtin--adaptive-presentation-studio"   # 37 字符，真包里就是它
SHORT_ID = "demo-skill-x"                            # 12 字符，用来证"与 ID 长度无关"

SKILL_MD = "---\nname: demo\ndescription: 演示\n---\n\n# 演示\n\n按步骤执行。\n"
CLEAN_PY = "def helper(value):\n    return value.strip()\n"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _manifest(skill_id: str) -> str:
    return json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0",
                       "description": "演示包", "enabled": True, "source": "marketplace"},
                      ensure_ascii=False)


def _package(tmp_path: Path, skill_id: str, member_rel: str = "") -> Path:
    """造一份**内容干净**的包：门必须放行，这样红只能来自落点而不是来自裁决。"""
    root = tmp_path / ("pkg_" + skill_id.replace("--", "_"))
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(_manifest(skill_id), encoding="utf-8")
    (root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (root / "lib.py").write_text(CLEAN_PY, encoding="utf-8")
    if member_rel:
        deep = root / member_rel
        deep.parent.mkdir(parents=True, exist_ok=True)
        deep.write_text("{}", encoding="utf-8")
    return root


def _capturedStagingNames(monkeypatch):
    """把 `install_skill` 那次 copytree 的暂存目标名取回来（装完就被删，读不到）。"""
    seen: list = []
    real = shutil.copytree

    def spy(src, dst, *args, **kwargs):
        seen.append(Path(str(dst)).name)
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", spy)
    return seen


class TestStagingNameDoesNotEmbedTheSkillId:
    def test_stagingNameLengthIsIndependentOfIdLength(self, tmp_path, monkeypatch):
        """长短两个 ID 产生的暂存名必须**一样长**——今天整段嵌 ID，故随 ID 变长。"""
        seen = _capturedStagingNames(monkeypatch)
        for skill_id in (SHORT_ID, LONG_ID):
            svc = SkillService(agent_id="staging-budget", skills_dir=str(tmp_path / f"skills-{skill_id}"))
            result = svc.install_skill(str(_package(tmp_path, skill_id)), skill_id=skill_id)
            assert result.get("success"), f"{skill_id} 没装成，读数无意义：{result}"
        names = [n for n in seen if n.startswith(STAGING_PREFIX)]
        assert len(names) == 2, f"期望两次各产生一个暂存名，实得 {names}"
        lengths = {len(n) for n in names}
        assert lengths == {min(lengths)} and len(names[0]) == len(names[1]), (
            f"暂存名随 skill_id 长度增长（{names}）：终点合法成员在暂存处就会越过 260")

    def test_stagingNameWithinAbsoluteBudget(self, tmp_path, monkeypatch):
        """暂存名有绝对上界（取"任何合理策略都成立"的数，不钉实现选的那个值）。"""
        seen = _capturedStagingNames(monkeypatch)
        svc = SkillService(agent_id="staging-budget", skills_dir=str(tmp_path / "skills-abs"))
        assert svc.install_skill(str(_package(tmp_path, LONG_ID)), skill_id=LONG_ID).get("success")
        names = [n for n in seen if n.startswith(STAGING_PREFIX)]
        assert names, f"这次安装没经过暂存拷贝，格打空（seen={seen}）"
        assert all(len(n) <= STAGING_NAME_MAX for n in names), (
            f"暂存名 {names} 超出 {STAGING_NAME_MAX} 预算：多出来的每一字符都是从"
            "Windows 260 上限里借的")


class TestStagingPrefixStaysRecognised:
    def test_prefix_matches_bothExemptionFaces(self, tmp_path, monkeypatch):
        """两处豁免各自必须等于那份前缀单源——只比"两边相等"在两边同时改错时会绿。

        本格**今天就是绿的**（钉的是以后有人改名那一下），牙由变异 P2 证：把暂存名
        前缀改掉时，摘要面与 staging 忽略面这两条必须同时翻红。
        """
        seen = _capturedStagingNames(monkeypatch)
        svc = SkillService(agent_id="staging-budget", skills_dir=str(tmp_path / "skills-pre"))
        assert svc.install_skill(str(_package(tmp_path, LONG_ID)), skill_id=LONG_ID).get("success")
        names = [n for n in seen if n.startswith(STAGING_PREFIX)]
        assert names, "没有暂存名可核，格打空"
        assert all(n.startswith(STAGING_PREFIX) for n in names), names

        assert AD._VOLATILE_DIR_PREFIXES == (STAGING_PREFIX,), (
            f"摘要侧豁免前缀漂了：{AD._VOLATILE_DIR_PREFIXES}——暂存目录会被当成构件算进摘要")
        # 另一面判**效果**不判清单：`_STAGING_IGNORED` 是 ignore_patterns 产出的可调用，
        # 只认它真把暂存目录剔出去（按字符串成员判会 TypeError，且那样判的是抄表不是行为）。
        probe_dir = tmp_path / "cache-probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        staged = STAGING_PREFIX + "deadbeef_1792129486311"
        (probe_dir / staged).mkdir()
        (probe_dir / "lib.py").write_text(CLEAN_PY, encoding="utf-8")
        ignored = _STAGING_IGNORED(str(probe_dir), [staged, "lib.py"])
        assert staged in ignored, (
            f"staging 忽略面不再把 {staged!r} 剔出去（实际剔了 {sorted(ignored)}）"
            "——缓存里的暂存目录会被拷进下一份 staging")


@pytest.mark.skipif(sys.platform != "win32", reason="POSIX 无 260 字符上限，本格在此平台无对象")
class TestLegalAtFinalTargetMustInstall:
    def test_packageLegalAtTargetInstalls(self, tmp_path):
        """成员在**终点**合法（投影取合法上界 259）的包必须装得成。

        长度按当前临时根现场算，不写死：暂存形态比终点多占 `.incoming_` + `_` + 13 位
        时间戳 = 24 字符，所以"终点 259"这一形在旧命名下投影 283（越界），换短标记后 254（合法）。
        """
        skills_dir = tmp_path / "agent-skills"
        header = len(str(skills_dir)) + 1 + len(LONG_ID) + 1
        member_len = WINDOWS_MAX_PATH - 1 - header          # 终点投影正好落在 259
        if member_len < 16:
            pytest.skip(f"临时根已达 {len(str(skills_dir))} 字符，连终点都放不下合法成员，本格无对象")
        prefix, suffix = "assets/" + "d" * 40 + "/", ".json"
        fill = member_len - len(prefix) - len(suffix)
        if fill < 1:
            pytest.skip(f"成员名只剩 {member_len} 字符可铺，构造不出同量级深路径")
        member_rel = prefix + "p" * fill + suffix
        assert len(member_rel) == member_len, (len(member_rel), member_len)
        final_projection = header + len(member_rel)
        assert final_projection == WINDOWS_MAX_PATH - 1, final_projection

        svc = SkillService(agent_id="staging-budget", skills_dir=str(skills_dir))
        result = svc.install_skill(str(_package(tmp_path, LONG_ID, member_rel)), skill_id=LONG_ID)
        assert result.get("success"), (
            f"终点投影 {final_projection} 字符（合法上界），却被暂存那一步拒在门外：{result}")
        assert (Path(skills_dir) / LONG_ID / member_rel).is_file()


class TestStagingNameBuilderIsSingleSourced:
    """格名即设计说明：**这格今天就是绿的**，钉的是以后别再抄第二份。

    判定按 AST 取"函数体里出现 `.incoming_` 字面量"的函数名集合；暂存名只许在一处拼。
    """

    def _bodiesHoldingPrefix(self, source: str):
        hits = []
        for node in ast.walk(parseSource(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for x in ast.walk(node):
                if isinstance(x, ast.Constant) and isinstance(x.value, str) \
                        and x.value.startswith(STAGING_PREFIX) and "{" not in x.value:
                    hits.append(node.name)
                    break
        return sorted(set(hits))

    def test_serviceBuildsTheStagingNameInExactlyOneBody(self):
        src = io.open(SERVICE_SRC, encoding="utf-8").read()
        hits = self._bodiesHoldingPrefix(src)
        assert len(hits) == 1, (
            f"`.incoming_` 暂存名在 {len(hits)} 个函数体里各拼一份：{hits}——两份就会各自演化，"
            "一处改了名另一处的豁免判定静默失效")

    def test_detectorSeesTheShapeAndNotTheWord(self):
        """反空转格：探测器必须真认得这个形状，否则上一条绿得没道理。"""
        sample = (
            "def _make_stage():\n"
            "    return f'.incoming_{name}_{stamp}'\n"
            "def read_prefix():\n"
            "    return '.incoming_x'\n"
            "def unrelated():\n"
            "    return 1\n"
        )
        assert self._bodiesHoldingPrefix(sample) == ["_make_stage", "read_prefix"], (
            "探测器抓不到 `.incoming_` 字面量所在的那两个函数体——上一格是在靠不咬人装绿")
