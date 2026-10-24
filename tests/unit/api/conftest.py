# -*- coding: utf-8 -*-
"""`tests/unit/api` 的共用隔离：移动在册设备库不得写进仓内 `data/`。

为什么放在 conftest 而不是各文件自己抄一遍：在册库是 §4.8 新落地的**持久**权威，
凡是打到 `/mobile/*` 这些口的判据都会真的开一条 SQLite。仓根的逐用例污染守卫
**只盯仓库顶层条目**，`data/` 内部它看不见（AGENTS/流水线都记过这一条），
于是"跑测把设备行写进真库"是一件不会有任何人报错的事——每条判据自己拼一次路径，
漏一条就是污染，且拼错也不报错（教义第 6 条点名的手抄形态）。

单点做法：把 `mobile_pairing.deviceStorePath()` 重定向到本用例的 tmp 目录，
前后各释放一次单例。用例内不需要知道库在哪。
"""
import pytest


@pytest.fixture(autouse=True)
def _isolateMobilePairingGlobals(tmp_path, monkeypatch):
    """`/mobile/*` 用到的**模块级全局状态**在这里一次清干净，各档不自己抄一遍。

    两件事都必须是单点：

    - 在册库路径：§4.8 之后它是持久权威，任何打到这些口的判据都会真开一条 SQLite。
      仓根污染守卫只盯仓库顶层条目，`data/` 内部它看不见——不重定向就是写进真库，
      而且没有任何人会报错。
    - `confirm` 的每 IP 限流桶（5 次/300s）：它是模块 dict，跨文件不会自己过期。
      实测形态是「前一档配了 3 次，后一档拿 429 当业务失败」，
      报错落在与根因无关的地方（本卷形态 396：抄既有夹具会继承它的跨档污染）。
    """
    from neurova.api.endpoints import mobile_pairing as mp

    monkeypatch.setattr(mp, "deviceStorePath",
                        lambda: str(tmp_path / "mobile_devices.db"))
    mp.resetDeviceRegistry()
    mp._confirm_attempts.clear()
    yield
    mp._confirm_attempts.clear()
    mp.resetDeviceRegistry()
