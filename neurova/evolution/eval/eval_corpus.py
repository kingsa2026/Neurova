"""评测语料工件与结晶入库泄漏闸(P1-1,2026-10-07)。

层序事实:结晶器在 cognitive_layers(低层),评测域在 evolution——闸的判定
逻辑与语料都留在本模块,经 attach_ingestion_gate 注入结晶器,不产生反向
import(对比研究 B.2 登记的"层序受阻"由此解除:缺的是语料工件这一环)。

语料来源:eval service 每次物化评测集(golden/挖掘/合成)时合并去重落盘
(build_dataset 统一出口),路径 get_data_root()/agents/<id>/evolution/
eval_corpus.json,env NEUROVA_EVOLUTION_EVAL_CORPUS 重定位(测试指向临时
目录)。有界(CORPUS_CAP),防无界增长。

标记纪律与 leak_critic 同源(deterministic_leak_check 单一事实源,教义
第 7 条);无语料=无围栏,诚实放行(宁漏勿误杀)。检查对象:结晶文本里会
原文入库的 sample_context——模式键/工具名/成功率是结构化字段,不是泄漏面。

挂载点:post_chat 复盘通道(review_pending_with_llm 调用点,agent_id 在手,
幂等)。已知窗口:crystallization_llm_gate_enabled=false(显式直写)且首评
之前的候选不经本闸——登记于对比研究附录 B.2。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

CORPUS_ENV = "NEUROVA_EVOLUTION_EVAL_CORPUS"
# 语料有界:只保留最近 CORPUS_CAP 条(评测集滚动,老题面失去围栏意义)
CORPUS_CAP = 256


def eval_corpus_path(agent_id: Any) -> Path:
    """语料工件落点(env 整路径重定位优先;缺省按 agent 进化树推导)。"""
    injected = (os.environ.get(CORPUS_ENV) or "").strip()
    if injected:
        return Path(injected)
    from neurova.core.agent_workspaces import get_agent_evolution_dir

    return get_agent_evolution_dir(agent_id or "default") / "eval_corpus.json"


def update_eval_corpus(agent_id: Any, dataset: Any) -> bool:
    """把物化评测集合并进语料工件(去重、按序截尾到 CORPUS_CAP)。

    原子写(tmp + replace);语料读写失败不阻断进化主流程(围栏是安全垫,
    不是主路径)。
    """
    try:
        examples = list(getattr(dataset, "all_examples", []) or [])
    except Exception:  # noqa: BLE001 - 非数据集形态不物化
        return False
    if not examples:
        return False

    fresh = [{"task_input": str(getattr(e, "task_input", "") or ""),
              "expected_behavior": str(getattr(e, "expected_behavior", "") or "")}
             for e in examples]
    path = eval_corpus_path(agent_id)
    merged: List[Dict[str, str]] = []
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = (data or {}).get("examples", [])
            merged = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("结晶闸语料读取失败,重建语料工件: %s", e)
        merged = []

    seen = {(e.get("task_input", ""), e.get("expected_behavior", "")) for e in merged}
    for item in fresh:
        key = (item["task_input"], item["expected_behavior"])
        if key not in seen:
            seen.add(key)
            merged.append(item)
    merged = merged[-CORPUS_CAP:]

    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "examples": merged}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.warning("结晶闸语料写入失败: %s", e)
        return False


def load_corpus_examples(agent_id: Any) -> List[Dict[str, str]]:
    """读语料原始条目(损坏/缺失 → 空表 = 无围栏,诚实放行)。"""
    try:
        data = json.loads(eval_corpus_path(agent_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = (data or {}).get("examples", [])
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def corpus_markers(agent_id: Any) -> frozenset:
    """语料标记集——与 leak_critic 同一构建纪律(单一事实源)。"""
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    from neurova.evolution.eval.leak_critic import LeakCritic

    raw = load_corpus_examples(agent_id)
    if not raw:
        return frozenset()
    ds = EvalDataset(train=[
        EvalExample(task_input=e.get("task_input", ""),
                    expected_behavior=e.get("expected_behavior", ""))
        for e in raw
    ])
    return LeakCritic().build_markers(ds)


def make_crystallization_leak_gate(agent_id: Any) -> Callable[[str], Optional[str]]:
    """结晶入库闸:命中返回证据片段,None=放行。

    每次调用现读语料——结晶低频(≥3 次观察才成候选)、文件有界,不设缓存
    就没有陈旧围栏。
    """
    def _gate(text: str) -> Optional[str]:
        from neurova.evolution.eval.leak_critic import deterministic_leak_check

        verdict = deterministic_leak_check(
            str(text or ""), "", corpus_markers(agent_id))
        if verdict is not None and verdict.leaked:
            return verdict.evidence or verdict.category
        return None

    return _gate


def attach_crystallization_leak_gate(crystallizer: Any, agent_id: Any) -> bool:
    """幂等挂载:已挂过闸的结晶器拒绝重建(返回 False)。"""
    if getattr(crystallizer, "_ingestion_gate", None) is not None:
        return False
    if not hasattr(crystallizer, "attach_ingestion_gate"):
        return False
    crystallizer.attach_ingestion_gate(make_crystallization_leak_gate(agent_id))
    return True
