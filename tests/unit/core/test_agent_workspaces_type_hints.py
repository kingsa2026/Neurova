# -*- coding: utf-8 -*-
"""延迟注解在运行期求值时不得引用未导入的类型名。"""

import typing

from neurova.core import agent_workspaces


def test_owner_index_annotations_resolve():
    for function in (
        agent_workspaces.load_agent_owner_index,
        agent_workspaces.save_agent_owner_index,
    ):
        hints = typing.get_type_hints(function)
        assert "return" in hints or "agents" in hints
