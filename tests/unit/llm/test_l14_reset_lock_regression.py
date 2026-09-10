"""M-?/L-14 回归测试：reset() 必须用 _multi_model_clients_lock 保护 _multi_model_clients 清理。

红绿：无修复时 reset() 在 cls._lock 块外（即不用 _multi_model_clients_lock）
清空 _multi_model_clients，与 get_multi_model_client 形成双锁竞态（L-14 根因）。
测试用录制锁替换 _multi_model_clients_lock，断言 reset() 期间该锁的 __enter__ 被调用。
修复前（清理由 cls._lock 之外执行）→ 录制锁 __enter__ 不被调用 → 断言失败（红）；修复后→绿。
"""

from unittest.mock import MagicMock, patch

import neurova.llm.multi_model_client as mmc
from neurova.llm.multi_model_client import MultiModelLLMClient


def test_l14_reset_clears_under_shared_lock():
    recorder = MagicMock()
    recorder.__enter__ = MagicMock(return_value=recorder)
    recorder.__exit__ = MagicMock(return_value=False)

    # reset() 末尾会调用 reset_provider_manager，用 no-op 避免重量级副作用
    with patch.object(mmc, "_multi_model_clients_lock", recorder), \
         patch("neurova.llm.provider_manager.reset_provider_manager"):
        MultiModelLLMClient.reset()

    assert recorder.__enter__.called, (
        "L-14: reset() 必须用 _multi_model_clients_lock 保护 "
        "_multi_model_clients 的清理，避免与 get_multi_model_client 双锁竞态"
    )
