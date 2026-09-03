"""
Neurova 集成测试包
"""

import sys
from pathlib import Path

# 确保项目根目录在路径中
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
