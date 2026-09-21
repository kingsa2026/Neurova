"""neurova.storage —— 存储与数据迁移基础设施。

历史目录名为 `Storage`（首字母大写），与全仓 `neurova.<小写包>` 的导入路径
不匹配：Linux/Docker 上 `import neurova.storage.*` 必然 ModuleNotFoundError
（Windows 文件系统大小写不敏感，本地可跑故长期潜伏）。
统一为全小写包名并补 `__init__.py`，使包可导入。
"""
