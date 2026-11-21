# -*- coding: utf-8 -*-
"""suite_eval 运行台账落盘（P1-0）：`<数据根>/benchmark/suite_runs/*.json`。

补 `api/endpoints/benchmark.py::_RUNS_STORE` 的进程内断点——run 到达终态时
原子落盘（temp + os.replace，与 `multi_agent.report` 同纪律），重启后历史
仍可读回。读面两件：`loadSuiteRun`（单条）、`listSuiteRuns`（全量列表，
坏文件如实跳过不阻断）；落点与 `multi_agent` 报告同源，都从数据根派生。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional


def defaultSuiteRunsDir() -> Path:
    """suite 评测 run 台账的统一落点：`<数据根>/benchmark/suite_runs/`。"""
    from neurova.core.data_root import get_data_root

    return get_data_root() / "benchmark" / "suite_runs"


def saveSuiteRun(runData: dict, directory: Optional[str] = None) -> str:
    """run 记录 JSON 原子落盘（temp + os.replace），返回落点路径字符串。

    写前建父目录；同盘 replace 保证读者要么看到旧文件要么看到完整新文件，
    不存在读到半截 JSON 的中间态。
    """
    runId = str(runData.get("run_id") or "").strip()
    if not runId:
        raise ValueError("runData.run_id 缺失——无主运行记录不落盘")
    target = (Path(directory) if directory else defaultSuiteRunsDir()) / f"{runId}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + target.name, dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(runData, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(target)


def loadSuiteRun(runId: str, directory: Optional[str] = None) -> Optional[dict]:
    """按 run_id 取回单条运行记录；不存在或坏文件如实返回 None。"""
    base = Path(directory) if directory else defaultSuiteRunsDir()
    file = base / f"{Path(runId).stem}.json"
    if not file.exists():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏文件如实返回 None，不阻断读面
        return None
    return data if isinstance(data, dict) else None


def listSuiteRuns(directory: Optional[str] = None) -> List[dict]:
    """列出已落盘的 run 记录（新→旧，按 started_at 倒序）。

    只读面：坏文件/非 dict 内容如实跳过，不抛错不阻断列表。
    """
    base = Path(directory) if directory else defaultSuiteRunsDir()
    if not base.exists():
        return []
    items: List[dict] = []
    for file in base.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 坏文件跳过，不阻断列表
            continue
        if isinstance(data, dict):
            items.append(data)
    items.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return items
