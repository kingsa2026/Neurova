# -*- coding: utf-8 -*-
"""部署配置一致性门禁的常驻自检（Issue #61）。

背景：Dockerfile / docker-compose.yml / Helm Chart 是同一服务的三种交付形态，
却长期没有一条自动化检查把它们对齐（改一处忘两处全靠人肉记忆）。本次新增
scripts/ci/deploy_config_consistency_check.py 后，本套件负责钉住：

1. **脚本存在且当前全绿** —— 门禁自己失效（被删/被改成空壳/悄悄放宽）时，
   配置漂移就又回到"上线才发现"。
2. **规则集不缩水** —— R1~R9 九条不变量的函数与错误码仍在（防有人"顺手"
   删掉某条挡路的规则）。
3. **双侧 CI 都真的调用它** —— 只挂一侧 = 另一侧的合并放行标准缺失。
4. **周级 crontab 巡检在位** —— push 门禁只在有人提交时跑，沉寂期的漂移
   （基础镜像上游发版、依赖 CVE、K8s API 演进）无人可见。周级 cadence 用
   标准 5 段 cron 的第 5 段（星期）表达；平台定时任务最小间隔 5 分钟，
   不存在"间隔单位"或"任务最长存活 3 天"这类语义。
5. **负向能力仍在** —— 把已知的漂移形态（探针周期不一致 / 死环境变量名 /
   资源不齐 / 数据卷无 PVC）注入临时副本时应被抓住，防门禁退化成"永远绿"。
6. **漂移实体不回潮** —— 本次修的 6 处实锤漂移逐个钉死（DEAD_ENV_KEYS /
   探针常量 / 资源对 / Chart 版本），避免被并行改动覆盖回去。
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "ci" / "deploy_config_consistency_check.py"
CHECK_CMD = "scripts/ci/deploy_config_consistency_check.py"
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("deploy_config_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _cnb_main() -> dict:
    data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
    return data["main"]


def _pipeline_scripts(pipe) -> str:
    out = []
    for stage in (pipe or {}).get("stages") or []:
        if isinstance(stage, dict) and stage.get("script"):
            out.append(str(stage["script"]))
    return "\n".join(out)


class TestGateScriptExists:
    def test_script_present(self):
        assert GATE.exists(), "部署配置一致性门禁脚本丢失——跨文件漂移将无人拦"

    def test_gate_passes_now(self):
        """当前仓库应全绿（红即代表配置漂移已存在，须先修配置再谈门禁）。"""
        proc = subprocess.run(
            [sys.executable, str(GATE), "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
        )
        payload = json.loads(proc.stdout or "{}")
        assert proc.returncode == 0, (
            "部署配置一致性门禁当前不通过（合并即红）：\n"
            + "\n".join(f"  ❌ [{e['rule']}] {e['message']}" for e in payload.get("errors", []))
        )
        assert payload.get("ok") is True


class TestRuleSetNotShrunk:
    RULES = ("R1-ports", "R2-healthcheck", "R3-resources", "R4-images", "R5-env",
             "R6-persistence", "R7-auth", "R8-deps", "R9-wiring", "R10-config-assets",
             "R11-helm-values")

    def test_all_rules_implemented(self):
        source = io.open(GATE, encoding="utf-8").read()
        missing = [r for r in self.RULES if f'"{r}"' not in source]
        assert not missing, (
            f"门禁规则实现被删除/改名: {missing}\n"
            "规则集与测试里的 RULES 是契约：删规则必须同步改测并说明为何不再需要。"
        )

    def test_checker_functions_present(self):
        source = io.open(GATE, encoding="utf-8").read()
        for fn in ("_check_ports", "_check_health", "_check_resources", "_check_images",
                   "_check_env_keys", "_check_persistence", "_check_auth_secret",
                   "_check_hard_deps", "_check_config_assets", "_check_helm_values_refs",
                   "_check_ci_wiring"):
            assert f"def {fn}(" in source, f"门禁检查函数缺失: {fn}"

    def test_units_normalized_documented(self):
        """单位归一必须显式正确：compose 的 m/g 是 1024 进制，`2000m` 已是 millicore。"""
        module = _load_gate_module()
        assert module.cpu_millicores("2") == 2000
        assert module.cpu_millicores("0.5") == 500
        assert module.cpu_millicores("2000m") == 2000
        assert module.cpu_millicores("500m") == 500
        assert module.memory_bytes("1Gi") == module.memory_bytes("1g")
        assert module.memory_bytes("4Gi") == module.memory_bytes("4g")
        assert module.memory_bytes("512Mi") == 512 * 1024**2


class TestCiWiring:
    def test_cnb_push_pipeline_runs_gate(self):
        scripts = json.dumps(_cnb_main().get("push"), ensure_ascii=False)
        assert CHECK_CMD in scripts, f".cnb.yml push 流水线未调用 {CHECK_CMD}"

    def test_github_workflow_runs_gate(self):
        assert CHECK_CMD in io.open(GHW, encoding="utf-8").read(), (
            f".github/workflows/ci.yml 未调用 {CHECK_CMD}"
        )

    def test_weekly_crontab_audit_present(self):
        """周级 crontab 巡检必须存在且真跑门禁脚本。

        周级语义：标准 5 段 cron 的第 5 段（星期）取具体值即周级，例如
        `30 3 * * 1`。不要写成"间隔 N 天"——平台只认 cron 表达式。
        """
        main = _cnb_main()
        weekly = {
            key: value for key, value in main.items()
            if isinstance(key, str) and key.startswith("crontab:")
            and re.match(r"^crontab:\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([0-7])\s*$", key)
            and CHECK_CMD in _pipeline_scripts((value or [{}])[0])
        }
        assert weekly, (
            "缺少周级 crontab 部署配置巡检（形如 `main: \"crontab: 30 3 * * 1\"`）——"
            "push 门禁只在提交时跑，沉寂期的上游漂移无人可见"
        )

    def test_crontab_interval_not_below_platform_minimum(self):
        """平台限制：定时任务最小调度间隔 5 分钟；逐分钟写法会被平台拒绝。"""
        main = _cnb_main()
        for key in main:
            if not (isinstance(key, str) and key.startswith("crontab:")):
                continue
            expr = key.split(":", 1)[1].split()
            assert expr[0] != "*" or expr[1] == "*", (
                f"crontab `{key}` 的分钟段为 `*`（每分钟）低于平台最小间隔 5 分钟，将被平台拒绝"
            )

    def test_parity_guard_registry_includes_deploy_config(self):
        """两侧放行标准必须一致：EXPECTED_MAP 里已登记 deploy-config。"""
        source = io.open(PROJECT_ROOT / "tests" / "unit" / "test_ci_parity_guard.py",
                         encoding="utf-8").read()
        assert '"deploy-config": ["deploy-config"]' in source, (
            "test_ci_parity_guard.EXPECTED_MAP 未登记 deploy-config —— "
            "单侧门禁看似存在、实际不参与对齐校验"
        )

    def test_gate_registered_in_protected_subset(self):
        """门禁自检必须进受保护子集，否则 CI 根本不跑它。"""
        protected = io.open(PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt",
                            encoding="utf-8").read()
        assert "tests/unit/test_deploy_config_guard.py" in protected, (
            "本守卫未登记进 scripts/ci/protected_tests.txt —— unit-tests 流水线不会跑它"
        )


class TestNegativeControls:
    """负向控制：已知漂移形态必须被抓住（防门禁退化为永远绿）。"""

    def _run_on_copy(self, tmp_path: Path, mutate) -> dict:
        import shutil

        root = tmp_path / "repo"
        shutil.copytree(
            PROJECT_ROOT, root,
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", "embedding", "models", "dist", "__pycache__",
                "audit-reports", "trajectories", "sessions",
            ),
            dirs_exist_ok=True,
        )
        mutate(root)
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "ci" / "deploy_config_consistency_check.py"), "--json"],
            capture_output=True, text=True, cwd=str(root), timeout=180,
        )
        return json.loads(proc.stdout or "{}")

    def test_detects_healthcheck_drift(self, tmp_path):
        def mutate(root: Path):
            path = root / "docker-compose.yml"
            text = io.open(path, encoding="utf-8").read().replace("interval: 30s", "interval: 15s")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R2-healthcheck" for e in payload["errors"]), (
            "探针周期被单侧改动却未被抓住"
        )

    def test_detects_dead_env_key(self, tmp_path):
        def mutate(root: Path):
            path = root / "helm" / "neurova" / "templates" / "configmap.yaml"
            text = io.open(path, encoding="utf-8").read().replace(
                "NEUROVA_DB_PATH:", "DATABASE_PATH:")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R5-env" for e in payload["errors"]), (
            "环境变量名写错（应用零读取方）却未被抓住"
        )

    def test_detects_resource_mismatch(self, tmp_path):
        def mutate(root: Path):
            path = root / "docker-compose.yml"
            text = io.open(path, encoding="utf-8").read().replace("memory: 4g", "memory: 8g")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R3-resources" for e in payload["errors"]), (
            "compose 与 Helm 资源限制不一致却未被抓住"
        )

    def test_detects_pvc_bypass(self, tmp_path):
        def mutate(root: Path):
            path = root / "helm" / "neurova" / "templates" / "deployment-backend.yaml"
            text = io.open(path, encoding="utf-8").read().replace(
                "persistentVolumeClaim:", "emptyDir: #")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R6-persistence" for e in payload["errors"]), (
            "数据卷退化为非持久化存储却未被抓住"
        )

    def test_detects_env_override_healthcheck_drift(self, tmp_path):
        """base values 对齐、环境 override 漂移也必须被抓（生产探活口径）。"""

        def mutate(root: Path):
            path = root / "helm" / "neurova" / "values-production.yaml"
            text = io.open(path, encoding="utf-8").read()
            io.open(path, "w", encoding="utf-8").write(
                text.replace("periodSeconds: 30", "periodSeconds: 5")
            )

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R2-healthcheck" for e in payload["errors"]), (
            "values-production.yaml 的探针周期漂移却未被抓住"
        )

    def test_detects_undefined_values_ref(self, tmp_path):
        def mutate(root: Path):
            path = root / "helm" / "neurova" / "values.yaml"
            text = io.open(path, encoding="utf-8").read().replace(
                'configMountPath: /app/config', "# configMountPath removed")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R11-helm-values" for e in payload["errors"]), (
            "模板引用了 values 里不存在的键却未被抓住（渲染为 <no value> 静默失效）"
        )

    def test_detects_dockerignored_runtime_config(self, tmp_path):
        def mutate(root: Path):
            path = root / ".dockerignore"
            text = io.open(path, encoding="utf-8").read().replace("!config/cors.json\n", "")
            io.open(path, "w", encoding="utf-8").write(text)

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R10-config-assets" for e in payload["errors"]), (
            "运行时必需的 config/cors.json 被 .dockerignore 挡掉却未被抓住"
        )

    def test_detects_missing_weekly_audit(self, tmp_path):
        def mutate(root: Path):
            # 把 crontab 键换成非定时事件（保持 YAML 合法，只摘掉"周级"这一属性）
            path = root / ".cnb.yml"
            text = io.open(path, encoding="utf-8").read()
            io.open(path, "w", encoding="utf-8").write(
                text.replace('"crontab: 30 3 * * 1":', "api_trigger:")
            )

        payload = self._run_on_copy(tmp_path, mutate)
        assert any(e["rule"] == "R9-wiring" for e in payload["errors"]), (
            "周级巡检被摘掉却未被抓住"
        )


class TestDriftEntitiesStayFixed:
    """本次实锤漂移逐个钉死，防止被并行改动覆盖回旧形态。"""

    def test_dockerfile_python_in_ci_matrix(self):
        text = io.open(PROJECT_ROOT / "Dockerfile", encoding="utf-8").read()
        ci = io.open(GHW, encoding="utf-8").read()
        versions = set(re.findall(r'python-version:\s*"(\d+\.\d+)"', ci))
        used = set(re.findall(r"^FROM python:(\d+\.\d+)", text, re.M))
        assert used <= versions, f"Dockerfile 基础镜像 {sorted(used)} 不在 CI 矩阵 {sorted(versions)} 内"

    def test_cron_hard_dep_declared_in_prod_requirements(self):
        reqs = io.open(PROJECT_ROOT / "requirements.txt", encoding="utf-8").read().lower()
        for dep in ("apscheduler", "feedparser"):
            assert dep in reqs, f"硬依赖 {dep} 未进 requirements.txt（生产镜像 import 即崩）"

    def test_this_agent_cli_has_no_fake_cron_tools(self):
        """本仓（Neurova）不存在 CronCreate/CronList/CronDelete 工具。

        Issue #61 原始描述里的调度结论基于"平台会话工具"，与本仓能力无关：
        本仓的定时能力是 neurova/agent/scheduler.py（APScheduler）+ 平台
        crontab 流水线事件。此处钉住"不得为迎合描述而在仓内新建同名工具"。
        """
        hits = []
        for path in PROJECT_ROOT.joinpath("neurova").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in ("CronCreate", "CronList", "CronDelete"):
                if name in text:
                    hits.append(f"{path.relative_to(PROJECT_ROOT)}:{name}")
        assert not hits, f"仓内出现凭空捏造的 cron 工具名: {hits}"
