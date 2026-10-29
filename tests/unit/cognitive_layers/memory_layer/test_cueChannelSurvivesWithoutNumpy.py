# -*- coding: utf-8 -*-
"""联想线索通道不得把 numpy 当先决条件（CI 精简锁定刻意不含它）。

**这票为什么在主线重落一次**：原档 `test_cueChannelSurvivesWithoutNumpy.py` 随 `e6596821`
落在一条**后来被丢弃的血统**里（该提交不在任何 ref 上，`git log --all --diff-filter=A` 读不到
它的文件），生产侧的免矩阵修复随后经 MR #369（`fix/embedding-numpy-optional`）并入主线，
但**判据本身没跟着过来**——现算主线没有任何一档在 numpy 缺席下跑过这条通道。
于是"引擎缺席即降级"这句承诺在这一行重新变成无人守的口头话。

形态（构建 `cnb-mt7-1k5l48d6p#003` 实测）：`test_associativeRecallGate.py` 两条 setup 直接
`ModuleNotFoundError: No module named 'numpy'`，而 numpy 正是 `requirements-ci.txt` 头部点名
排除的重依赖。根因在 `CueVectorChannel._build()`：`import numpy` 写在方法体里、没有降级分支，
缺席即整条通道炸。同模块族的两处既有消费点都是「try 导入 / 缺席退回暴力搜索」
（`unified_vector_store._refresh_numpy_matrix` 与 numpy 快路径），本条此前是唯一例外。

本档钉住「矩阵只是加速」：numpy 在当前解释器里**真的不可导入**时，通道照样给候选、
照样把命中计入读数。今天它是**回归闸**（生产侧已修，故现值应绿）——牙齿由变异探针自证：
把 `recall` 里那行逐行余弦换回 `self._vectors @ np.asarray(...)`，本档两格当场红。
"""
import importlib
import sys

import pytest

from neurova.cognitive_layers.memory_layer import association_cue_index as cueIndex

pytestmark = [pytest.mark.timeout(60)]


class _NumpyBlocker:
    """把 numpy 从 import 面里摘掉（比 monkeypatch `sys.modules` 更贴真缺席）。

    只实现 `find_spec`：`find_module` 是已废弃的旧协议，同时实现会让别的导入器在收尾时
    反复调用它，进而把同进程里后续档的导入搅成 `cannot load module more than once per process`
    （实测）。
    """

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] != "numpy":
            return None
        # 返回一个**会抛 ImportError 的 loader**，而不是 None：None 只是"我不认领"，
        # 导入会继续沿 meta_path 往下走，numpy 照样被导进来（本判据就成了空转）。
        import importlib.machinery

        spec = importlib.machinery.ModuleSpec(name, None)
        spec.loader = _MissingLoader()
        return spec


class _MissingLoader:
    def create_module(self, spec):
        raise ImportError("numpy 缺席（本判据刻意如此）")

    def exec_module(self, module):
        raise ImportError("numpy 缺席（本判据刻意如此）")


@pytest.fixture
def withoutNumpy():
    saved = {m: sys.modules.pop(m) for m in list(sys.modules)
             if m.split(".")[0] == "numpy"}
    blocker = _NumpyBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)


def _channel():
    rows = [
        {"cue_text": "部门年会要敬酒怎么办", "memory_id": "mem_a"},
        {"cue_text": "海边度假的防晒准备", "memory_id": "mem_b"},
    ]
    vectors = {"部门年会要敬酒怎么办": [1.0, 0.0], "海边度假的防晒准备": [0.0, 1.0]}
    return cueIndex.CueVectorChannel(
        cueRowsGetter=lambda n: rows,
        encodeOne=lambda text: vectors.get(text),
    )


class TestChannelDoesNotRequireNumpy:
    def test_recallWorksWhenNumpyIsAbsent(self, withoutNumpy):
        with pytest.raises(ImportError):
            importlib.import_module("numpy")  # 自证缺席真的生效，否则本判据空转

        results = _channel().recall([1.0, 0.0], limit=3)
        assert results and results[0][0] == "mem_a", (
            "numpy 缺席时通道给了空结果——矩阵只是加速，不该成为这条通道的前置。"
            f"实际：{results}"
        )
        assert results[0][2] == pytest.approx(1.0), "余弦读数在降级通路里被改坏了"

    def test_statsStillAttributeTheHits(self, withoutNumpy):
        channel = _channel()
        channel.recall([1.0, 0.0], limit=3)
        stats = channel.stats()
        assert stats["indexed"] == 2, f"降级通路没把线索建进索引：{stats}"
        assert stats["injected"] == 1, f"命中没有计入注入读数：{stats}"
