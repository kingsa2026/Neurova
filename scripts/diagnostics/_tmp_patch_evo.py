"""一次性补丁脚本：delete_agent 清理 AgentConfigManager 配置。"""
from pathlib import Path

path = 'neurova/api/endpoints/agent.py'
src = Path(path).read_text(encoding='utf-8')

old = '''    # 移除
    del agents[agent_id]
'''
new = '''    # 移除运行时实例
    del agents[agent_id]

    # B11: 清理 AgentConfigManager 持久化配置
    try:
        get_agent_config_manager().delete_agent(agent_id)
    except Exception as e:
        logger.warning("AgentConfigManager.delete_agent 失败: %s", e)
'''
assert old in src
src = src.replace(old, new, 1)
Path(path).write_text(src, encoding='utf-8')
print('patched delete_agent')
