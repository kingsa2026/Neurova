"""memory_layer 的 torch 依赖防回归（内存优化 H1 的现行契约）。

契约的**来历**（2026-09-08 内存分析报告 H1）：`memory_field.py` 里的 `MemoryFieldConfig`
运行时零消费方，却被包 `__init__` 急切拉入 ⇒ 导入即 +176MB。H1 的当时解法是"惰性化 +
历史 API 仍可用 + 缺 torch 时 fail-soft"，本文件原本三条就是照那个形态写的。

**2026-10-10 复核实状后改对（台账 §6-52 就地更正）**：`memory_field.py` 已在
`0c333a76`（温度衰减双实现收敛）整模块退役，`MemoryFieldConfig` 全仓再无定义，
本包内 `import torch` **一处也没有**（连惰性形态都不剩）。于是原第 2 条断言的红
是"前提已死"，原第 3 条更坏——符号不存在时 `AttributeError` 恒成立，
**那条格在当前代码下根本不可能失败**（恒绿的假断言，比红更需要处理）。
现行三条各自可失败：

1. 运行时面：导入本包任一子模块不得把 torch 拉进 `sys.modules`；
2. 退役面：`memory_field.py` 与 `MemoryFieldConfig` 不得复活——复活就是往回搬那座
   零消费方的 torch 依赖，必须先重新判它急不急切；
3. 静态面：本包源码内 `import torch` 必须仍为 0 处（含函数内惰性写法）。
"""

import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[4] / 'neurova' / 'cognitive_layers' / 'memory_layer'


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True, timeout=300
    )


def test_import_submodule_does_not_load_torch():
    r = _run(
        'import neurova.cognitive_layers.memory_layer.unified_vector_store, sys; '
        "assert 'torch' not in sys.modules, 'torch 被包 __init__ 急切拉入'"
    )
    assert r.returncode == 0, r.stderr


def test_retiredMemoryFieldFaceDoesNotComeBack():
    """反向存在断言：那座零消费方的 torch 载体退役后不许被悄悄搬回来。"""
    retiredFile = PACKAGE_DIR / 'memory_field.py'
    assert not retiredFile.is_file(), (
        'memory_field.py 又回到包里了（它随 `0c333a76` 整模块退役）——'
        '要搬回来先重判它是否急切拉 torch，并同步改本文件与台账 §6-52')

    r = _run(
        'import neurova.cognitive_layers.memory_layer as ml, sys; '
        "assert not hasattr(ml, 'MemoryFieldConfig'), 'MemoryFieldConfig 复活'; "
        "print('retired')"
    )
    assert r.returncode == 0 and 'retired' in r.stdout, r.stderr


def _torchImportSites(dirPath: Path) -> list:
    """按**形态**取形：注释行不算，函数内的惰性 `import torch` 也算。"""
    offenders = []
    for path in sorted(Path(dirPath).rglob('*.py')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if ('import torch' in stripped) or ('torch.' in stripped and 'import' in stripped):
                offenders.append('%s:%d %s' % (path.name, lineno, stripped[:60]))
    return offenders


def test_noTorchImportAnywhereInPackage():
    """静态面：本包不得再出现任何 torch 导入形态（函数内的惰性写法也算）。

    取代原先那条"缺 torch 时 fail-soft"的断言——符号已不存在，那条在当前代码下
    永远不会失败（AttributeError 由符号缺失给出，与 torch 无关），留着就是一枚
    看起来在守、其实不判事的恒绿格（台账 §6-52、判据形态清单同族）。
    """
    scanned = list(PACKAGE_DIR.rglob('*.py'))
    assert len(scanned) > 40, (
        '扫描面收缩到 %d 个文件——这条守卫已经在扫一个空/半空目录，'
        '它的绿不代表任何事（先修路径，别急着高兴）' % len(scanned))

    offenders = _torchImportSites(PACKAGE_DIR)
    assert not offenders, (
        'memory_layer 里出现了 torch 导入（H1 的结论是这座依赖零消费方、已整块退役）：\n  '
        + '\n  '.join(offenders))


def test_detectorReallyFindsALazyTorchImport(tmp_path):
    """反空转：藏在函数里的惰性写法必须被抓到，注释里的字样不许被误报。"""
    sample = tmp_path / 'lazy_offender.py'
    sample.write_text(
        '# 注释里提到 import torch 不算命中\n'
        'def heavy():\n'
        '    import torch  # 惰性也要被数出来\n'
        '    return torch.cuda.is_available()\n',
        encoding='utf-8')

    sites = _torchImportSites(tmp_path)
    assert len(sites) == 1 and ':3 ' in sites[0], (
        '探测器漏了惰性写法或把注释误报成命中（命中行应为第 3 行）：%s' % sites)
