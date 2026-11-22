# -*- coding: utf-8 -*-
"""ContainerSandbox（沙箱第二档 · Docker 容器档）行为判据。

红→绿：本文件先于 `neurova/sandbox/container_sandbox.py` 存在时跑红
（ImportError：模块不存在），实现落地后转绿。

断言按 docker 可用性**分支**，两态都稳定：
- docker 可用：真容器执行 6*7=42、宿主文件系统不可见、断网、/work 只读、
  超时真停容器，全部 enforced=True；
- docker 不可用：availability()=False，run_code 诚实返回 enforced=False
  的不可用结果（不谎报、不静默降级成裸跑）。

语言判定是**先验参数检查**，与 docker 可用性无关，两态都断言。
"""

from __future__ import annotations

import json

import pytest

from neurova.sandbox.container_sandbox import (
    DEFAULT_PYTHON_IMAGE,
    ContainerSandbox,
    SandboxLanguageUnsupported,
    SandboxResult,
)
from neurova.sandbox.exec_sandbox import docker_available


@pytest.fixture(scope="module")
def sandbox() -> ContainerSandbox:
    return ContainerSandbox()


class TestAvailability:
    """docker 可用性探测：缓存、与全仓唯一探测源同值。"""

    def test_availability_is_a_stable_cached_boolean(self, sandbox):
        first = sandbox.availability()
        assert isinstance(first, bool)
        assert sandbox.availability() is first, "availability 结果应缓存稳定"

    def test_availability_matches_the_single_docker_probe_source(self, sandbox):
        """不重复造判定：容器档可用性必须与全仓唯一 docker 探测（exec_sandbox）同值。"""
        assert sandbox.availability() == docker_available()

    def test_availability_caches_the_probe(self, monkeypatch):
        import neurova.sandbox.container_sandbox as container_sandbox_module

        calls = {"count": 0}
        realProbe = container_sandbox_module.docker_available

        def countingProbe() -> bool:
            calls["count"] += 1
            return realProbe()

        monkeypatch.setattr(container_sandbox_module, "docker_available", countingProbe)
        fresh = ContainerSandbox()
        assert fresh.availability() == fresh.availability()
        assert calls["count"] <= 1, (
            f"availability 未缓存：docker info 探测跑了 {calls['count']} 次"
        )

    def test_default_image_is_python312_slim(self, sandbox):
        assert sandbox.image == DEFAULT_PYTHON_IMAGE
        assert "python" in DEFAULT_PYTHON_IMAGE


class TestRunCode:
    """run_code 契约：真执行 / 诚实不可用，两态分支断言。"""

    def test_python_arithmetic_runs_or_honestly_reports_unavailable(self, sandbox):
        """docker 可用：容器里真算 6*7=42 且 enforced=True；不可用：诚实 enforced=False。"""
        result = sandbox.run_code("print(6*7)", timeout_s=180)
        assert isinstance(result, SandboxResult)
        if not sandbox.availability():
            assert result.enforced is False, "docker 不可用却自报 enforced=True——谎报隔离"
            assert result.exit_code != 0, "不可用不得伪装成一次成功执行"
            assert result.stdout == ""
            assert "docker" in (result.detail or "").lower(), "不可用结果必须点名原因"
            return
        assert result.enforced is True
        assert result.exit_code == 0, f"容器执行失败：{result.stderr}"
        assert "42" in result.stdout

    def test_result_contract_fields_are_always_present(self, sandbox):
        result = sandbox.run_code("print('neurova-container-probe')", timeout_s=180)
        for field in (
            "stdout", "stderr", "exit_code", "enforced",
            "duration_ms", "backend", "timed_out",
        ):
            assert hasattr(result, field), f"结果缺契约字段 {field}"
        assert result.backend == "docker"
        assert result.duration_ms >= 0
        assert result.duration == result.duration_ms / 1000.0
        if sandbox.availability():
            assert "neurova-container-probe" in result.stdout
        else:
            assert result.enforced is False

    def test_stderr_is_captured_separately_when_available(self, sandbox):
        if not sandbox.availability():
            pytest.skip("docker 不可用：执行面用例仅在有 docker 的机器上跑")
        result = sandbox.run_code(
            "import sys; sys.stderr.write('container-boom\\n')", timeout_s=180
        )
        assert result.enforced is True
        assert "container-boom" in result.stderr, "stderr 未与 stdout 分流"


_HOST_PROBE_CODE = (
    "import json, os\n"
    "report = {'root': sorted(os.listdir('/')), 'probes': {}}\n"
    "for path in ('C:/Windows/win.ini', 'C:/Users', '/Users', '/Windows', '/Projects'):\n"
    "    try:\n"
    "        with open(path, 'rb') as fh:\n"
    "            fh.read(1)\n"
    "        report['probes'][path] = 'VISIBLE'\n"
    "    except OSError as exc:\n"
    "        report['probes'][path] = type(exc).__name__\n"
    "print(json.dumps(report))\n"
)


class TestStrongIsolation:
    """容器档强隔离判据：宿主文件系统不可见、断网、/work 只读、超时停容器。"""

    def test_host_filesystem_is_not_visible(self, sandbox):
        """挂载白名单（/work 只读）之外的宿主路径在容器内必须探测失败。"""
        if not sandbox.availability():
            pytest.skip("docker 不可用：容器内探测仅在有 docker 的机器上跑")
        result = sandbox.run_code(_HOST_PROBE_CODE, timeout_s=180)
        assert result.enforced is True
        assert result.exit_code == 0, f"探测脚本没跑成：{result.stderr}"
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        visible = {p: v for p, v in payload["probes"].items() if v == "VISIBLE"}
        assert not visible, f"宿主路径在容器内可见：{visible}——挂载白名单失效"
        for marker in ("Windows", "Users", "Projects", "Program Files"):
            assert marker not in payload["root"], (
                f"容器根目录出现宿主痕迹 {marker}：{payload['root']}"
            )

    def test_network_is_disabled(self, sandbox):
        if not sandbox.availability():
            pytest.skip("docker 不可用：断网判据仅在有 docker 的机器上跑")
        code = (
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 80), timeout=5)\n"
            "    print('NETWORK-UP')\n"
            "except OSError as exc:\n"
            "    print('NETWORK-DOWN:' + type(exc).__name__)\n"
        )
        result = sandbox.run_code(code, timeout_s=120)
        assert result.enforced is True
        assert "NETWORK-UP" not in result.stdout, "容器能建外网连接——--network none 没生效"
        assert "NETWORK-DOWN" in result.stdout

    def test_workdir_files_mounted_readonly(self, sandbox):
        if not sandbox.availability():
            pytest.skip("docker 不可用：挂载判据仅在有 docker 的机器上跑")
        code = (
            "data = open('/work/note.txt', 'rb').read().decode('utf-8')\n"
            "print('READ:' + data)\n"
            "try:\n"
            "    open('/work/note.txt', 'w').write('tampered')\n"
            "    print('WRITE-ALLOWED')\n"
            "except OSError as exc:\n"
            "    print('WRITE-DENIED:' + type(exc).__name__)\n"
        )
        result = sandbox.run_code(
            code, workdir_files={"note.txt": b"from-host"}, timeout_s=180
        )
        assert result.enforced is True
        assert result.exit_code == 0, result.stderr
        assert "READ:from-host" in result.stdout, "workdir_files 没挂进容器 /work"
        assert "WRITE-DENIED" in result.stdout, "/work 可写——只读挂载没生效"
        assert "WRITE-ALLOWED" not in result.stdout

    def test_timeout_stops_the_container(self, sandbox):
        if not sandbox.availability():
            pytest.skip("docker 不可用：超时判据仅在有 docker 的机器上跑")
        result = sandbox.run_code(
            "import time; time.sleep(60); print('survived')", timeout_s=4
        )
        assert result.timed_out is True, "超时未被判定"
        assert result.enforced is True
        assert result.exit_code != 0, "被停掉的容器不得报成功"
        assert "survived" not in result.stdout


class TestLanguageSupportIsHonest:
    """语言先验：本期仅 python；js/ts 点名"需 node 镜像"；其余诚实 unsupported。"""

    def test_javascript_names_the_node_image_requirement(self, sandbox):
        with pytest.raises(SandboxLanguageUnsupported) as excinfo:
            sandbox.run_code("console.log(1)", language="javascript")
        assert "node" in str(excinfo.value), "js 的拒绝理由必须点名'需 node 镜像'"

    def test_typescript_is_also_node_image_gated(self, sandbox):
        with pytest.raises(SandboxLanguageUnsupported) as excinfo:
            sandbox.run_code("const x: number = 1;", language="typescript")
        assert "node" in str(excinfo.value)

    def test_other_languages_are_unsupported_not_silently_python(self, sandbox):
        with pytest.raises(SandboxLanguageUnsupported) as excinfo:
            sandbox.run_code("puts 1", language="ruby")
        assert "python" in str(excinfo.value)

    def test_python_language_name_is_normalized(self, sandbox):
        """语言名大小写/空白规范化后按 python 走：可用则真跑，不可用则诚实自报。"""
        result = sandbox.run_code("print(1)", language=" PYTHON ")
        assert result.enforced is sandbox.availability()
