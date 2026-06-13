"""
API 错误码定义
"""


class ErrorCode:
    """API 错误码"""

    SUCCESS = 0
    UNKNOWN_ERROR = 1000
    AUTH_FAILED = 2000
    TOKEN_EXPIRED = 2001
    PERMISSION_DENIED = 2002
    NOT_FOUND = 3000
    VALIDATION_ERROR = 4000
    RATE_LIMITED = 4290
    SERVER_ERROR = 5000


# 别名
ErrorCodes = ErrorCode
