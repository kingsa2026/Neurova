#!/usr/bin/env python3
"""创建 admin 用户。

四条口径（都是修过的，别再退回去）：
- **落点**走服务端同一解析：`UserModel()` → `callerPath("", "users.db")` → 当前数据根。
  原实现写死 `db_path="data/users.db"`（CWD 相对字面量），`NEUROVA_DATA_DIR` 对它完全不
  生效——设了数据根的部署跑完仍拿不到账号，而账号被写进了运行目录旁的 dev 库。
- **口令**只由 `NEUROVA_ADMIN_PASSWORD` 注入，强度沿用仓内
  `PasswordHasher.is_password_strong`；不内置默认口令，也不把口令写到 stdout。
  没有"tty 交互输入"这条分支：Windows 的 `getpass` 直接读控制台、不看
  `sys.stdin.isatty()`，实测无人值守（stdin 重定向到 NUL）时会把进程挂死在提示符上。
- **口令先校验再动库**：不出现"连库查到一半才要口令"的半途退出。
- **失败以非零退出**：安装脚本打印"失败"却回 0，会被 CI 读成通过。
"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neurova.api.auth import hash_password
from neurova.auth.password_hasher import PasswordHasher
from neurova.auth.user_model import UserModel

PASSWORD_ENV_KEY = "NEUROVA_ADMIN_PASSWORD"


def _resolveAdminPassword() -> str:
    password = (os.environ.get(PASSWORD_ENV_KEY) or "").strip()
    if not password:
        raise SystemExit(
            f"必须经环境变量 {PASSWORD_ENV_KEY} 注入 admin 口令。"
            "本脚本不再内置默认口令，也不把口令打印出来——内置值连同回显等于"
            "把管理员账号公开在仓库里。"
        )
    if not PasswordHasher().is_password_strong(password):
        raise SystemExit("admin 口令强度不足：需 ≥8 位且同时含大小写字母、数字与符号")
    return password


def create_admin_user() -> None:
    password = _resolveAdminPassword()

    user_model = UserModel()

    existing = user_model.get_user_by_username("admin")
    if existing:
        print(f"admin 用户已存在，ID: {existing.id}")
        print(f"用户名: {existing.username}")
        print(f"角色: {existing.role}")
        print(f"状态: {existing.status}")
        print(f"落点: {user_model.db_path}")
        return

    user = user_model.create_user(
        username="admin",
        password_hash=hash_password(password),
        email="admin@neurova.local",
        role="admin",
        status="active",
    )

    print("admin 用户创建成功!")
    print(f"用户ID: {user.id}")
    print(f"用户名: {user.username}")
    print(f"邮箱: {user.email}")
    print(f"角色: {user.role}")
    print(f"状态: {user.status}")
    print(f"落点: {user_model.db_path}")


if __name__ == "__main__":
    create_admin_user()
