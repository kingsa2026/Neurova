"""P1-4：通知的管理员/全员枚举必须取真实账号源（红→绿）

修复前缺陷：`notifications.py:85/121` 伸手拿 `enhanced_users_api._users_store`——那是一个
**进程内字典、从不播种**（只有该 router 自己 POST 过才有内容），真账号在 `users.db`
（`auth/user_model.py`，`role` 列）。于是 `notify_admins()` 每次都枚举到空集，落到
`["default"]` 兜底：知识共享审批、市场提交、调度器失败这些**本应通知管理员**的事件，
全部写进 anonymous 共享桶——既没送达真管理员，又把管理员可见内容放进了跨租户可读的面。

处置：枚举改走身份链同一事实源 `UserModel`（`list_users(role=, status=)`，与 JWT 的
`sub`/`user_id` 同为账号 id）；`enhanced_users_api._users_store` 那两处旁路读删除。
单机零账号时的 `default` 兜底语义**保留并钉住**，不借本条把它偷偷改掉。
"""

from pathlib import Path
from typing import List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def realUsers(tmp_path, monkeypatch):
    """把数据根与通知落点都指到本用例的临时目录，用生产入口写真账号。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))

    from neurova.notifications.manager import reset_notification_manager

    reset_notification_manager()
    try:
        from neurova.auth.user_model import UserModel

        model = UserModel()
        admin = model.create_user(
            username="root_admin", password_hash="x", email=None, role="admin", status="active"
        )
        peer = model.create_user(
            username="plain_user", password_hash="x", email=None, role="user", status="active"
        )
        yield {"admin": str(admin.id), "peer": str(peer.id), "model": model}
    finally:
        reset_notification_manager()


def _notificationsByUser(storagePath: Path) -> dict:
    """按 user_id 归堆。存储形状是 {"notifications": {id: {...}}}（dict 不是 list）。"""
    import json

    if not storagePath.exists():
        return {}
    payload = json.loads(storagePath.read_text(encoding="utf-8"))
    rows = payload.get("notifications", {})
    if isinstance(rows, dict):
        rows = list(rows.values())
    byUser: dict = {}
    for row in rows:
        byUser.setdefault(str(row.get("user_id")), []).append(row.get("title"))
    return byUser


def testAdminEnumerationUsesTheRealAccountSource(realUsers, tmp_path):
    from neurova.api.endpoints import notifications

    assert notifications._admin_user_ids() == [realUsers["admin"]], (
        "管理员枚举没取到真账号源——notify_admins 会全体落进 default 共享桶"
    )


def testNotifyAdminsDeliversToAdminNotDefaultBucket(realUsers, tmp_path):
    from neurova.api.endpoints import notifications

    sent = notifications.notify_admins("审批待处理", "有人提交了知识共享")

    byUser = _notificationsByUser(tmp_path / "notifications.json")
    assert sent == 1, f"应只发给那一名真管理员，实际 {sent}"
    assert realUsers["admin"] in byUser, f"管理员没收到通知：{byUser}"
    assert "default" not in byUser, "真管理员在场却还兜底进 default 桶"


def testNotifyAllUsersFansOutToEveryAccount(realUsers, tmp_path):
    from neurova.api.endpoints import notifications

    sent = notifications.notify_all_users("系统维护", "今晚 22:00 重启")

    byUser = _notificationsByUser(tmp_path / "notifications.json")
    assert sent == 2, f"两个账号都该收到，实际 {sent}"
    assert set(byUser) == {realUsers["admin"], realUsers["peer"]}, byUser


def testZeroAccountDeploymentStillFallsBackToDefault(tmp_path, monkeypatch):
    """零账号（全新单机部署）保留 default 兜底——这条语义不许被顺手改掉。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    from neurova.notifications.manager import reset_notification_manager

    reset_notification_manager()
    try:
        from neurova.api.endpoints import notifications

        assert notifications._admin_user_ids() == []
        assert notifications.notify_admins("标题", "正文") == 1
        assert "default" in _notificationsByUser(tmp_path / "notifications.json")
    finally:
        reset_notification_manager()


def _usersStoreAccesses(source: str) -> List[str]:
    """抽出代码里对 `_users_store` 的**属性取用**（AST 形态，注释与说明文字不算）。"""
    import ast

    tree = ast.parse(source)
    return [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "_users_store"
    ]


def testInMemoryStubIsNoLongerRead():
    """防回流：通知域不得再伸手另一套进程内用户字典。

    判据按 AST 的属性取用形态判，不按字符串比对——本文件与生产码的说明文字都会
    提到 `_users_store`，钉词会自己把自己钉红（本轮已撞过一次）。
    """
    target = REPO_ROOT / "neurova" / "api" / "endpoints" / "notifications.py"
    accesses = _usersStoreAccesses(target.read_text(encoding="utf-8"))
    assert not accesses, (
        f"又去读 enhanced_users_api._users_store（{len(accesses)} 处）——那是从不播种的"
        "进程内字典，读它等于永远枚举不到真账号"
    )


def testGuardHasTeethOnInjectedAccess():
    """判据自证：注入一处属性取用必须被抓到，否则这条守卫是空转的。"""
    probe = "from neurova.api.endpoints import enhanced_users_api as m\n" \
            "store = m._users_store\n"
    assert len(_usersStoreAccesses(probe)) == 1, "守卫抓不到注入的取用点——它已经空转"
