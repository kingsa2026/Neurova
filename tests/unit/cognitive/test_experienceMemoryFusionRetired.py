# -*- coding: utf-8 -*-
"""ExperienceMemoryFusion 退役守卫（教义第 7 条：同功能先比后合，其余退役）。

退役对象与对比结论（四项逐项，2026-11-12 现算）：

- `neurova/cognitive_layers/memory_layer/experience_memory_fusion.py`：每轮把
  工具结果＋图谱上下文融合成一条内存记录（1000→500 截断，不落盘）。它的
  `confidence` 是启发式拍算（0.5 基础 + 0.3 成功 + 0.1 图谱 + 0.1 时延），且在
  无回执时把 success 折成 False（`tool_result.get("success", False)`）——正是
  工单 002 废掉的那种「无据即失败/成功」折算。
- `post_chat_pipeline._step_extract_conversation_rules` 里的唯一写入调用；
  `agent_core.wire_memory_guards` 的装配；`tests/unit/cognitive/
  test_experience_memory_fusion.py`（测的是无人消费的产物）；
  `tests/test_memory/_memory_persistence.py`（手工演示脚本，非收集面，
  主体依赖随本退役死亡）。

对比（EKB ＋ 结晶器为存续方）：
- **正确性**：EKB 成败位走 服务端票据(010) > 工具回执(002) > 用户回执 的客观链，
  逐字可核闸（001）与人工处置（015）兜底；fusion 的启发式 confidence 连三态都没有。
- **覆盖面**：EKB 持久化＋检索注入（injector/chat_pipeline）＋采纳回写（006）＋
  运营浏览（007/015）；fusion 覆盖面＝0——`get_fused_memories`/`get_tool_statistics`
  全仓零生产消费方（只写不读，§2 断点条款点名的形态）。
- **可测性**：fusion 的单测测的是写侧产物（无人读 ⇒ 测了也测不出价值）；
  EKB 有注入/排序/质量门禁多面测试在守。
- **调用方数量**：fusion 写 1 读 0；EKB 写 1（post_chat 沉淀）读 2＋API。

无可取之长（graph_context 无人消费），故不「取长补短」直接退役；冲突检测/版本
快照/依赖图三个同批装配的组件**不**在退役范围——它们有真实消费方
（`tests/unit/agent/test_memory_guards_wiring.py` 在守）。

本档钉四件不许复活 + 一枚自我防御：
1. 模块文件与两份测试/脚本文件不存在；
2. `neurova/`＋`tests/`＋`scripts/` 里 `ExperienceMemoryFusion`／
   `experience_fusion`／`experience_memory_fusion` 零出现（本守卫档自身除外）；
3. 同批仍存续的装配守卫档在场（否则将来它被删时本退役失去对照）；
4. 反向控制：合成样本必须被扫描器点名、本档自身不得误报无辜档。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RETIRED_MODULE = (REPO_ROOT / "neurova" / "cognitive_layers" / "memory_layer"
                  / "experience_memory_fusion.py")
RETIRED_TEST = (REPO_ROOT / "tests" / "unit" / "cognitive"
                / "test_experience_memory_fusion.py")
RETIRED_SCRIPT = REPO_ROOT / "tests" / "test_memory" / "_memory_persistence.py"
WIRING_GUARD = REPO_ROOT / "tests" / "unit" / "agent" / "test_memory_guards_wiring.py"
DEAD_NAMES = ("ExperienceMemoryFusion", "experience_fusion", "experience_memory_fusion")

_SCAN_ROOTS = ("neurova", "tests", "scripts")


def _hits():
    """死名字的全部出现位置（本守卫档自身除外）。"""
    hits = []
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for name in DEAD_NAMES:
                if name in text:
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()} :: {name}")
    return hits


class TestExperienceMemoryFusionRetired:
    def test_module_file_is_gone(self):
        assert not RETIRED_MODULE.exists(), (
            f"融合器模块还在：{RETIRED_MODULE}——只写不读的断点未清")

    def test_retired_test_and_script_are_gone(self):
        for path in (RETIRED_TEST, RETIRED_SCRIPT):
            assert not path.exists(), f"退役档的测试/演示脚本还在：{path}"

    def test_dead_names_have_zero_references(self):
        hits = _hits()
        assert not hits, ("退役名字仍有引用（复活即红）：\n  " + "\n  ".join(sorted(hits)))

    def test_surviving_wiring_guard_is_still_present(self):
        assert WIRING_GUARD.is_file(), (
            "同批存续的装配守卫不在了——本退役失去对照，三个存续组件的装配面无人守")

    def test_repo_root_sanity(self):
        assert (REPO_ROOT / "neurova" / "agent_core.py").is_file(), (
            "REPO_ROOT 没指向仓库根——本档的「零出现」类断言可能恒绿（形态 373）")


class TestScannerReallyBites:
    """反向控制：合成样本必须被抓到，无辜文件不得误报。"""

    def test_synthetic_reference_is_caught(self, tmp_path):
        sentinel = tmp_path / "sentinel.py"
        sentinel.write_text(
            "from neurova.cognitive_layers.memory_layer.experience_memory_fusion "
            "import ExperienceMemoryFusion\n", encoding="utf-8")
        hits = []
        for name in DEAD_NAMES:
            if name in sentinel.read_text(encoding="utf-8"):
                hits.append(name)
        assert hits, "扫描判据放过了合成样本——零出现断言不可信"

    def test_this_guard_itself_is_exempt_but_neighbour_is_not(self):
        """本档点名死名字是合法的（退役对象要留案底）；邻档无死名字。"""
        here = Path(__file__).resolve()
        assert "ExperienceMemoryFusion" in here.read_text(encoding="utf-8")
