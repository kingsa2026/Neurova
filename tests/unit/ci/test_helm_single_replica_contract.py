import re
from pathlib import Path

import yaml

CHART = Path("helm/neurova")


def testProductionValuesKeepSqliteSingleReplica():
    values = yaml.safe_load((CHART / "values-production.yaml").read_text(encoding="utf-8"))
    assert values["hpa"]["enabled"] is False
    assert values["hpa"]["minReplicas"] == 1
    assert values["hpa"]["maxReplicas"] == 1


def testPersistentBackendRejectsMultipleReplicas():
    template = (CHART / "templates/deployment-backend.yaml").read_text(encoding="utf-8")
    assert re.search(
        r"if and \.Values\.database\.persistence\.enabled "
        r"\(gt \(int \.Values\.backend\.replicaCount\) 1\)",
        template,
    ), "持久化 SQLite 多副本必须在渲染期失败，不能等到运行后写坏库"
    assert re.search(r"fail \"[^\"]*SQLite[^\"]*多副本", template)


def testHpaRejectsPersistentSqlite():
    template = (CHART / "templates/hpa.yaml").read_text(encoding="utf-8")
    assert re.search(
        r"if and \.Values\.hpa\.enabled \.Values\.database\.persistence\.enabled",
        template,
    ), "HPA 可扩到多副本，持久化 SQLite 模式必须在渲染期禁用"
    assert re.search(r"fail \"[^\"]*SQLite[^\"]*HPA", template)


def testNoUnrenderedPdbOrServiceMonitorConfiguration():
    for name in ("values.yaml", "values-production.yaml", "values-development.yaml"):
        values = yaml.safe_load((CHART / name).read_text(encoding="utf-8"))
        assert "pdb" not in values, f"{name} 声明了无模板的 PDB"
        assert "serviceMonitor" not in values.get("monitoring", {}), (
            f"{name} 声明了无模板的 ServiceMonitor"
        )


def testJwtSecretRequirementCoversHpaScaleOut():
    template = (CHART / "templates/deployment-backend.yaml").read_text(encoding="utf-8")
    authBlock = template.split("{{- if .Values.auth.jwtSecret }}", 1)[1].split(
        "{{- if .Values.auth.masterRecoveryPassword }}", 1
    )[0]
    assert ".Values.hpa.enabled" in authBlock
    assert ".Values.hpa.maxReplicas" in authBlock
    assert "HPA" in authBlock
