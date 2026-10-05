# -*- coding: utf-8 -*-
"""把用户组档位折算成 firewall 的人用渠道每分钟额度。

放在 API 层而非 `core.firewall`：`auth.user_group_model` 反向依赖
`core.logger`/`core.data_root`，让 core 去 import auth 即成环。firewall 因此只接受
一个 resolver 注入，由本模块在装配点提供。

额度取**所属组的并集最宽值**（entitlement 语义：就高不就低）；一个组都没有时返回
None，由 firewall 回落全局默认——不能把"查不到"当成 0 把人全拒。
"""

from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def _manager():
    from neurova.auth.user_group_model import get_user_group_manager

    return get_user_group_manager()


def groupRatePerMinute(username: Optional[str]) -> Optional[int]:
    """解析该登录名的组档位每分钟额度；无组/无身份/解析失败一律返回 None。"""
    if not username:
        return None

    try:
        groups = _manager().get_groups_for_user(username)
    except Exception as e:  # 查库失败不得把请求拒掉，回落默认档
        logger.warning("组档位解析失败，回落默认额度: user=%s err=%s", username, e)
        return None

    rates = [
        getattr(getattr(group, "resource_quota", None), "max_requests_per_minute", None)
        for group in groups or []
    ]
    rates = [rate for rate in rates if isinstance(rate, int) and rate > 0]
    if not rates:
        return None

    return max(rates)
