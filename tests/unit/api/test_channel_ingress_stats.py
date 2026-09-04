"""渠道入站队列统计端点测试（P0-5 前端对齐：/channel-configs/ingress/stats）。

契约：裸对象无信封——{"enabled": bool, pending, processing, dead_letter,
processed_total}；队列不可用时 {"enabled": False}（fail-open 直发模式）。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestIngressStatsEndpoint(unittest.TestCase):
    def test_stats_shape_with_queue(self):
        from neurova.api.endpoints.channel_config import ingress_stats

        fake_queue = MagicMock()
        fake_queue.stats.return_value = {
            "pending": 2,
            "processing": 1,
            "dead_letter": 0,
            "processed_total": 42,
        }
        fake_manager = MagicMock()
        fake_manager.ingress_queue = fake_queue

        import neurova.api.endpoints.channel_config as cc

        with unittest.mock.patch.object(cc, "get_channel_manager", return_value=fake_manager):
            result = asyncio_run(ingress_stats())

        self.assertTrue(result["enabled"])
        self.assertEqual(result["pending"], 2)
        self.assertEqual(result["processed_total"], 42)

    def test_stats_disabled_without_queue(self):
        from neurova.api.endpoints.channel_config import ingress_stats

        fake_manager = MagicMock()
        fake_manager.ingress_queue = None

        import neurova.api.endpoints.channel_config as cc

        with unittest.mock.patch.object(cc, "get_channel_manager", return_value=fake_manager):
            result = asyncio_run(ingress_stats())

        self.assertEqual(result, {"enabled": False})


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
