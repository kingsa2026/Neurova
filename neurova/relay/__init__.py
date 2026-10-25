"""可独立部署的中继（`python -m neurova.relay`）。

它**不是** Neurova 后端的一部分：跑在一台有固定域名的机器上，只负责
「持有公网入口 ＋ 把流量接给服务端自己拨出来的那条隧道」。
"""
from neurova.relay.app import RelayState, create_relay_app

__all__ = ["RelayState", "create_relay_app"]
