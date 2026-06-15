"""
记忆接口 - Memory Endpoint 包

通过导入所有子模块确保路由注册到共享 router，然后重新导出 router。
导入路径保持不变: from neurova.api.endpoints.memory import router as memory_router
"""

# 导入共享 router（所有子模块通过 from .base import router 注册路由）
from .base import router  # noqa: F401

# 导入子模块以注册路由
from . import crud  # noqa: F401
from . import eki  # noqa: F401
from . import emotion  # noqa: F401
from . import metacognition  # noqa: F401
from . import profile  # noqa: F401
from . import questions  # noqa: F401
from . import reflection  # noqa: F401
from . import tkg  # noqa: F401
from . import working_memory  # noqa: F401
