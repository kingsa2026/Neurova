"""Plan Mode 错误类型（独立模块避免 plan_docs/plan_session 循环 import）。"""


class PlanError(Exception):
    """计划模式基础错误。"""


class PlanStateError(PlanError):
    """状态机非法流转（终态再变更 / asking 态审批 / 空提交）。"""


class PlanLLMError(PlanError):
    """LLM 返回不可解析 / 缺少必需字段。"""


class PlanDocError(PlanError):
    """计划文档读写失败（非法文件名 / 文件不存在）。"""


class PlanDocNotFound(PlanDocError):
    """计划文档不存在（文件名合法但文件缺失）——端点映射 404。"""
