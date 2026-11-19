"""`python -m neurova.relay` —— 自建中继的独立运行入口（档二：裸 systemd 部署）。

只依赖仓内 `neurova.relay` 与清单内的 FastAPI/uvicorn。配置来源优先级：
命令行 > 环境变量 > 默认值。

- 准入令牌：`--enrollment-token` / `NEUROVA_RELAY_ENROLLMENT_TOKEN`（必填；
  空令牌等于没有入口，直接拒绝启动——与 `create_relay_app` 的既有语义一致）。
- 监听：`--host` / `--port`（env `NEUROVA_RELAY_HOST`/`NEUROVA_RELAY_PORT`，
  默认 0.0.0.0:8443）。
- TLS：`--tls-cert`/`--tls-key`（env `NEUROVA_RELAY_TLS_CERT`/`NEUROVA_RELAY_TLS_KEY`；
  中继终结 TLS 是已裁决策（设计方案 §1-2）——生产必须配证书，本地开发可先裸 HTTP）。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import uvicorn

from neurova.relay.app import create_relay_app


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurova-relay", description="Neurova 自建中继")
    parser.add_argument("--host", default=os.environ.get("NEUROVA_RELAY_HOST", "0.0.0.0"),
                        help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("NEUROVA_RELAY_PORT", "8443")),
                        help="监听端口（默认 8443）")
    parser.add_argument("--enrollment-token",
                        default=os.environ.get("NEUROVA_RELAY_ENROLLMENT_TOKEN", ""),
                        help="agent 注册用的准入令牌（必填）")
    parser.add_argument("--tls-cert", default=os.environ.get("NEUROVA_RELAY_TLS_CERT", ""),
                        help="TLS 证书（PEM）；中继终结 TLS，生产必配")
    parser.add_argument("--tls-key", default=os.environ.get("NEUROVA_RELAY_TLS_KEY", ""),
                        help="TLS 私钥（PEM）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = buildParser().parse_args(argv)

    token = (args.enrollment_token or "").strip()
    if not token:
        print("拒绝启动：未配置准入令牌（--enrollment-token 或 NEUROVA_RELAY_ENROLLMENT_TOKEN）。"
              "空令牌等于没有入口。", file=sys.stderr)
        return 2

    tlsArgs: dict = {}
    if args.tls_cert or args.tls_key:
        if not (args.tls_cert and args.tls_key):
            print("TLS 证书与私钥必须成对提供（--tls-cert / --tls-key）。", file=sys.stderr)
            return 2
        tlsArgs = {"ssl_certfile": args.tls_cert, "ssl_keyfile": args.tls_key}

    app = create_relay_app(token)
    uvicorn.run(app, host=args.host, port=args.port, **tlsArgs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
