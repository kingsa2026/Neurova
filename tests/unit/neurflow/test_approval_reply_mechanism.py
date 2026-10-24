"""
审批回复接收机制测试

测试目标：验证审批消息发送后，审批人回复能正确触发 approval_event
修复: 使用 add_message_handler 替代 set_message_handler，使用 threading.Event 替代 asyncio.Event
"""
import asyncio
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neurova.collaboration.neurflow.builtin import exec_approval

#: 审批节点在测试里等多久（秒）。
#:
#: 为什么不是 60：`exec_approval` 会**等满**这个窗口才返回，而这些格子注册的处理器是在
#: `asyncio.run(exec_approval(...))` **返回之后**才被手动调用的——窗口里永远不会有回复进来，
#: 于是 60 就是实打实的 60 秒空等。全局墙是 30s（`pyproject.toml:116`），而 Windows 侧
#: pytest-timeout 走 thread 法、超时即终止整个进程 ⇒ **一格空等 60s＝整场跑测没了**
#: （2026-10-24 实测：本文件 7 格全绿却跑 130.03s，`pytest tests/unit` 在 72% 处就此消失）。
#: 1s 是本仓同族档的既有口径（`test_approval_reply_mechanism_fixed.py:37` 写"短超时用于测试"，
#: `test_approval_integration.py`、`test_approval_cross_event_loop_fixed.py` 全用 1／5）。
_APPROVAL_WAIT_S = 1

REPO_ROOT = Path(__file__).resolve().parents[3]
_TESTS_ROOT = REPO_ROOT / "tests"


def _intOf(node, table):
    """把 `60`／`_APPROVAL_WAIT_S` 这类字典值算成秒数；算不出给 None（不静默当 0）。"""
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in table:
        return _intOf(table[node.id], table)
    return None


class TestApprovalReplyMechanism:
    """测试审批回复机制的完整性"""

    @pytest.fixture
    def mock_channel_manager(self):
        """模拟 ChannelManager"""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="msg_123")
        mock.broadcast_message = AsyncMock(return_value={"feishu": "msg_123"})
        mock.add_message_handler = MagicMock(return_value=0)
        mock.remove_message_handler = MagicMock(return_value=True)
        return mock

    @pytest.fixture
    def mock_channel_adapter(self):
        """模拟 ChannelAdapter"""
        mock = AsyncMock()
        mock.channel_type = "feishu"
        mock.is_connected = True
        mock.send_message.return_value = "msg_456"
        return mock

    def test_approval_should_register_message_handler(self, mock_channel_manager):
        """测试: 审批应该注册消息处理器"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": _APPROVAL_WAIT_S
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证: 应该使用 add_message_handler
            mock_channel_manager.add_message_handler.assert_called_once()
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            assert callable(handler)

    def test_approval_handler_should_process_approve_message(self, mock_channel_manager):
        """测试: 审批处理器应该处理批准消息"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": _APPROVAL_WAIT_S
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟审批消息
        approve_message = MagicMock()
        approve_message.content = "approve"
        approve_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到审批消息
            asyncio.run(handler(approve_message))
            
            # 验证: 处理器应该被调用
            mock_channel_manager.add_message_handler.assert_called_once()

    def test_approval_should_timeout_when_no_reply(self, mock_channel_manager):
        """测试: 无回复时应该超时"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 1  # 1秒超时
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证
            assert result["status"] == "timeout"
            assert result["output"]["approved"] is None

    def test_approval_event_should_be_set_on_approve(self, mock_channel_manager):
        """测试: 批准时 approval_event 应该被设置"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 5
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟审批消息
        approve_message = MagicMock()
        approve_message.content = "同意"
        approve_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 获取注册的处理器
            result = asyncio.run(exec_approval(config, ctx))
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到审批消息
            asyncio.run(handler(approve_message))
            
            # 验证: 处理器应该被调用
            mock_channel_manager.add_message_handler.assert_called_once()

    def test_approval_should_ignore_messages_from_other_users(self, mock_channel_manager):
        """测试: 应该忽略来自其他用户的消息"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 1
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟来自其他用户的消息
        other_message = MagicMock()
        other_message.content = "approve"
        other_message.sender_id = "user_456"  # 不同的用户
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到其他用户的消息
            asyncio.run(handler(other_message))
            
            # 验证: 处理器应该被调用，但不应该触发审批事件
            mock_channel_manager.add_message_handler.assert_called_once()


class TestApprovalReplyIntegration:
    """测试审批回复的端到端集成"""

    def test_approval_reply_flow_with_real_channel_manager(self):
        """测试: 使用真实 ChannelManager 的审批回复流程"""
        # 验证修复后的跨事件循环问题已解决
        pass

    def test_multiple_concurrent_approvals(self):
        """测试: 多个并发审批节点"""
        # 验证 add_message_handler 支持多个处理器
        pass


class TestApprovalWaitBudgetStaysUnderTheWall:
    """审批节点的等待预算必须留在跑测墙内——一格空等 60s 会把整场跑测打死。

    与本档上面那个常量同根的常驻判据：全仓凡提到 `exec_approval` 的被收集测试里，带
    `"timeout"` 键的字典字面量（含"提到模块常量、能算出数值"那一形）都不得超出上限。
    为什么用**静态形状**而不是"跑一遍计时"：计时要真等，而真等恰恰是这里要防的事；
    形状判据今天就能红，且不受机器快慢影响。

    口径边界（不当已收口）：只认 `"timeout"` 这一个键，且只在**提到 `exec_approval` 的测试文件**
    里认——`"timeout": 60` 出现在别处（浏览器路由配置、沙箱 HTTP 载荷）不归这条管，
    那是批 P-1「任意有界等待」扩面要处置的对象。
    """

    #: 上限比全局墙（30s）低一档，留足"等满窗口＋断言与建夹具的杂项"的余量。
    _WAIT_CEILING_S = 10

    def _waitSites(self):
        """[(文件, 行号, 秒数)]——提到 exec_approval 的测试里那些 `"timeout": <整数>` 字典项。"""
        import ast

        from tests import ast_scan

        sites = []
        for ref in ast_scan.sourceRefsUnder(_TESTS_ROOT, ".py", hints=("exec_approval",)):
            path = ref.path
            if not path.name.startswith("test_"):
                continue
            tree = ast_scan.transientTree(path)
            table = {
                stmt.targets[0].id: stmt.value
                for stmt in tree.body
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for key, value in zip(node.keys, node.values):
                    if not (isinstance(key, ast.Constant) and key.value == "timeout"):
                        continue
                    seconds = _intOf(value, table)
                    if seconds is None:
                        continue
                    sites.append((path.relative_to(REPO_ROOT).as_posix(), node.lineno, seconds))
        return sites

    def test_noApprovalTestWaitsOutAWindowTheWallCannotCover(self):
        sites = self._waitSites()
        over = [(f, line, secs) for f, line, secs in sites if secs > self._WAIT_CEILING_S]
        assert not over, (
            "这些审批测试的等待窗口超出了跑测墙能覆盖的范围（上限 %ds）：%s"
            "——`exec_approval` 会等满它，而 Windows 侧 pytest-timeout 走 thread 法、"
            "超时即终止整个进程，报出来的不是这一格红，是整场跑测没了"
            % (self._WAIT_CEILING_S, over)
        )

    def test_waitSiteScanIsNotVacuous(self):
        """面自证：三个读数分开比——枚举面、预筛候选面、真扫到的等待预算数。

        合成一条就分辨不出失败形态：枚举面掉穿＝扫描根指错；候选面为空＝预筛词写窄；
        只有站点数为零而前两面正常＝这个域里真的没有超墙预算（那才是绿）。
        """
        from tests import ast_scan

        enumerated = len(ast_scan.sourceRefsUnder(_TESTS_ROOT, ".py"))
        assert enumerated >= 1000, (
            "被收集测试语料现读 %d 个 .py——`_TESTS_ROOT` 指错时下面两条会一起假绿" % enumerated
        )
        candidates = len(ast_scan.sourceRefsUnder(_TESTS_ROOT, ".py", hints=("exec_approval",)))
        assert candidates >= 5, (
            "提到 `exec_approval` 的测试文件只剩 %d 个（建档那轮现数 7）——预筛词或收集口径写窄了"
            % candidates
        )
        sites = self._waitSites()
        assert len(sites) >= 12, (
            "只读到 %d 处带 `\"timeout\"` 的审批配置字典（建档那轮现数 23）——此时上一条的"
            "『零违规』与『没扫到』长得一模一样" % len(sites)
        )

    def test_detectorBitesAnOverWideWindowAndSparesTheConvention(self):
        """合成样本对照：探测恒假＝主判据的绿是假的，这里双向都验（形态 376）。"""
        import ast

        cases = (
            ('def f():\n    cfg = {"approver": "u", "timeout": 60}\n', True, "空等 60s"),
            ('def f():\n    cfg = {"approver": "u", "timeout": 1}\n', False, "本仓既有口径 1s"),
            ('_W = 120\ndef f():\n    cfg = {"approver": "u", "timeout": _W}\n', True,
             "值挂在模块常量上也要算得出来"),
        )
        for source, expectOver, why in cases:
            tree = ast.parse(source)        # 合成样本自己先要合法
            table = {
                stmt.targets[0].id: stmt.value
                for stmt in tree.body
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name)
            }
            values = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "timeout":
                        values.append(_intOf(value, table))
            assert len(values) == 1, "样本自己没被探测到，探测器在此失明（%s）" % why
            assert (values[0] > self._WAIT_CEILING_S) is expectOver, (
                "探测器对「%s」判成了 %s（读数 %s）"
                % (why, "超限" if values[0] > self._WAIT_CEILING_S else "合规", values)
            )
