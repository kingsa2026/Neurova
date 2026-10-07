"""测试夹具：在隔离数据根里建**真账号**。

通知域的管理员/全员枚举只认真账号源（`auth/user_model.UserModel`，即 JWT `sub`/`user_id`
那张表）。过去这些用例靠 `monkeypatch.setattr(enhanced_users_api, "_users_store", {...})`
"声明有个管理员"——那份字典从不播种，生产里根本枚举不到人，所以这种注入把测试钉在
一个假契约上（改真源后当场失效）。要测"通知真的发给管理员"，就得建真账号。
"""

from pathlib import Path
from typing import Dict

from neurova.auth.user_model import UserModel

DEFAULT_ACCOUNTS = (("rootadmin", "admin"), ("alice", "user"))


def seedAccounts(monkeypatch, tmp_path, accounts=DEFAULT_ACCOUNTS) -> Dict[str, str]:
    """把数据根指到本用例临时目录并建出账号，返回 `{username: user_id(str)}`。"""
    root = _isolateDataRoot(monkeypatch, tmp_path)
    model = UserModel()
    ids: Dict[str, str] = {}
    for username, role in accounts:
        existing = model.get_user_by_username(username)
        user = existing or model.create_user(
            username=username,
            password_hash="not-used-in-notification-tests",
            email=None,
            role=role,
            status="active",
        )
        ids[username] = str(user.id)
    return ids


def isolateNoAccounts(monkeypatch, tmp_path) -> None:
    """把数据根指到一个**零账号**的临时目录。

    给"无注册管理员时兜底 default"这类断言用：它成立的前提是部署里确实没有账号，
    而不是"枚举源恰好是空的"。不隔离时它会读到仓内 `data/users.db`（今天里面有 admin），
    通知就会发给真人，断言随即失去意义。
    """
    _isolateDataRoot(monkeypatch, tmp_path)


def _isolateDataRoot(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "data_root"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(root))
    return root
