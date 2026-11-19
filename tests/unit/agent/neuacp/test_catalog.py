# -*- coding: utf-8 -*-
"""A8 附带：工具目录（catalog）契约测试——预设、探测结构、禁用项。"""
from neurova.agent.neuacp.catalog import CATALOG, defaultCommand, listCatalog, probeTool


def test_p0ToolsPresentWithCommands():
    for tool in ("opencode", "qoder", "codebuddy", "zcode"):
        assert tool in CATALOG
        assert CATALOG[tool]["command"], f"{tool} 缺默认命令"
    assert CATALOG["zcode"]["kind"] == "plugin"
    assert "--disallowed-tools" in CATALOG["zcode"]["command"]


def test_traeIsDisabledButArchived():
    assert CATALOG["trae"]["disabled"] is True
    assert defaultCommand("trae") is None


def test_defaultCommandReturnsCopy():
    command = defaultCommand("opencode")
    assert command == ["opencode", "acp"]
    command.append("x")
    assert defaultCommand("opencode") == ["opencode", "acp"]


def test_defaultCommandUnknownToolReturnsNone():
    assert defaultCommand("not-a-tool") is None


def test_listCatalogProbesEachEntry():
    items = listCatalog()
    names = {item["tool"] for item in items}
    assert {"opencode", "qoder", "codebuddy", "zcode", "gemini-cli", "claude-code", "codex", "trae"} <= names
    for item in items:
        assert "installed" in item and "install_hint" in item


def test_probeUnknownTool():
    result = probeTool("not-a-tool")
    assert result["known"] is False
    assert result["installed"] is False
