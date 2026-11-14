"""遥测 OTLP 导出（P2-13）。

把仓内错误/审计事件经 OTLP/HTTP JSON 导出到外部观测面（如 Loki/OTel Collector）：

- **显式开关**：``NEUROVA_TELEMETRY_ENABLED`` 默认 **0=关**——关时零网络零行为
  变化（record 只丢弃并计数）；
- **脱敏**：敏感键打码、字符串 512 截断、嵌套深度 8 截断（sanitize.py）；
- **fail-open**：导出失败只计 dropped，绝不阻断调用方；
- **接线点**：``error_logger`` 的写账路径（全仓错误事件单一咽喉）在写完本地
  账后转发一份到遥测（懒导入，失败静默）。

对照 ZCode 遥测面：OTLP 标准协议、错误脱敏只留 type/code/message、显式可关。
分布式二进制才需要的「端点构建期注入」在本仓以 env 等价表达（自托管形态）。
"""

from neurova.telemetry.client import TelemetryClient, getTelemetryClient, resetTelemetryClient
from neurova.telemetry.sanitize import sanitizeValue

__all__ = [
    "TelemetryClient",
    "getTelemetryClient",
    "resetTelemetryClient",
    "sanitizeValue",
]
