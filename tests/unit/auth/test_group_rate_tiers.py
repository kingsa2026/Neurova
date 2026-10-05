# -*- coding: utf-8 -*-
"""组档位表的新数值（接线即执行，故必须逐档钉住）

接线前这五档只写不读；从本批起它们就是人用渠道的真额度。数值刻意**不低于**限流
中间件此前实际在执行的 120/分（访客档除外），否则收口等于给存量用户当场断流。
"""

from neurova.auth.user_group_model import (
    create_admin_group,
    create_developer_group,
    create_guest_group,
    create_super_admin_group,
    create_user_group,
)


def _minutes(group):
    return group.resource_quota.max_requests_per_minute


def test_tier_table():
    assert _minutes(create_guest_group()) == 30
    assert _minutes(create_user_group()) == 120
    assert _minutes(create_developer_group()) == 300
    assert _minutes(create_admin_group()) == 600
    assert _minutes(create_super_admin_group()) == 1200


def test_tiers_are_monotonic():
    ladder = [
        _minutes(create_guest_group()),
        _minutes(create_user_group()),
        _minutes(create_developer_group()),
        _minutes(create_admin_group()),
        _minutes(create_super_admin_group()),
    ]
    assert ladder == sorted(ladder) and len(set(ladder)) == len(ladder)


def test_general_tier_is_not_below_the_enforced_baseline():
    """普通用户档不得低于中间件此前实际执行的 120，否则接线即当场收紧。"""
    assert _minutes(create_user_group()) >= 120
