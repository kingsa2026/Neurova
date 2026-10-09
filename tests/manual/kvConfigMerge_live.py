# -*- coding: utf-8 -*-
"""活体自证（§6-125 · 序 5 批 E）：KV 配置器合并到分层版后，真读写与真启动都照旧。

单元测试那批用 `patch(...logger)` 断级别，本脚本换成**真 logging**：在 `neurova.core.config`
的 logger 上挂 handler，收真实产生的 LogRecord——mock 断的是"调用发生在谁身上"，真 handler
断的是"运维在日志里看到什么"，后者才是这格分级要保护的对象。

判据（缺一条这条链就是断的）：
1. `save()` 真落盘，文件里是真 JSON 且读得回来（新对象 load，不吃内存）；
2. 文件损坏时 `load()` **记 warning 不记 error**，且内存里已有的键一个不丢
   ——这正是从退役的 `core/config_manager.py` 并过来的那格长处；
3. 写盘真失败（父路径是一个已存在的文件）时记 **error** 且不崩：数据没落盘必须看得见；
4. 反向对照：文件完好时 `load()` 不得产生 warning/error——否则第 2 条"有 warning"
   会被任何一条杂记凑满，本格无从失败；
5. 被并的实现所在的模块仍在全栈路上：真 `create_app()` 起来后 `/api/v1/health` 返 200
   （`core/config.py` 的 env 读口被 9 个生产文件用着，改坏了这里先炸）。

跑法（仓根）：PYTHONPATH=. .venv/Scripts/python.exe tests/manual/kvConfigMerge_live.py
"""
from __future__ import annotations

import sys


def main() -> int:
    import json
    import logging
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    from neurova.core.config import ConfigManager

    failures: list[str] = []

    class _Collect(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[tuple[int, str]] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append((record.levelno, record.getMessage()))

    cfgLogger = logging.getLogger("neurova.core.config")
    collector = _Collect()
    cfgLogger.addHandler(collector)
    cfgLogger.setLevel(logging.DEBUG)

    def levels(which: int) -> list[str]:
        return [msg for lvl, msg in collector.records if lvl == which]

    # ── 1 真落盘 + 换新对象读回 ──
    good = root / "cfg_good.json"
    writer = ConfigManager(str(good))
    writer.set("merged_key", "merged_value")
    writer.set("number", 42)
    writer.save()
    onDisk = json.loads(good.read_text(encoding="utf-8"))
    print(f"1 save 落盘内容：{onDisk}")
    if onDisk != {"merged_key": "merged_value", "number": 42}:
        failures.append(f"落盘文件里不是那份配置：{onDisk}")
    reader = ConfigManager(str(good))
    reader.load()
    if reader.get("merged_key") != "merged_value" or reader.get("number") != 42:
        failures.append("换新对象 load 读不回落盘的那份值")

    # ── 4 反向对照先跑：完好文件不得报 warning/error ──
    collector.records.clear()
    reader.load()
    noise = levels(logging.WARNING) + levels(logging.ERROR)
    print(f"4 完好文件再 load 产生的告警条数：{len(noise)} {noise}")
    if noise:
        failures.append(f"完好文件上 load 也在报警：{noise}——第 2 条的判据因此不可信")

    # ── 2 损坏文件：warning 而非 error，内存不丢 ──
    collector.records.clear()
    broken = root / "cfg_broken.json"
    broken.write_text("{not json", encoding="utf-8")
    victim = ConfigManager(str(broken))
    victim.set("keep_me", "keep_value")
    victim.load()
    warns, errs = levels(logging.WARNING), levels(logging.ERROR)
    print(f"2 损坏件 load：warning {len(warns)} 条 {warns} / error {len(errs)} 条 {errs}")
    if not warns:
        failures.append("可降级的读取失败被抹平成一律 error（并过来的那格分级没了）")
    if errs:
        failures.append(f"同一场可恢复失败还额外记了 error：{errs}")
    if victim.get("keep_me") != "keep_value":
        failures.append("load 失败把内存里已有的配置也丢了")

    # ── 3 真写盘失败：父路径是个已存在的文件 ──
    collector.records.clear()
    blocker = root / "blocker.json"
    blocker.write_text("{}", encoding="utf-8")
    failing = ConfigManager(str(blocker / "sub" / "config.json"))
    failing.set("k", "v")
    try:
        failing.save()
    except Exception as e:  # noqa: BLE001 - 本条就是来看它崩不崩的
        failures.append(f"写盘失败把异常抛到了调用方：{type(e).__name__}: {e}")
    errs = levels(logging.ERROR)
    print(f"3 写盘失败：error {len(errs)} 条 {errs}")
    if not errs:
        failures.append("数据没落盘却只字不报——用户配置丢失无人知道")

    # ── 5 真启动：改的是被 9 个生产文件读着的模块 ──
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        status = client.get("/api/v1/health").status_code
        print(f"5 create_app 真启动后 /api/v1/health → {status}")
        if status != 200:
            failures.append(f"真栈起不来或健康检查不是 200：{status}")

    cfgLogger.removeHandler(collector)
    if failures:
        print("\nFAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("\nPASS：读写往返、降级分级、失败可见、真启动四段都在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
