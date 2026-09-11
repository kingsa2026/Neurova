"""C-21 / 台账 #4 防回归：channels 层不得再有 mobile_pairing 重复实现。

历史：neurova/channels/mobile_pairing.py 与 neurova/api/endpoints/mobile_pairing.py
双实现（资源型修复登记台账 2026-09-11 #4）——channels 版经全仓 grep 复核为
零运行时消费方（仅测试导入），已于 2026-09-11 删除。

本文件原为 channels 版 MobilePairingManager 的线程安全回归测试；实现删除后
转为防复活断言。线程安全/有界撤销表/安全随机码等行为回归由存活的
api/endpoints 实现及其测试（tests/unit/api/test_mobile_pairing_*.py）承接。
"""

import importlib
import sys
from pathlib import Path

import pytest

import neurova.channels

_CHANNELS_MP_PATH = Path(neurova.channels.__file__).resolve().parent / "mobile_pairing.py"


def test_channels_mobile_pairing_file_removed():
    """文件级防复活：channels/mobile_pairing.py 不得重新出现"""
    assert not _CHANNELS_MP_PATH.exists(), (
        "channels/mobile_pairing.py 复活——与 api/endpoints/mobile_pairing.py 双实现回归（台账 #4）"
    )


def test_channels_mobile_pairing_import_fails():
    """模块级防复活：即使文件被意外恢复，导入语义也必须走 api/endpoints 版本"""
    sys.modules.pop("neurova.channels.mobile_pairing", None)
    with pytest.raises(ImportError):
        importlib.import_module("neurova.channels.mobile_pairing")
