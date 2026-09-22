"""一次性补丁脚本：delete_agent 清理 AgentConfigManager 配置。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from neurova.core.data_root import repoAsset

# 改动对象是工作树里的仓库文件：锚仓库根，而不是"碰巧从哪儿启动"。
path = repoAsset("neurova", "api", "endpoints", "agent.py")
src = path.read_text(encoding='utf-8')

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
path.write_text(src, encoding='utf-8')
print('patched delete_agent')
