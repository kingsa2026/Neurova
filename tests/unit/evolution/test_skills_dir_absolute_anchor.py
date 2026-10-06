# -*- coding: utf-8 -*-
"""skills_dir 作为落盘锚点必须是绝对路径；mock / 相对串一律显式拒绝

取证见对话与 `audit-reports/`：仓库根曾出现
`MagicMock/SkillService().skills_dir/<id>/.lifecycle_state.json`。机制是
`MagicMock` 实现了 `__fspath__`，于是 `Path(mock)` 能过类型检查，其 repr
`<MagicMock name='SkillService().skills_dir' id='...'>` 被 Windows 拆成三层目录，
`_save_last_run` / `ConsolidationPlanStore.upsert` 的 `mkdir(parents=True)` **静默建目录
并写盘成功**——只在 `except OSError` 里留一行 debug。相对路径同理：落点随进程 CWD 漂移。

判据口径不自造：`neurova/core/data_root.py:42` 的 `get_data_root()` 早已对相对
`NEUROVA_DATA_DIR` 显式 ValueError，理由写的就是"数据落点随进程 CWD 漂移，这正是散落
污染的成因"。本文件把同一口径接到**消费边界**（值进入落盘函数的那道），因为生产侧
`SkillService.skills_dir` 本就取 `get_data_root()`（恒绝对），非绝对值只可能是外部注入。

每条都先 `chdir(tmp_path)`：判据不收时，被污染的正是这个可断言的临时目录——
红在行为（有没有真写出东西），不是红在措辞。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neurova.evolution.skill_consolidator import ConsolidationPlanStore
from neurova.evolution.skill_lifecycle import run_sweep_if_due


def _emptyService():
    svc = MagicMock()
    svc.iter_skills.return_value = []
    return svc


def _tree(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_mockSkillsDirIsRejectedBeforeAnyWrite(tmp_path, monkeypatch):
    """mock 的 `__fspath__` 不得被当成落盘锚点。"""
    monkeypatch.chdir(tmp_path)
    svc = _emptyService()

    with pytest.raises(ValueError):
        run_sweep_if_due(svc, svc.skills_dir, now_ms=int(time.time() * 1000))

    assert _tree(tmp_path) == [], f"拒绝前已经往 CWD 落盘了：{_tree(tmp_path)}"


def test_relativeSkillsDirIsRejectedBeforeAnyWrite(tmp_path, monkeypatch):
    """相对串同样拒绝——它会让状态文件跟着 CWD 跑。"""
    monkeypatch.chdir(tmp_path)
    svc = _emptyService()

    with pytest.raises(ValueError):
        run_sweep_if_due(svc, "agents/default/skills", now_ms=int(time.time() * 1000))

    assert not (tmp_path / "agents").exists(), "相对路径被接受并建目录：落点随 CWD 漂移"
    assert _tree(tmp_path) == [], _tree(tmp_path)


def test_planStoreRejectsMockAndRelative(tmp_path, monkeypatch):
    """同契约第二命中点：合并计划落盘仓（6 个生产调用点共用它）。"""
    monkeypatch.chdir(tmp_path)
    svc = _emptyService()

    with pytest.raises(ValueError):
        ConsolidationPlanStore(svc.skills_dir)
    with pytest.raises(ValueError):
        ConsolidationPlanStore("agents/default/skills")

    assert _tree(tmp_path) == [], _tree(tmp_path)


def test_rejectionMessageNamesTheOffendingValue(tmp_path):
    """显式失败要能定位注入方：报错必须带上收到的值与它该来自哪儿。"""
    svc = _emptyService()

    with pytest.raises(ValueError) as exc:
        run_sweep_if_due(svc, svc.skills_dir)

    text = str(exc.value)
    assert "skills_dir" in text, f"报错没点名是哪个入参：{text}"
    assert "MagicMock" in text, f"报错没回显非法值，排查时无从定位注入方：{text}"


def test_serviceConstructorRejectsRelativeAnchor(tmp_path, monkeypatch):
    """上游生产方同判据：`SkillService(skills_dir=...)` 今天会 `mkdir` 到进程 CWD，
    它是两个下游锚点的共同成因，不收这一处就等于留第三份。"""
    monkeypatch.chdir(tmp_path)
    from neurova.skills.skill_service import SkillService

    with pytest.raises(ValueError):
        SkillService(agent_id="rel", skills_dir="agents/rel/skills")

    assert _tree(tmp_path) == [], f"构造期就往 CWD 建目录了：{_tree(tmp_path)}"


def test_absolutePathBehaviourIsUnchanged(tmp_path):
    """收紧不得把生产口径（data root 下绝对路径）的正常语义改窄。"""
    skills = tmp_path / "agents" / "default" / "skills"
    now = int(time.time() * 1000)
    svc = _emptyService()

    assert run_sweep_if_due(svc, skills, now_ms=now) is None
    state = json.loads((skills / ".lifecycle_state.json").read_text(encoding="utf-8"))
    assert state["last_run_at_ms"] == now

    store = ConsolidationPlanStore(skills)
    store.upsert([{"umbrella": "u1", "status": "pending"}])
    assert [p["umbrella"] for p in store.load()] == ["u1"]


def test_anchorJudgementIsSingleSource():
    """判据只许一处定义（教义第 6 条）：两个消费方须调用 data_root 那道锚点，
    而不是各自抄一份 `is_absolute` 判断——抄第二份就等于给未来留第三份。"""
    import inspect

    import neurova.core.data_root as dataRoot
    from neurova.evolution import skill_consolidator, skill_lifecycle

    anchorName = "require_data_path"
    assert callable(getattr(dataRoot, anchorName, None)), (
        f"锚点函数未落在 `core/data_root.py`（找不到 {anchorName}）"
    )

    for module in (skill_lifecycle, skill_consolidator):
        src = inspect.getsource(module)
        assert anchorName in src, f"{module.__name__} 未接上单源锚点"
        assert "is_absolute()" not in src, (
            f"{module.__name__} 自造了第二份绝对路径判据，应收口到 data_root.{anchorName}"
        )
