"""睡眠固化的编排面只许剩一份实现——`sleep_adapter.py` 那层壳的退役锁（§6-209 票②）。

现量归属（2026-10-15 重算，不抄台账旧数）：壳 198 行、1 类 7 法；`neurova/` 里对它的外部
import **0 处**（只剩它自己的类名与日志串），`tests/` 12 行全在一个类里，`scripts/` 0；
⇒ **生产零消费者**。它自建 `MemoryRecord`（`sleep_adapter.py:105-115`，9 个键）不经
`from_dict`，因此 `agent_id/neuser_id/user_id` 全落默认值 `"default"` —— 隔离作用域在这条腿上
被抹平（§6-223 记的那形）。同一条链在选定那份（`sleep.py` 的 `SleepConsolidation`）上早已
按作用域分桶、按源行写回（§6-226），所以壳的"不可替代部分"实际为零。

教义第 7 条的判据是"该功能在仓内只剩一处实现被消费"。本档三格分工：
- 主格红在今天：壳还活着（名字仍可 import）；
- 另两格是**交付锁**（现值绿，红由变异提供）：删壳不许把它覆盖的三件事一起删没——
  编排能力必须还在选定那份上，`from_dict` 必须仍认壳当年手工搬的那 9 个键。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import neurova
from tests import ast_scan
from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation

#: 壳当年手工搬进 MemoryRecord 的键（`sleep_adapter.py:105-115` 现场抄来，不是想象）
SHELL_KEYS = ("id", "content", "embedding", "temperature", "importance",
              "emotion_score", "recall_count", "created_at", "categories")


def testTheShellIsGoneAndNothingStillNamesIt():
    """主格：那层壳不许再存在，也不许再有生产代码点它的名字（教义第 7 条的判据形态）。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("neurova.cognitive_layers.memory_layer.sleep_adapter")

    neurovaDir = Path(neurova.__file__).resolve().parent
    # 取数走 `tests/ast_scan.sourceRefsUnder` 的共享预算＋文本预筛，不私有 `rglob + read_text`：
    # 后者把判据成本绑在代码总量上（`test_memoryLayerGenerationResidue.py` 的档头就写着这条账，
    # 而 `test_ci_ast_scan_budget_guard` 判红的正是这形）。第一版这里就是裸 rglob 读全树，
    # 三目录合跑时给同选择集里的重扫描档加了一份墙钟压力。
    hits = [ref.path.name for ref in ast_scan.sourceRefsUnder(
        neurovaDir, ".py", ("sleep_adapter", "SleepConsolidationAdapter"))]
    assert hits == [], "生产面仍有对壳的引用：%s ⇒ 退役没闭环" % hits


def testTheChosenImplementationStillCarriesTheOrchestration():
    """交付锁（现值绿）：编排能力必须在选定那一份上齐全——删壳不许顺手把功能删没。"""
    for name in ("consolidate", "run_sleep_cycle", "cluster_by_similarity",
                 "merge_cluster", "start_sleep", "wake"):
        assert callable(getattr(SleepConsolidation, name, None)), (
            "选定的那份缺 %s() ⇒ 壳不是重复实现，而是唯一通路，退役判据不成立" % name
        )

    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result)

    assert callable(write_back_consolidation_result)


def testFromDictCarriesEveryKeyTheShellHandBuilt():
    """交付锁（现值绿）：`from_dict` 必须认壳当年手工搬的那 9 个键，含单数 `category` 跨界口。

    壳的"不可替代部分"要验证实质而不是只看存在：它建的记录若比 `from_dict` 多认一个键，
    退役就会丢那条键的事实。`category`（单数）那半是 §6-222 现量补上的——写侧只发单数键时
    读侧不认，类别就整条链路失明。
    """
    record = MemoryRecord.from_dict({
        "id": "n1", "content": "那件事", "embedding": [0.1, 0.2], "temperature": 61.0,
        "importance": 55.0, "emotion_score": 0.3, "recall_count": 4,
        "created_at": "2026-10-01T00:00:00+00:00", "category": "episodic",
        "agent_id": "a1", "neuser_id": "ne-a", "user_id": "u-a",
    })
    missing = [k for k in SHELL_KEYS
               if k not in record.__dict__ and not hasattr(record, k)]
    assert missing == [], "from_dict 供不出壳认得的键：%s" % missing
    assert list(record.categories) == ["episodic"], (
        "单数 category 没被接住（实得 %s）⇒ 壳的最后一处不可替代还没并进选定那份"
        % (record.categories,))
    assert (record.agent_id, record.neuser_id, record.user_id) == ("a1", "ne-a", "u-a"), (
        "隔离三元组没从字典里活下来（实得 %s）⇒ 壳抹平作用域那条形成了契约"
        % ((record.agent_id, record.neuser_id, record.user_id),))
