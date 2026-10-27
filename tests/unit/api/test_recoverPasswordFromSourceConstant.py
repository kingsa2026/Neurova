"""§6-171：取回密码的最高权重口令由源码常量提供，且必须核对管理员账号（2026-10-13 用户裁定）。

实状（本会话现取，不沿用旧描述）：`66269ea0` 把原先写死的常量改成
`NEUROVA_MASTER_RECOVERY_PASSWORD`，未配置即 403。本机未设该变量，而
`data/users.db` 实测只有 1 条用户（`kingsa`／role=admin／failed_attempts=0）——
不是被锁定，是没有任何可用口令，面板上"最高权重密码"那一栏提交出去只能撞到那条 403。
经裁定按原形态把口令写回源码，偏离说明与补偿措施登记在台账 §6-171。

本档钉三件事，缺一不可：

1. 常量是源码里的字面量（按 AST 判形态，不钉文档措辞），不再是环境查询；
2. 因常量必然非空而**永不可达**的「未配置即 403」分支必须删净——从历史取回一段代码时，
   不许把它已经失效的兜底分支一起搬回来；
3. 端点行为：口令对上但角色不是 admin ⇒ 拒且原口令不被改写；角色是 admin ⇒ 放行，
   且新口令在登录端点上真的能用（写→读闭环，不拿"库里查得到一行"充当判据）。
"""

import ast
import os
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET", "recover-pin-0123456789abcdef-2026-10-13")

from neurova.api.auth import hash_password  # noqa: E402
from neurova.api.endpoints import auth as AUTH  # noqa: E402
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTH_SOURCE = REPO_ROOT / "neurova" / "api" / "endpoints" / "auth.py"

OLD_PASSWORD = "0ld-Pw#not-used-01"
ADMIN_NEW_PASSWORD = "R3cover#admin-new-02"
NONADMIN_NEW_PASSWORD = "R3cover#refused-03"
WRONG_SECRET = "d3finitely-n0t-the-source-constant"


def _secretAssignNode():
    """模块级 `MASTER_RECOVERY_PASSWORD = <右值>` 的右值节点；找不到返回 None。"""
    tree = parseSource(AUTH_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "MASTER_RECOVERY_PASSWORD":
                return node.value
    return None


def _recoverFuncNode():
    tree = parseSource(AUTH_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "recover_password":
            return node
    return None


def _secretGateLines(funcNode):
    """形如 `if not MASTER_RECOVERY_PASSWORD:` 的分支行号——常量非空后它永不可达。"""
    lines = []
    for node in ast.walk(funcNode):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Name)
            and test.operand.id == "MASTER_RECOVERY_PASSWORD"
        ):
            lines.append(node.lineno)
    return lines


@pytest.fixture()
def recoveryFace(monkeypatch):
    """真端点 + 生产取法的用户模型。

    数据根由 `tests/conftest.py` 在导入期钉到临时目录，本夹具不碰仓内 `data/users.db`；
    账号名带随机后缀，避开同一会话跑测里别的用例在共享 users.db 里留下的行。
    """
    app = FastAPI()
    app.include_router(AUTH.router, prefix="/api/v1/auth")
    # 限流表是模块级 dict，跨用例累计会把后续格子的读数从 400 变成 429——按用例重置
    monkeypatch.setattr(AUTH, "_recover_attempts", {})

    user_model = AUTH._get_user_model()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"recAdm{suffix}"
    member_name = f"recMem{suffix}"
    user_model.create_user(username=admin_name, password_hash=hash_password(OLD_PASSWORD), role="admin")
    user_model.create_user(username=member_name, password_hash=hash_password(OLD_PASSWORD), role="user")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, admin_name, member_name


class TestRecoverySecretFromSource:
    def testSecretIsSourceLiteralNotEnvLookup(self):
        """口令必须来自源码字面量——本批裁定的形态本身要被钉住，防止下个会话静默改回环境查询。"""
        node = _secretAssignNode()
        assert node is not None, "MASTER_RECOVERY_PASSWORD 的模块级赋值不见了"
        assert isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value, (
            "最高权重恢复口令必须是源码里的非空字符串字面量（§6-171 裁定）；"
            "写成 os.environ.get(...) 即退回未配置时恢复功能整体锁死的形态"
        )

    def testUnreachableDisabledBranchIsGone(self):
        """常量必然非空，那条 403 分支就是不可达死码——留着一边谎称"可禁用"，一边永远走不到。"""
        func_node = _recoverFuncNode()
        assert func_node is not None, "recover_password 端点函数不见了"
        gate_lines = _secretGateLines(func_node)
        assert gate_lines == [], (
            f"recover_password 里仍有 `if not MASTER_RECOVERY_PASSWORD` 分支（行 {gate_lines}）——"
            "源码常量非空后它永不可达，属本批应一并退役的死码"
        )

    def testAdminWithSourceSecretIsResetAndNewPasswordWorks(self, recoveryFace):
        client, admin_name, _ = recoveryFace
        response = client.post(
            "/api/v1/auth/recover-password",
            json={
                "username": admin_name,
                "master_password": AUTH.MASTER_RECOVERY_PASSWORD,
                "new_password": ADMIN_NEW_PASSWORD,
                "confirm_password": ADMIN_NEW_PASSWORD,
            },
        )
        assert response.status_code == 200, f"管理员凭源码口令应放行，实得 {response.status_code}: {response.text}"

        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": ADMIN_NEW_PASSWORD}
        ).status_code == 200, "重置写进去了却没被登录读到——闭环未成立"
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 401, "旧口令仍可用，说明密码根本没被改写"

    def testNonAdminWithCorrectSecretIsRefused(self, recoveryFace):
        """裁定明确要求核对管理员账号：口令对而角色不对，也必须拒，且不得改动任何人。"""
        client, _, member_name = recoveryFace
        response = client.post(
            "/api/v1/auth/recover-password",
            json={
                "username": member_name,
                "master_password": AUTH.MASTER_RECOVERY_PASSWORD,
                "new_password": NONADMIN_NEW_PASSWORD,
                "confirm_password": NONADMIN_NEW_PASSWORD,
            },
        )
        assert response.status_code == 400, (
            f"非 admin 账号凭正确口令应被拒（400），实得 {response.status_code}: {response.text}"
        )
        assert client.post(
            "/api/v1/auth/login", json={"username": member_name, "password": OLD_PASSWORD}
        ).status_code == 200, "拒绝却已经把普通账号口令改掉了"
        assert client.post(
            "/api/v1/auth/login", json={"username": member_name, "password": NONADMIN_NEW_PASSWORD}
        ).status_code == 401, "被拒的重置实际生效了——角色核对没起到闸门作用"

    def testWrongSecretIsRefusedNotDisabled(self, recoveryFace):
        """口令错 ⇒ 400（统一文案），且不得读成"未配置"那条形变。"""
        client, admin_name, _ = recoveryFace
        response = client.post(
            "/api/v1/auth/recover-password",
            json={
                "username": admin_name,
                "master_password": WRONG_SECRET,
                "new_password": ADMIN_NEW_PASSWORD,
                "confirm_password": ADMIN_NEW_PASSWORD,
            },
        )
        assert response.status_code == 400, (
            f"口令不正确应回 400，实得 {response.status_code}: {response.text}"
        )
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 200, "口令校验失败却改动了管理员账号"

    def testEmptySecretIsRefused(self, recoveryFace):
        """空口令必须被拒——本仓反证实测过的形变：

        把常量退回 `os.environ.get(..., \"\")` 而未保留「未配置即禁用」那道门时，
        `hmac.compare_digest(\"\", \"\")` 为真，于是**任何人留空最高权重密码即可重置 admin**。
        上面那条 AST 格钉的是形态，本格钉的是形态被破坏后的后果，两半都要在。
        """
        client, admin_name, _ = recoveryFace
        response = client.post(
            "/api/v1/auth/recover-password",
            json={
                "username": admin_name,
                "master_password": "",
                "new_password": ADMIN_NEW_PASSWORD,
                "confirm_password": ADMIN_NEW_PASSWORD,
            },
        )
        assert response.status_code == 400, (
            f"空口令不得放行（否则留空即接管管理员），实得 {response.status_code}: {response.text}"
        )
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 200, "空口令校验失败却已经把管理员口令改掉"
