"""401 必须自带自救入口（C1 写侧要凭证后的直接后果）。

C1 把记忆面写类请求收成"必须有可验证身份"后，CLI 上原先匿名就能通的
`/memory save`、`/knowledge add`、`/session del` 等命令第一次开始回 401。
后端此时给的是 FastAPI 标准信封 `{"detail": "Not authenticated"}`——对
浏览器用户有意义（界面上有登录框），对 REPL 用户是一句死路：他不知道
`/login` 能救，只会以为"后端坏了"。

判据钉的是**这条消息在 CLI 侧变成什么**，不是后端契约：
- 401 时把服务端原文保留（不抹除，教义第 2 条），再补一条可执行动作；
- 只补 401，其他状态码一字不改——403/404/409 的可自救动作各不相同，
  在此统一加话术就是替别人编理由。
"""

import importlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _loadCli():
    """导入仓库根的 `cli`（顶层脚本，不是包）。

    `cli.py` 住在仓库根、本身不是一个包，所以常规 import 会把编译产物写到
    `__pycache__/cli.*.pyc` —— 那正是仓库根顶层条目，`tests/conftest.py` 的
    `_guardRepoRootAgainstPollution` 会当场点名肇事用例（2026-10-12 CI 实测报
    `['__pycache__']`）。写盘已由 `tests/conftest.py` 在导入期统一关掉
    （`sys.dont_write_bytecode`），本处不再各写一份开关。
    """
    return importlib.import_module("cli")


class TestFourOhOneSelfRescueHint(unittest.TestCase):
    def test_unauthenticated_401_names_the_login_command(self):
        _loadCli()
        from cli import _error_message

        message = _error_message(401, {"detail": "Not authenticated"})
        # 服务端原文必须还在：抹掉它就没法区分"没带凭证"与"凭证无效"
        self.assertIn("Not authenticated", message)
        self.assertIn("/login", message)

    def test_invalid_token_401_also_points_at_login(self):
        _loadCli()
        from cli import _error_message

        message = _error_message(401, {"detail": "Invalid or expired token"})
        self.assertIn("Invalid or expired token", message)
        self.assertIn("/login", message)

    def test_hint_is_added_once_not_duplicated(self):
        _loadCli()
        from cli import _error_message

        # 信封形态（{code,message}）与 detail 形态都要补，但只能补一次
        envelope = _error_message(401, {"code": 401, "message": "未认证"})
        self.assertEqual(envelope.count("/login"), 1)

    def test_other_status_codes_keep_message_untouched(self):
        _loadCli()
        from cli import _error_message

        # 教义第 2 条的反向钉：改错误封装只能加自救入口，不许顺手改写别的码
        self.assertEqual(_error_message(403, {"detail": "权限不足"}), "权限不足")
        self.assertEqual(_error_message(404, {"detail": "not found"}), "not found")
        self.assertEqual(_error_message(409, {"code": 409, "message": "冲突"}), "[409] 冲突")
        self.assertEqual(_error_message(500, {}), "HTTP 500")


if __name__ == "__main__":
    unittest.main()
