"""企业数据源接入器接口预留（B14，升级计划 §14）。

只落 Protocol/映射描述符/fake adapter/admission 接线；真实 DB/ERP/事件流
连接器、CDC、全量 R2RML 解析均另立项。所有新能力默认关闭（enabled=False），
默认零调用零网络。
"""
