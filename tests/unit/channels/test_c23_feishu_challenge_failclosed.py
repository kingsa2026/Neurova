"""C-23 回归测试：Feishu verify_url_challenge 必须 fail-closed 校验 token。

缺陷：verify_url_challenge(challenge, token) 接收 token 但完全不使用，
任何人可"验证" webhook。修复：与配置的 verification_token 恒定时间比对；
未配置 token 时拒绝挑战（与 wecom/telegram fail-closed 口径一致）。
"""

import pytest

from neurova.channels.feishu import create_feishu_adapter


@pytest.fixture
def configured_adapter():
    return create_feishu_adapter(
        app_id="cli_x",
        app_secret="s",
        verification_token="token_secret_123",
    )


def test_matching_token_returns_challenge(configured_adapter):
    result = configured_adapter.verify_url_challenge("abc_challenge", "token_secret_123")
    assert result == {"challenge": "abc_challenge"}


def test_wrong_token_rejected(configured_adapter):
    with pytest.raises(ValueError):
        configured_adapter.verify_url_challenge("abc_challenge", "attacker_token")


def test_empty_token_rejected(configured_adapter):
    with pytest.raises(ValueError):
        configured_adapter.verify_url_challenge("abc_challenge", "")


def test_unconfigured_token_fails_closed():
    adapter = create_feishu_adapter(app_id="cli_x", app_secret="s")
    with pytest.raises(ValueError):
        adapter.verify_url_challenge("abc_challenge", "any_token")
