# -*- coding: utf-8 -*-
"""活体自证（§6-116）：singleton 收敛网的两份清单逐条在**真进程**里对得上实现。

单元测试那档只做 AST 结构断言（函数体里有没有 `with ...Lock`），它有一个前提没人验过：
**条目指向的文件与符号还在**。2026-09-21 的 `0c333a76` 退役了 `memory_field.py`，条目没跟，
于是那一格 FileNotFoundError 红了 18 天——而红的那格挡不住任何东西，同档其余 9 格真检查反倒
被这层"已知红"噪声淹掉。

本脚本把"清单对得上现实"做成运行时读数，而不是又一轮 grep：

1. 逐条 `importlib.import_module` 真导入，再取 `getattr(mod, factory)` 断其可调用——
   这走的是 Python 的解析路径，比"文件里有一行 def"更能证明"这个名字在生产路上取得到"；
2. 被摘掉的那条必须在真进程里**取不到**（模块 ImportError、包属性也没有），否则说明
   本批只是在消音一条真检查，而不是它指向的东西确实没了；
3. 反向对照：清单里若混进一条假条目（指向不存在的文件），探测器必须报警——与单测
   `TestListsPointAtLiveImplementations::test_staleDetectorRejectsADanglingEntry` 同源，
   这里在真进程侧再走一遍。

跑法（仓根）：PYTHONPATH=. .venv/Scripts/python.exe tests/manual/singletonListFacesLive.py
"""
from __future__ import annotations

import sys
from tests.ast_scan import parseSource


def main() -> int:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()

    import ast

    # 清单从判据文件里读，不在这儿抄第二份（教义第 6 条：口径只允许一处定义）
    judge = repo / "tests/unit/core/test_singleton_convergence.py"
    tree = parseSource(judge.read_text(encoding="utf-8"))
    lists: dict[str, list] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            lists[node.targets[0].id] = [
                (el.elts[0].value, el.elts[1].value)
                for el in node.value.elts
                if isinstance(el, ast.Tuple)
            ]
    pairs = lists["HIGH_RISK_SINGLETONS"] + lists["BENIGN_SINGLETONS"]
    print(f"1 读到两份清单共 {len(pairs)} 条（HIGH_RISK {len(lists['HIGH_RISK_SINGLETONS'])} / "
          f"BENIGN {len(lists['BENIGN_SINGLETONS'])}）")

    failures: list[str] = []
    for rel, factory in pairs:
        modName = rel[:-3].replace("/", ".")
        try:
            mod = __import__(modName, fromlist=["*"])
        except Exception as e:
            failures.append(f"{rel}::{factory} 真导入失败：{type(e).__name__}: {e}")
            continue
        target = getattr(mod, factory, None)
        if not callable(target):
            failures.append(f"{rel}::{factory} 取不到可调用工厂（条目已陈旧）")
        else:
            print(f"   ok {rel}::{factory}")

    # 被摘掉那条必须在真进程里取不到——否则本批是消音而非纠陈旧
    import importlib
    import importlib.util

    try:
        importlib.import_module("neurova.cognitive_layers.memory_layer.memory_field")
        failures.append("`memory_field` 竟然还能导入：条目不该被摘")
    except ModuleNotFoundError as e:
        print(f"2 已退役那侧真取不到：ModuleNotFoundError（{e}）")
    import neurova.cognitive_layers.memory_layer as pkg
    if hasattr(pkg, "get_memory_field"):
        failures.append("包里仍暴露 get_memory_field，摘掉条目等于少了一条检查")

    # 反向对照：假条目必须报警（探测器与判据同源，这里按真模块加载取函数，不抄第二份）
    spec = importlib.util.spec_from_file_location("_singletonJudge", judge)
    ns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ns)
    if not ns._staleEntries([("neurova/no_such_module_zz.py", "get_x")]):
        failures.append("探测器对不存在的文件不报警——它已经坏了")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(" -", f)
        return 1
    print(f"\nPASS：清单 {len(pairs)} 条全部在真进程里对得上实现，退役那条已确认取不到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
