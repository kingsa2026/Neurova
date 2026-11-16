"""Sandbox 包 —— 代码/命令执行沙箱（exec_sandbox、code_sandbox、appcontainer、restricted_token）。

（S7 死码退役批）原 thought_sandbox（思维模拟沙箱）已按 P2 散点退役：生产零消费
（端点实现在 api/endpoints/sandbox.py + exec_sandbox.py，与本模块无 import 关系），
包级符号导出面随之撤销。消费方一律直接 `from neurova.sandbox.exec_sandbox import ...`。
"""
