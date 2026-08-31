# MCP 治理与安全加固

> 状态: ✅ 已实现 · 版本: v1.0.0-beta1 · 代码: `neurova/tool_layers/` + `neurova/security/`

## 概述

Model Context Protocol (MCP) 集成层经过 P0-1 ~ P0-6 六项安全治理加固，从"半成品"到生产级多用户隔离。

## 修复清单（P0-1 ~ P0-6）

| 编号 | 漏洞 | 修复 |
|------|------|------|
| **M1** | 未认证 RCE（tool_layers 无鉴权） | 路由器加鉴权依赖，stdio 仅 admin |
| **M2** | stdio command/args 无白名单 | shell 拒绝表 + 命令白名单 |
| **M3** | ToolRouter 主路径绕过防火墙 | 防火墙收敛进 `call_tool` 主路径 |
| **M4** | 治理预检只提取 4 个键名 | 全参数扫描（scan_all），分级 fail-closed |
| **M5** | MCP 客户端跨用户单例 | 防火墙身份按请求穿透（ContextVar 注入） |
| **M6** | 零重连/退避/熔断/健康探测 | 配置收敛 + 死路清理（P1 待完善） |
| **M7-M10** | 配置分叉、死代码、键名 bug | 存储收敛、ToolEngine 懒获取、server_id 修复 |

## 安全架构

```
请求 → JWT 鉴权 → 角色门（admin/user） → 防火墙预检 → 参数扫描 → 审计落盘 → 执行
        ↓        ↓          ↓                  ↓               ↓
     L0 入口   L1 隔离    L2 输出            L3 审计        L4 数据
```

## 关键文件

```
neurova/tool_layers/
├── mcp_client.py          # MCP 客户端（隔离会话）
├── mcp_config.py          # MCP 配置（收敛/掩码）
├── mcp_bootstrap.py       # MCP 启动
├── tool_router.py         # 工具路由（防火墙主路径）
├── tool_marketplace.py    # 工具市场
├── tool_orchestrator.py   # 工具编排
└── tool_logger.py         # 工具日志

neurova/security/
├── url_guard.py           # SSRF 防护（私网/环回/链路本地）
└── governance.py          # 治理评估（全参数扫描 + fail-closed）
```

## 设计理念

MCP 是 Neurova 的"第三只手"——连接外部工具生态。安全加固确保这只手看得见、可控、可审计，不会成为攻击入口。

## 相关文档

- [工具层实现总结](../05-reports/tool_layers_implementation_summary.md)
- [ADRs 复用](../01-architecture/adr/README.md)
