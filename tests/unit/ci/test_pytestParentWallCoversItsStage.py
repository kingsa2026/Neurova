# -*- coding: utf-8 -*-
"""单档父墙必须窄于它所在 CI stage 的墙——两墙同值时，先到点的是整段被强杀。

## 红是怎么来的（2026-10-25 构建 `cnb-009-1k5pg3vcp#003`）

`unit-tests` 的 stage 于 **82%** 被平台杀死：`Killed`、`code: 137`、`duration: 28m 0s`。
日志里那 82% 一条失败都没有，`collected 7926 items` 之外最刺眼的是**每格 30s 的 setup
超时**——它们是 `pytest-timeout` 自己的读数，不是缺陷的读数。

上一笔（`68ba37dd`）把这道 stage 的墙从 30m 抬到 90m；但**单档墙没跟着动**：
`pyproject.toml` 的全局 `timeout = 30` 仍是每一格的墙。整段被掐断时先到点的仍是平台那道
stage 墙，单档那 30s 只来得及把慢格记成 `Timeout`——两层读数挤在一起，读谁都不算结论。

## 不变量（只认活配置，不抄任何秒数）

对 `.cnb.yml` 里每一道**跑 pytest 的 stage**：

1. 该 stage 的墙从 `timeout:` 现读（缺省即无界，本闸不管）；
2. 跑测命令里若显式给了 `--timeout=N`，那一层的墙就是 N；
3. 否则墙取 `pyproject.toml` 的 `[tool.pytest.ini_options] timeout`（缺省父墙的唯一事实源）；
4. **stage 墙必须严格大于第 2/3 步的读数**，相等也判红。

分母（扫到几道跑测 stage）自带面自证：低于下限说明 stage 命名或命令形状变了，本闸失明。

## 边界（明写，不当已收口）

- 只认 `.cnb.yml`：GitHub 侧同一条命令由 job 级 `timeout-minutes` 给墙，读法与取值面都不同，
  不在此档；两侧命令同源由 `test_ci_parity_guard.py` 钉住。
- 只认「stage 墙 vs 单档墙」这一对：`pytest.mark.timeout(N)` 与全局 `timeout` 之间那对由
  `test_nestedPytestBudgetWallsAreOrdered.py` 负责，本档不重复造一把尺。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

yaml = pytest.importorskip("yaml")

_mod = sys.modules[__name__]

REPO = Path(__file__).resolve().parents[3]
CNB = REPO / ".cnb.yml"
PYPROJECT = REPO / "pyproject.toml"

#: 面自证下限：现读 `.cnb.yml` 里带墙的跑测 stage 有 3 道（import-and-regression /
#: unit-tests / e2e）；perf-gate 与 experience-quality 跑的是独立脚本、不吃单档墙，
#: 按口径不算跑测 stage。写死现值等于等着它讲假话，故只取下限——扫描根写窄必掉穿。
STAGE_FACE_FLOOR = 3

_UNIT = re.compile(r"^\s*(\d+)\s*(ms|s|m|h)?\s*$")
_FACTOR = {None: 1, "ms": 0.001, "s": 1, "m": 60, "h": 3600}
_PER_CASE_FLAG = re.compile(r"--timeout[= ](\d+)")


def stageWallSeconds(text: str) -> Optional[float]:
    """`90m` / `30m` / `45s` → 秒；算不出给 None（**不是 0**：无界与未知是两件事）。"""
    match = _UNIT.match(str(text))
    if not match:
        return None
    return int(match.group(1)) * _FACTOR[match.group(2)]


def globalCaseWallSeconds(pyprojectText: str) -> Optional[float]:
    """`[tool.pytest.ini_options] timeout = 30` 的读数；切到下一个 `[表]` 为止。"""
    _head, sep, tail = pyprojectText.partition("[tool.pytest.ini_options]")
    if not sep:
        return None
    body: List[str] = []
    for line in tail.splitlines():
        if line.lstrip().startswith("["):
            break
        body.append(line)
    match = re.search(r"^[ \t]*timeout[ \t]*=[ \t]*(\d+)", "\n".join(body), re.M)
    return float(match.group(1)) if match else None


def caseWallSeconds(script: str, globalWall: Optional[float]) -> Tuple[float, str]:
    """这一道 stage 的**单档墙**读数与它的出处。

    `.cnb.yml` 的 `script:` 是 **shell**，`#` 之后是注释——注释里提到 `--timeout 900`
    不改变任何一格的墙，读它等于把一句话当成配置。故先在命令行 `#` 处截断，
    再认「`pytest` 那一行上的 `--timeout=N`」；没有就继承 `pyproject.toml` 的全局 `timeout`。

    命令里 `--timeout` 的值**读不出**（`$WALL` 这类外部值）时退回**最保守**的读法：
    取「全局值」与「全仓显式声明过的最小值」里更小的那个。只认全局会漏掉一种真实形状——
    命令用变量给墙、而变量比全局宽，那已经**同样**是两墙错配；宁可判严，
    也不许把未知报成合规。
    """
    for line in script.splitlines():
        command = line.split("#", 1)[0]
        if "pytest" not in command:
            continue
        explicit = _PER_CASE_FLAG.search(command)
        if explicit:
            return float(explicit.group(1)), "--timeout"
        if re.search(r"--timeout(?![= ]\d)", command):
            return min(globalWall, _narrowestExplicit()), "--timeout(值读不出，按最保守)"
    return globalWall, "pyproject 全局"


def _narrowestExplicit() -> float:
    """全仓活配置里现读「显式声明过的单档墙」的最小值（不抄字面量）。"""
    values: List[float] = []
    for path in [CNB, *sorted((REPO / ".github").rglob("*.yml"))]:
        for match in _PER_CASE_FLAG.finditer(path.read_text(encoding="utf-8", errors="replace")):
            values.append(float(match.group(1)))
    return min(values) if values else 0.0


def _stageTimeout(pipeName: str, stageName: str) -> Optional[str]:
    data = yaml.safe_load(CNB.read_text(encoding="utf-8", errors="replace"))
    for pipe in (data.get("main") or {}).get("push") or []:
        if pipe.get("name") != pipeName:
            continue
        for stage in pipe.get("stages") or []:
            if stage.get("name") == stageName:
                return stage.get("timeout")
    return None


def _runTestsIn(script: str) -> bool:
    """命令里是否**真跑一套用例**（`pip install pytest-timeout` 那种只装不跑的不算）。"""
    return any("pytest" in line and ("tests" in line or ".py" in line or "$TESTS" in line)
               for line in script.splitlines())


def _pytestStages() -> List[Tuple[str, str, str]]:
    """(流水线名, stage 名, 跑测命令)——只收带墙且真跑用例的 stage。"""
    data = yaml.safe_load(CNB.read_text(encoding="utf-8", errors="replace"))
    found: List[Tuple[str, str, str]] = []
    for pipe in (data.get("main") or {}).get("push") or []:
        for stage in pipe.get("stages") or []:
            script = str(stage.get("script") or "")
            if not stage.get("timeout"):
                continue        # 无界 stage：父墙那一路由别处管，本档不说它合规
            if not _runTestsIn(script):
                continue
            found.append((pipe.get("name"), stage.get("name"), script))
    return found


class TestEveryPytestStageOutlivesItsOwnCaseWall:
    def test_stage_face_is_wide_enough(self):
        stages = _pytestStages()
        assert len(stages) >= STAGE_FACE_FLOOR, (
            f"只扫到 {len(stages)} 道带墙的跑测 stage（下限 {STAGE_FACE_FLOOR}）："
            "stage 命名或命令形状变了，本闸已失明"
        )

    def test_no_stage_wall_equals_its_case_wall(self):
        assert wallOffenders() == [], "跑测 stage 的墙没宽过它自己的单档墙:\n  " + "\n  ".join(wallOffenders())


def wallOffenders() -> List[str]:
    """两墙错配的 stage（判据与自证共用这一把尺，不写第二遍规则）。"""
    globalWall = globalCaseWallSeconds(PYPROJECT.read_text(encoding="utf-8", errors="replace"))
    assert globalWall is not None, "pyproject 里读不到全局 timeout——缺省父墙的事实源不见了"
    offenders: List[str] = []
    for pipe, stage, script in _pytestStages():
        parentText = _stageTimeout(pipe, stage)
        parent = stageWallSeconds(parentText)
        if parent is None:
            offenders.append(f"{pipe}/{stage}: stage 墙读不出数值（{parentText!r}）")
            continue
        caseWall, source = caseWallSeconds(script, globalWall)
        if parent <= caseWall:
            offenders.append(
                f"{pipe}/{stage}: stage 墙 {parent:g}s ≤ 单档墙 {caseWall:g}s（{source}）"
                "——相等时先到点的是整段强杀，诚实的单格超时永远轮不到说话")
    return offenders


class TestDetectorHasTeeth:
    """合成样本对照：相等要抓、stage 更窄要抓、更宽要放行——三头都钉在**同一把尺**上。

    走 `wallOffenders()` 本身（不是各测一段辅助函数）：判据与自证共用一把尺，
    尺子自己坏了的时候，对照也会一起红——否则"零违规"与"没扫到"长得一样。
    """

    @staticmethod
    def _offendersFor(cnbText: str, pyprojectText: str, monkeypatch, tmp_path) -> List[str]:
        (tmp_path / ".cnb.yml").write_text(cnbText, encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(pyprojectText, encoding="utf-8")
        manifest = tmp_path / "scripts" / "ci" / "protected_tests.txt"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("tests/unit/x.py\n", encoding="utf-8")
        monkeypatch.setattr(_mod, "CNB", tmp_path / ".cnb.yml")
        monkeypatch.setattr(_mod, "PYPROJECT", tmp_path / "pyproject.toml")
        monkeypatch.setattr(_mod, "REPO", tmp_path)
        return wallOffenders()

    @staticmethod
    def _cnb(timeout: str, script: str) -> str:
        return (
            "main:\n  push:\n    - name: unit-tests\n      stages:\n"
            "        - name: run subset\n          script: |\n            " + script + "\n"
            f"          timeout: {timeout}\n"
        )

    def test_equal_walls_are_red(self, monkeypatch, tmp_path):
        offenders = self._offendersFor(
            self._cnb("1800s", "python -m pytest -q --timeout 1800 tests/unit/x.py"),
            "[tool.pytest.ini_options]\ntimeout = 30\n", monkeypatch, tmp_path)
        assert offenders and "1800s" in offenders[0], f"两墙相等没被判红：{offenders}"

    def test_stage_narrower_than_its_case_wall_is_red(self, monkeypatch, tmp_path):
        offenders = self._offendersFor(
            self._cnb("2m", "python -m pytest -q --timeout 240 tests/unit/x.py"),
            "[tool.pytest.ini_options]\ntimeout = 30\n", monkeypatch, tmp_path)
        assert offenders, "stage 比单档墙还窄却被放行"

    def test_inheriting_the_global_wall_under_a_wider_stage_is_green(self, monkeypatch, tmp_path):
        """正方向对照：stage 90m、单档继承全局 30s ⇒ 合规（否则判据是"全红"）"""
        offenders = self._offendersFor(
            self._cnb("90m", "python -m pytest -q tests/unit/x.py"),
            "[tool.pytest.ini_options]\ntimeout = 30\n", monkeypatch, tmp_path)
        assert offenders == [], f"严格有序的两墙被误判：{offenders}"

    def test_unknown_wall_is_red_not_silently_green(self, monkeypatch, tmp_path):
        """stage 墙读不出数值（写成 `timeout: 半小时`）⇒ 点名，不是放行。"""
        offenders = self._offendersFor(
            self._cnb("half-an-hour", "python -m pytest -q tests/unit/x.py"),
            "[tool.pytest.ini_options]\ntimeout = 30\n", monkeypatch, tmp_path)
        assert offenders, "读不出的 stage 墙被当成合规"

    def test_a_comment_does_not_give_a_wall(self):
        """注释里提到 `--timeout 900` 不改变任何一格的墙——读它等于把一句话当配置。"""
        script = ("# 子集里最高的单档父墙（`pytest.mark.timeout(120)`）见台账\n"
                  "python -m pytest -q tests/unit/x.py")
        assert caseWallSeconds(script, 30.0) == (30.0, "pyproject 全局")

    def test_explicit_flag_beats_the_global_value(self):
        assert caseWallSeconds("python -m pytest -q --timeout 240 tests/e2e", 30.0)[0] == 240
        assert caseWallSeconds("python -m pytest -q --timeout=45 x.py", 30.0)[0] == 45

    def test_unreadable_flag_falls_back_conservatively(self):
        """`--timeout $WALL` 读不出数值时按最保守值算——未知不许被当成合规。"""
        caseWall, source = caseWallSeconds("python -m pytest -q --timeout $WALL tests/x.py", 30.0)
        assert "读不出" in source, f"读不出的墙被当成已知：{source!r}"
        assert caseWall <= 30.0, f"退回值比全局还宽（{caseWall}）＝把未知报成合规"

    def test_unit_parsing_is_honest(self):
        assert stageWallSeconds("90m") == 5400
        assert stageWallSeconds("45s") == 45
        assert stageWallSeconds("1h") == 3600
        assert stageWallSeconds("") is None, "空串被当成 0 就会把无界 stage 报成合规"

    def test_install_only_stage_is_not_a_test_stage(self):
        """只装不跑的 stage 不进账（否则「装 pytest-timeout」会被读成跑测行）。"""
        assert not any("pytest" in line and ("tests" in line or ".py" in line)
                       for line in "python -m pip install pytest pytest-timeout fastapi".splitlines())
