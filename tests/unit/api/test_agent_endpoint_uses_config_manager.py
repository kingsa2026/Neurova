"""
B11 测试：验证 agent.py 端点改用 AgentConfigManager

验证：
1. agent.py 模块导入 get_agent_config_manager
2. list_agents 端点使用 config_manager.list_agents()（而非 load_agents_config）
3. create_agent 端点使用 config_manager.create_agent(dict) 持久化
4. delete_agent 端点使用 config_manager.delete_agent(agent_id) 清理配置
"""

import inspect


def test_agent_endpoint_imports_config_manager():
    """B11.1: agent.py 应导入 get_agent_config_manager"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module)
    assert "get_agent_config_manager" in source, "agent.py 应导入 get_agent_config_manager"


def test_list_agents_uses_config_manager():
    """B11.2: list_agents 应调用 config_manager.list_agents()，不再仅用 load_agents_config"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module.list_agents)
    assert "get_agent_config_manager" in source, "list_agents 应使用 get_agent_config_manager"
    assert ".list_agents()" in source, "list_agents 应调用 config_manager.list_agents()"


def test_create_agent_uses_config_manager():
    """B11.3: create_agent 应调用 config_manager.create_agent(dict) 持久化配置"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module.create_agent)
    assert "get_agent_config_manager" in source, "create_agent 应使用 get_agent_config_manager"
    assert ".create_agent(" in source, "create_agent 应调用 config_manager.create_agent()"


def test_delete_agent_uses_config_manager():
    """B11.4: delete_agent 应调用 config_manager.delete_agent(agent_id) 清理配置"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module.delete_agent)
    assert "get_agent_config_manager" in source, "delete_agent 应使用 get_agent_config_manager"
    assert ".delete_agent(" in source, "delete_agent 应调用 config_manager.delete_agent()"


def test_get_agent_uses_config_manager():
    """B11.5: get_agent 应使用 config_manager.get_agent() 作为后备"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module.get_agent)
    assert "get_agent_config_manager" in source, "get_agent 应使用 get_agent_config_manager"


def test_update_agent_uses_config_manager():
    """B11.6: update_agent 应调用 config_manager.update_agent() 持久化"""
    from neurova.api.endpoints import agent as agent_module

    source = inspect.getsource(agent_module.update_agent)
    assert "get_agent_config_manager" in source, "update_agent 应使用 get_agent_config_manager"
    assert ".update_agent(" in source, "update_agent 应调用 config_manager.update_agent()"
