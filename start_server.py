#!/usr/bin/env python3
"""
启动 Neurova API 服务器
"""

import sys
import os
import logging

# 强制 UTF-8 输出：stdout/stderr 重定向到文件时 Python 默认用系统 ANSI
# 代码页（中文 Windows = GBK），桌面壳按 UTF-8 读取会乱码。须在 stderr
# 首次使用前设置（io 编码在解释器初始化后只认环境变量/重配置）。
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
# 日志级别读 NEUROVA_LOG_LEVEL（ConfigMap/env 注入面）：此前写死 INFO，
# 于是 Helm/compose 里设的日志级别（且键名还写成 LOG_LEVEL）完全无效。
_LOG_LEVEL_NAME = os.environ.get("NEUROVA_LOG_LEVEL", "INFO").strip().upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, None)
if not isinstance(_LOG_LEVEL, int):
    _LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

try:
    from neurova.core.port_guard import PortUnavailableError
except Exception:  # noqa: BLE001 - 判据缺席时退化为"无此类"，不阻断入口
    class PortUnavailableError(RuntimeError):  # type: ignore[no-redef]
        """占位：port_guard 不可导入时不该让入口本身炸在 import 期。"""


def _get_app_version():
    try:
        from neurova import __version__

        return __version__
    except Exception:
        return "unknown"


def main():
    """启动服务器"""
    print("=" * 60)
    print("Starting Neurova API Server...")
    print("=" * 60)

    try:
        import uvicorn

        from neurova.api.app import create_app

        # 端口预检必须在**任何重型装配之前**：uvicorn 的次序是 lifespan.startup()
        # 先跑完、再 loop.create_server()，所以端口被占的失败会落在全量装配（实测
        # 约 8 秒：4 个 Agent、LLM providers、DB、torch 预检、1253 行日志）之后，
        # 且还会再触发一轮完整关机整理——真正的失败信息被埋在日志尾部。
        # 判据与 `start.py` 同源（neurova/core/port_guard.py），两套启动器行为一致。
        host = os.environ.get("NEUROVA_HOST", "0.0.0.0")
        port = int(os.environ.get("NEUROVA_PORT", "9527"))
        try:
            from neurova.core.port_guard import preflightPortAvailable

            preflightPortAvailable(host, port)
        except PortUnavailableError:
            raise
        except Exception as _port_probe_err:  # noqa: BLE001 - 探针自身故障不阻断启动
            print(f"Warning: 端口预检无法执行（忽略）: {_port_probe_err}")

        # torch 环境预检：c10.dll 初始化失败（缺 VC++ 运行库）→ 自动下载安装。
        # 任何失败只告警，不阻断启动。
        try:
            from neurova.core.env_check import preflight_torch_runtime

            preflight_torch_runtime()
        except Exception as _env_err:  # noqa: BLE001 - 预检失败不阻断启动
            print(f"Warning: torch 环境预检失败（忽略）: {_env_err}")

        # 进化权重持久化装配（显式；单例本身零 IO 副作用）
        try:
            from neurova.evolution.closed_loop import bootstrap_evolution_persistence

            bootstrap_evolution_persistence()
        except Exception as _persist_err:  # noqa: BLE001 - 权重恢复失败不阻断启动
            print(f"Warning: 进化权重恢复失败（忽略）: {_persist_err}")

        # C12：RSI 优化回执路径（显式注入，保单例零 IO 默认）
        # 工单 004：回滚时间线（回滚历史 + 装配时刻）同款注入 ——
        # 它是 phase 1→2"7 天无回滚"判据的唯一真实数据来源，
        # 不设则该起算点每次重启归零，晋升条件在真实部署里永不可满足。
        # 必须在 agent 构造 RSIOrchestrator 之前注入。
        try:
            import os as _os

            from neurova.core.data_root import dataLanding

            # 落点必须是**绝对**路径：原值 `data/evolution/...` 是 CWD 相对，
            # 换个启动目录就把回执与回滚时间线写散（后端冒烟实测 CWD 多出
            # `data/evolution/rsi_rollback.json`）。这两份是"7 天无回滚"判据的
            # 唯一数据来源，散落等于判据在真实部署里永不可满足。
            _os.environ.setdefault(
                "NEUROVA_RSI_RECEIPTS", str(dataLanding("evolution", "rsi_receipts.jsonl")))
            _os.environ.setdefault(
                "NEUROVA_EVOLUTION_ROLLBACK", str(dataLanding("evolution", "rsi_rollback.json")))
        except Exception as _receipt_err:  # noqa: BLE001
            print(f"Warning: 回执路径注入失败（忽略）: {_receipt_err}")

        # 工具层防护装配（C5：env 门控，默认关——NEUROVA_TOOL_CIRCUIT_BREAKER /
        # NEUROVA_TOOL_PARAM_GUARD 置 1 开启）
        try:
            from neurova.evolution.closed_loop import bootstrap_evolution_protections

            _protections = bootstrap_evolution_protections()
            if any(_protections.values()):
                print(f"工具层防护已装配: {_protections}")
        except Exception as _protect_err:  # noqa: BLE001 - 防护装配失败不阻断启动
            print(f"Warning: 工具层防护装配失败（忽略）: {_protect_err}")

        # 创建应用
        app = create_app()

        print(f"App: {app.title}")
        print(f"Version: {app.version}")

        # 启动服务器
        # host/port 已在上方预检处读出（默认 0.0.0.0:9527，与 Dockerfile EXPOSE /
        # compose 映射 / Helm service 同源；跨文件一致性见
        # scripts/ci/deploy_config_consistency_check.py 的 R1）。
        print(f"Health: http://{host}:{port}/health")
        print("=" * 60)
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=_LOG_LEVEL_NAME.lower(),
        )

    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except PortUnavailableError as e:
        # 端口被占是**可自辨的启动失败**：不是崩溃，也不必走启动失败上报
        # （那是给"解释器都起不来"这类故障用的）。一条点名端口的显式提示就够。
        print()
        print(f"[启动中止] {e}")
        return 1
    except Exception as e:
        print(f"Server failed to start: {e}")
        import traceback
        traceback.print_exc()

        # 启动失败上报远程错误日志（尽力而为：无网/关闭/失败都不影响退出）
        try:
            from neurova.core.crash_report import report_startup_failure

            report_startup_failure(e, stage="startup", app_version=_get_app_version())
        except Exception:
            pass
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
