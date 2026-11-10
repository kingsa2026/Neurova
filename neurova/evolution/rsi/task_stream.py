# -*- coding: utf-8 -*-
"""Goal B 固定任务流（B2，survey §10.2）——与经验挖掘数据源不相交的评测任务源。

三条纪律：
- **不相交**：任务流与经验挖掘（mined）数据源零重叠——同一 session/knowledge
  出现在两侧即红（`taskStreamOverlapGuard`）。重叠即生成器偏好污染（§7.1）：
  挖掘面喂什么、评测面就考什么，增益读数会自我应验。
- **固定**：任务集是版本化 fixture（`task_stream_fixtures.json`），确定性加载
  （同文件同读数）；改动任务集＝改评测标尺，必须显式改文件（可审计）。
- **来源登记**：每条任务的种子出处随 fixture 走（甲案＝合成形态模板，
  `seed_session_ids` 留空待运维回填真语料；回填时重叠守卫当场复核）。

数据面：挂 `eval.dataset` 的 source 体系（`source="task_stream"`），与
golden/history/synthetic 同字段同读数；本模块零 LLM、纯内存、确定性。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.dataset import EvalDataset, EvalExample

logger = get_logger(__name__)

#: source 词值（B2 新增档）：与 dataset.py 的 source 字段词表并列登记。
TASK_STREAM_SOURCE = "task_stream"

_FIXTURES_PATH = Path(__file__).parent / "task_stream_fixtures.json"

#: 三问形态（τ-bench 式）：工具使用成功 / 策略合规 / 一致性。
TASK_STREAM_FORMS = ("tool_usage_success", "policy_compliance", "consistency")


def taskStreamProvenance() -> Dict[str, Any]:
    """fixture 的来源登记块（种子出处与回填状态随文件走，可审计）。"""
    data = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    return data.get("_provenance") or {}


def loadTaskStream() -> List[EvalExample]:
    """确定性加载固定任务集（source=task_stream；同文件同读数）。"""
    data = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    examples: List[EvalExample] = []
    for task in data.get("tasks") or []:
        examples.append(EvalExample(
            task_input=str(task.get("task_input") or ""),
            expected_behavior=str(task.get("expected_behavior") or ""),
            source=TASK_STREAM_SOURCE,
        ))
    return examples


def taskStreamSessionIds() -> List[str]:
    """任务流的种子出处集合（甲案＝空集；真语料回填后非空，供重叠守卫比对）。"""
    ids = (taskStreamProvenance().get("seed_session_ids") or [])
    return [str(i) for i in ids]


def taskStreamOverlapGuard(mined_session_ids: List[str],
                           fixture_session_ids: Optional[List[str]] = None) -> None:
    """不相交守卫：同一 session 出现在挖掘与任务流两侧即抛。

    mined 侧的出处集合由调用方供（挖掘链的 session 登记回填后接真值）；
    fixture 侧缺省读 provenance。抛错信息点名交集——重叠是要修的数据事实，
    不是可吞的告警。
    """
    fixture_ids = set(fixture_session_ids
                      if fixture_session_ids is not None
                      else taskStreamSessionIds())
    mined = set(str(i) for i in (mined_session_ids or []))
    overlap = sorted(fixture_ids & mined)
    if overlap:
        raise ValueError(
            f"任务流与挖掘数据源重叠：session {overlap} 同时出现在两侧——"
            "生成器偏好污染（§7.1），先修数据面再谈评测")
    logger.debug("任务流重叠守卫通过（mined=%d, fixture=%d）", len(mined), len(fixture_ids))


def taskStreamDataset() -> EvalDataset:
    """固定任务集成数据集（全部进判据集；B2 的任务是外部参考不是搜索语料）。"""
    examples = loadTaskStream()
    return EvalDataset(train=[], val=[], holdout=list(examples))
