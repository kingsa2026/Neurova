"""移动端接入与隧道通道（配对线格式单源、出站隧道代理、可独立部署的中继）。

设计事实源：`docs/04-plans/2026-10-24-移动端扫码经中继连接无固定IP服务端设计方案.md`。
本包的 `protocol` 是三处状态字面量（Python / TS / ArkTS）的**权威侧**，
由 `tests/unit/test_tunnelStateEnumSingleSource.py` 逐条咬合。
"""
