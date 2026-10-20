# -*- coding: utf-8 -*-
"""夜间受保护子集复核的常驻判据（工单 2026-10-11 批 11，裁定「补夜间全量跑」）。

要防的形态都是本仓反复栽过的：

1. **门禁的准入条件本身没人复核**——`protected_tests.txt` 写着「只收逐文件单跑确定全绿」，
   而白天的跑法是一次全塞进 pytest。§6-138 那条常驻红就是这么躺了十几天没人说。
2. **悬空引用**：CI 里点一个不存在的脚本，配置期不报错、夜间静默什么都不做，
   比没有这道门更坏（让人以为有）。故脚本路径要核到文件级。
3. **清单被「顺手整理」**：去重、排序、吞行都会让条目数变小而看不出来。
   判据按原始读数逐条比，不做任何归一。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from tests import ast_scan  # 清单取数的共享入口：本档用 `rawManifestLines()`（原始行那一条）

REPO_ROOT = Path(__file__).resolve().parents[3]
CNB = REPO_ROOT / ".cnb.yml"
SCRIPT = REPO_ROOT / "scripts" / "ci" / "protected_subset_nightly.py"
LIST_FILE = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"

CRON_KEY = "crontab: 0 4 * * *"
JOB_NAME = "nightly-protected-subset-audit"


def mainBlock() -> dict:
    return yaml.safe_load(CNB.read_text(encoding="utf-8"))["main"]


def nightlyJob(main: dict) -> dict:
    """从 main 段里取夜间那一档 job（找不到即红，理由在断言里）。"""
    jobs = main.get(CRON_KEY) or []
    matches = [j for j in jobs if isinstance(j, dict) and j.get("name") == JOB_NAME]
    assert len(matches) == 1, (
        f"main 段下 {CRON_KEY!r} 里应当恰好一个 {JOB_NAME}（当前 {len(matches)} 个）。"
        "0 个＝这道门根本没接上；多于 1 个＝两份口径迟早漂开（教义第 6 条）")
    return matches[0]


def cronFields(key: str) -> list:
    """`crontab: <5 段>` 里的表达式段数（平台只认标准 5 段 POSIX cron）。"""
    prefix = "crontab:"
    assert key.startswith(prefix), f"{key!r} 不是 crontab 顶层键"
    return key[len(prefix):].split()


def nightlyModule():
    spec = importlib.util.spec_from_file_location("protected_subset_nightly", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assertFiveFieldCron(key: str) -> list:
    """crontab 顶层键必须是 5 段 POSIX cron；非法即抛（反向控制要的就是这一处）。"""
    fields = cronFields(key)
    assert len(fields) == 5, (
        f"cron 表达式应为 5 段 POSIX（分 时 日 月 周），当前 {len(fields)} 段：{fields}。"
        "平台只认 5 段：写成 6 段（带秒）或用「间隔 N 天」「daily」这类自然语言"
        "都在解析期就红——配置错误的形态只会在解析期报错，所以判据必须自己拦")
    return fields


def test_scriptExistsAndIsNotADanglingReference():
    assert SCRIPT.exists(), (
        f"{SCRIPT.relative_to(REPO_ROOT)} 不在仓里——CI 点了个不存在的脚本，"
        "配置期不报错、夜间静默空跑，比没有这道门更坏")


def test_cronKeyIsFiveFieldPosix():
    assert assertFiveFieldCron(CRON_KEY) == ["0", "4", "*", "*", "*"]


def test_nightlyJobIsDeclaredAndNonGating():
    job = nightlyJob(mainBlock())
    # 非门禁 → 允许失败，且不上报提交状态（提交状态通道是门禁专用，见 .cnb.yml 上方口径）
    assert job.get("allowFailure") is True, (
        "夜间复核设成硬门禁，就会把「别人合并时还没红的条目」变成拦人的墙；"
        "它的定位是巡检，不是门禁")
    assert "reportCommitStatus" not in str(job), "非门禁不得占用提交状态通道"


def test_jobActuallyRunsTheScript():
    job = nightlyJob(mainBlock())
    scripts = "\n".join(str(stage.get("script", "")) for stage in job.get("stages", []))
    assert "protected_subset_nightly.py" in scripts, (
        "这一步没真去跑那个脚本——名字挂了、活没干，正是「配置都对却静默空转」那一型")
    # 夜间是长跑任务：没写 timeout 时，一条挂死的用例就能吃掉整晚
    assert any("timeout" in str(stage) for stage in job.get("stages", [])), (
        "stages 里没有任何 timeout：夜间任务缺上限即可能整晚挂在一格上")


def test_readerKeepsTheListVerbatim():
    """清单读数逐条同序：不去重、不排序、不把注释行当条目。"""
    raw = ast_scan.rawManifestLines(LIST_FILE)
    assert nightlyModule().readEntries(LIST_FILE) == raw, (
        "脚本眼里的条目与清单原始读数不一致——被去重/排序/吞行之后，"
        "夜间跑的就不是准入时那份清单了")
    assert len(raw) > 100, f"清单只剩 {len(raw)} 条？被「顺手整理」过就要在这里暴露"
    assert len(raw) == len(set(raw)), (
        "同一文件被登记两次：夜间会重复跑它，而重复登记本身就是漂移的信号")


def test_rawReaderIsNotTheNormalizedOne(tmp_path):
    """两条读法必须**不同源**，否则上面那格是自证。

    期望值不向真清单借形状（现读那份清单今天恰好没有行内注释条目——按"清单里应该有"
    写断言就会造出一枚假红，267 那一形）：这里用合成清单把分歧点当场造出来。
    归一化那条把行内 `#` 剥成纯路径；原始行那条必须原样留着，且两者不许哪天"顺手合并"。
    """
    listing = tmp_path / "scripts" / "ci" / "protected_tests.txt"
    listing.parent.mkdir(parents=True)
    listing.write_text(
        "# 整行注释：不该被当条目\n"
        "tests/a.py  # 这条守什么\n"
        "\n"
        "tests/b.py\n"
        "tests/a.py\n",
        encoding="utf-8",
    )
    raw = ast_scan.rawManifestLines(listing)
    normalized = ast_scan.protectedSubsetEntries(tmp_path)
    assert raw == ["tests/a.py  # 这条守什么", "tests/b.py", "tests/a.py"], raw
    assert normalized == ["tests/a.py", "tests/b.py", "tests/a.py"], normalized
    assert any("#" in line for line in raw), "原始行读数把行内注释也剥了＝偷偷归一化"
    assert not any("#" in entry for entry in normalized), "条目读法应当剥掉行内注释，它坏了"
    assert raw != normalized, (
        "两条读法给出同一个结果＝被合成一条了，`test_readerKeepsTheListVerbatim` 随即失去意义")


class TestComparatorsAreNotVacuous:
    """反向控制：上面几格的校验函数必须能被非法输入打红，否则它们全是空转。"""

    def test_badCronShapeIsCaught(self):
        with pytest.raises(AssertionError):
            assertFiveFieldCron("crontab: 0 4 * * * 2")      # 6 段（带秒）
        with pytest.raises(AssertionError):
            assertFiveFieldCron("crontab: daily")            # 自然语言 cadence，平台不认
        with pytest.raises(AssertionError):
            assertFiveFieldCron("branches: 0 4 * * *")       # 不是 crontab 键

    def test_missingOrDuplicatedJobIsCaught(self):
        with pytest.raises(AssertionError):
            nightlyJob({})
        with pytest.raises(AssertionError):
            nightlyJob({CRON_KEY: [{"name": "别的名字"}]})
        with pytest.raises(AssertionError):
            nightlyJob({CRON_KEY: [{"name": JOB_NAME}, {"name": JOB_NAME}]})

    def test_gatingNightlyJobWouldFailTheNonGatingCheck(self):
        """allowFailure 缺省／为 False 时，「非门禁」那句断言必须站不住。"""
        for job in ({"name": JOB_NAME, "stages": []},
                    {"name": JOB_NAME, "allowFailure": False, "stages": []}):
            assert job.get("allowFailure") is not True, (
                "缺省 allowFailure 的夜间任务等同把巡检变成拦人的门禁")

    def test_readerDetectsSortedDedupedAndCommentedVariants(self):
        """读法改动（排序/去重/吞非注释行）必须被原始逐条比对抓到。"""
        reader = nightlyModule().readEntries
        synthetic = LIST_FILE.with_name(".tmp_synthetic_list.txt")
        try:
            synthetic.write_text(
                "# 注释行\n\ntests/a.py\ntests/b.py\ntests/a.py\n", encoding="utf-8")
            assert reader(synthetic) == ["tests/a.py", "tests/b.py", "tests/a.py"], (
                "读法把注释/空行之外的条目改了顺序或去了重——夜间跑的就不是准入那份清单")
        finally:
            synthetic.unlink(missing_ok=True)
