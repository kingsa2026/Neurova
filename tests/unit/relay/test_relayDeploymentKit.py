"""自建中继裸 systemd 部署包（档二）的咬合守卫。

三件事必须互相咬合，缺一环用户就会在服务器上才炸：
1. `install.sh` 的 RELAY_FILES 最小文件集 —— 拷出去**必须能独立运行**（含
   `/healthz`，配对面板的预检探的就是它）；
2. `neurova-relay.service` —— 引用的路径/用户/入口与 install.sh 写下的一致；
3. `python -m neurova.relay` —— 空令牌拒绝启动（空令牌等于没有入口）。
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
KIT = REPO / "deploy" / "relay-systemd"


def _relayFilesFromInstallScript() -> list:
    text = (KIT / "install.sh").read_text(encoding="utf-8")
    block = re.search(r"RELAY_FILES=\(([^)]*)\)", text, re.S)
    assert block, "install.sh 里找不到 RELAY_FILES 清单"
    return re.findall(r'"([^"]+)"', block.group(1))


class TestMinimalFileSet:
    def test_every_listed_file_exists_in_repo(self):
        for rel in _relayFilesFromInstallScript():
            assert (REPO / rel).is_file(), f"install.sh 清单里的文件不存在：{rel}"

    @pytest.mark.timeout(150)
    def test_minimal_set_runs_standalone(self, tmp_path):
        """按 install.sh 的清单拷到独立目录后，中继必须能起、/healthz 必须通。

        这条钉的是"最小集闭包"：拷贝清单漏一个文件，用户就在服务器上看到
        ImportError，而不是在仓库里。依赖只允许 fastapi/uvicorn（install.sh
        往 venv 里装的那两样）。
        """
        lib = tmp_path / "lib"
        for rel in _relayFilesFromInstallScript():
            dest = lib / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / rel, dest)
        probe = (
            "import sys;"
            f"sys.path.insert(0, r'{lib}');"
            "import neurova;"
            "assert r'" + str(lib) + "' in neurova.__file__, neurova.__file__;"
            "from fastapi.testclient import TestClient;"
            "from neurova.relay.app import create_relay_app;"
            "c = TestClient(create_relay_app('tok-123456'));"
            "r = c.get('/healthz');"
            "assert r.status_code == 200, r.text;"
            "print('STANDALONE_OK')"
        )
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                              timeout=120)
        assert proc.returncode == 0, f"最小集独立运行失败：\n{proc.stderr[-2000:]}"
        assert "STANDALONE_OK" in proc.stdout


class TestServiceUnit:
    def test_unit_matches_install_layout(self):
        text = (KIT / "neurova-relay.service").read_text(encoding="utf-8")
        assert "EnvironmentFile=/etc/neurova-relay/config.env" in text
        assert "Environment=PYTHONPATH=/opt/neurova-relay/lib" in text
        assert "ExecStart=/opt/neurova-relay/venv/bin/python -m neurova.relay" in text
        assert "User=neurova-relay" in text

    def test_install_script_is_valid_shell(self):
        script = (KIT / "install.sh").read_text(encoding="utf-8")
        proc = subprocess.run(["bash", "-n", str(KIT / "install.sh")],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
        assert proc.returncode == 0, proc.stderr
        assert "set -euo pipefail" in script, "部署脚本必须 fail-fast"
        # 幂等关键：令牌首启生成后复用，不能每次部署都换（换了面板就得重填）
        assert "enrollment_token" in script


class TestRelayEntry:
    def test_empty_token_refuses_to_start(self, monkeypatch):
        from neurova.relay import __main__ as entry

        ran = {"uvicorn": False}
        monkeypatch.setattr(entry.uvicorn, "run",
                            lambda *a, **kw: ran.__setitem__("uvicorn", True))
        assert entry.main([]) == 2
        assert ran["uvicorn"] is False, "空令牌绝不能把中继拉起来"

    def test_token_and_tls_are_passed_through(self, monkeypatch):
        from neurova.relay import __main__ as entry

        seen = {}
        monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: seen.update(kw))
        code = entry.main(["--enrollment-token", "tok-abc",
                           "--host", "0.0.0.0", "--port", "9443",
                           "--tls-cert", "/x/cert.pem", "--tls-key", "/x/key.pem"])
        assert code == 0
        assert seen["port"] == 9443
        assert seen["host"] == "0.0.0.0"
        assert seen["ssl_certfile"] == "/x/cert.pem"
        assert seen["ssl_keyfile"] == "/x/key.pem"

    def test_relay_healthz_is_probe_target(self):
        """配对面板的 relay 预检探的是 /healthz——这条口必须一直在。"""
        from neurova.relay.app import create_relay_app

        client = TestClient(create_relay_app("tok-123456"))
        assert client.get("/healthz").status_code == 200
