# -*- coding: utf-8 -*-
"""导入 CLI 的退出码：调用方（含 CI 与批处理）按码分支，不解析文案。"""

EXIT_OK = 0
EXIT_UNRECOGNIZED = 2      # 未识别或多指纹冲突——一律不写库
EXIT_INVALID_BUNDLE = 3    # 包校验未通过，整包拒绝
EXIT_REPORT_ONLY = 4       # 未接受 --yes，只出报告
