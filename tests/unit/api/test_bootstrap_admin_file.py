"""
安装包首装管理员凭据文件消费测试

背景: NSIS 安装向导自定义页收集用户名/密码写入 <backend>/data/bootstrap_admin.ini
（INI 格式规避 JSON 引号/反斜杠转义），后端 create_app 启动期消费:
- 仅当系统中无任何用户时创建 admin（与 register/setup-status 语义一致）
- 读取后立即删除文件（凭据不落盘残留；无删除权限仅告警）
- 编码健壮: NSIS WriteINIStr 在 Unicode 安装器写 UTF-16(带 BOM)，兼容 utf-8-sig/gbk
- fail-open: 任何异常不阻断启动

契约（consume_bootstrap_admin_file）:
- 无文件 → no-op 返回 0
- 文件+无用户 → create_user(role="admin") 返回 1，文件删除
- 文件+已有用户 → 不创建 返回 0，文件仍删除（陈旧凭据不留存）
- 内容非法/编码不可识别 → 不创建 返回 0，文件删除
"""
import configparser
import os

import pytest

import neurova.api.bootstrap_user as bootstrap_user


def _write_ini(path, username="installer_admin", password="Passw0rd!"):
    parser = configparser.ConfigParser()
    parser.add_section("bootstrap")
    parser.set("bootstrap", "username", username)
    parser.set("bootstrap", "password", password)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


class FakeUserModel:
    def __init__(self, users=None):
        self.users = users or []
        self.created_kwargs = None

    def list_users(self):
        return self.users

    def create_user(self, **kwargs):
        self.created_kwargs = kwargs
        self.users.append(kwargs["username"])


@pytest.fixture()
def ini_path(tmp_path):
    return str(tmp_path / "data" / "bootstrap_admin.ini")


class TestConsumeBootstrapAdminFile:
    def test_no_file_is_noop(self, tmp_path, ini_path):
        um = FakeUserModel()
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 0
        assert um.created_kwargs is None

    def test_creates_admin_when_no_users(self, tmp_path, ini_path):
        _write_ini(ini_path)
        um = FakeUserModel()
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 1
        assert um.created_kwargs["username"] == "installer_admin"
        assert um.created_kwargs["role"] == "admin"
        # 凭据文件消费后删除
        assert not os.path.exists(ini_path)

    def test_skips_when_users_exist_and_deletes_file(self, ini_path):
        _write_ini(ini_path)
        um = FakeUserModel(users=["existing"])
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 0
        assert um.created_kwargs is None
        assert not os.path.exists(ini_path)

    def test_invalid_content_deleted_no_create(self, ini_path):
        os.makedirs(os.path.dirname(ini_path), exist_ok=True)
        with open(ini_path, "wb") as f:
            f.write(b"\xff\xfe\x00garbage-not-ini\x00\x00")
        um = FakeUserModel()
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 0
        assert um.created_kwargs is None
        assert not os.path.exists(ini_path)

    def test_utf16_encoded_ini(self, ini_path):
        """Unicode NSIS 写 UTF-16 场景（BOM）"""
        _write_ini(ini_path)
        with open(ini_path, "rb") as f:
            text = f.read().decode("utf-8")
        with open(ini_path, "wb") as f:
            f.write(text.encode("utf-16"))
        um = FakeUserModel()
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 1
        assert um.created_kwargs["username"] == "installer_admin"

    def test_empty_fields_no_create(self, ini_path):
        _write_ini(ini_path, username="", password="")
        um = FakeUserModel()
        assert bootstrap_user.consume_bootstrap_admin_file(ini_path, user_model=um) == 0
        assert um.created_kwargs is None
        assert not os.path.exists(ini_path)
