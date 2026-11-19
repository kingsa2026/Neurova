#!/usr/bin/env bash
# Neurova 自建中继 —— 裸 systemd 一键部署（设计方案 §8-S2 的部署形态，档二）。
#
# 在**有固定域名/公网 IP** 的服务器上以 root 运行：
#   sudo ./install.sh [--source /path/to/neurova] [--port 8443]
#                     [--tls-cert /etc/.../fullchain.pem --tls-key /etc/.../privkey.pem]
#
# 幂等：重复执行只更新代码与配置；准入令牌只在首次生成，之后保持不变
# （后端面板里填的 relayUrl/token 是长期凭据，换了就得回面板重填）。
# TLS：中继终结 TLS（已裁决策）。证书获取建议 certbot standalone，把
# fullchain.pem/privkey.pem 路径经 --tls-cert/--tls-key 传进来即可。
set -euo pipefail

SERVICE_NAME=neurova-relay
SERVICE_USER=neurova-relay
INSTALL_DIR=/opt/neurova-relay
CONFIG_DIR=/etc/neurova-relay

# 中继运行的最小文件集（相对仓库根）。加依赖时同步 tests/unit/relay 的咬合判据——
# 那边会按这份清单做"最小集可独立运行"的验证，两边不同步就会在服务器上才炸。
RELAY_FILES=(
  "neurova/__init__.py"
  "neurova/core/__init__.py"
  "neurova/core/logger.py"
  "neurova/core/trace_context.py"
  "neurova/core/config.py"
  "neurova/tunnel/__init__.py"
  "neurova/tunnel/protocol.py"
  "neurova/relay/__init__.py"
  "neurova/relay/app.py"
  "neurova/relay/__main__.py"
)

SOURCE_DIR=""
RELAY_PORT=""
TLS_CERT=""
TLS_KEY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)   SOURCE_DIR="$2"; shift 2 ;;
    --port)     RELAY_PORT="$2"; shift 2 ;;
    --tls-cert) TLS_CERT="$2"; shift 2 ;;
    --tls-key)  TLS_KEY="$2"; shift 2 ;;
    *) echo "未知参数：$1（支持 --source/--port/--tls-cert/--tls-key）" >&2; exit 1 ;;
  esac
done

[[ ${EUID} -eq 0 ]] || { echo "请以 root 运行（要写 /opt、/etc 并装 systemd 服务）" >&2; exit 1; }
: "${SOURCE_DIR:=$(cd -- "$(dirname -- "$0")/../.." && pwd)}"
SOURCE_DIR=$(cd "$SOURCE_DIR" && pwd)
for rel in "${RELAY_FILES[@]}"; do
  [[ -f "$SOURCE_DIR/$rel" ]] || { echo "源码树缺文件：$SOURCE_DIR/$rel" >&2; exit 1; }
done

echo "==> 1/6 专用系统用户（最小权限，无 home 不可登录）"
id -u "$SERVICE_USER" >/dev/null 2>&1 || \
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"

echo "==> 2/6 拷贝最小文件集到 $INSTALL_DIR/lib"
rm -rf "$INSTALL_DIR/lib"
mkdir -p "$INSTALL_DIR/lib" "$INSTALL_DIR/venv" "$CONFIG_DIR"
for rel in "${RELAY_FILES[@]}"; do
  mkdir -p "$INSTALL_DIR/lib/$(dirname "$rel")"
  cp "$SOURCE_DIR/$rel" "$INSTALL_DIR/lib/$rel"
done

echo "==> 3/6 虚拟环境（relay 只依赖 fastapi/uvicorn，不拖全量依赖）"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet fastapi 'uvicorn[standard]'

echo "==> 4/6 准入令牌（首启生成，之后不变）"
TOKEN_FILE="$CONFIG_DIR/enrollment_token"
if [[ -s "$TOKEN_FILE" ]]; then
  ENROLLMENT_TOKEN=$(tr -d '\r\n' < "$TOKEN_FILE")
else
  ENROLLMENT_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf '%s' "$ENROLLMENT_TOKEN" > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"

echo "==> 5/6 配置与环境文件"
{
  echo "NEUROVA_RELAY_ENROLLMENT_TOKEN=$ENROLLMENT_TOKEN"
  echo "NEUROVA_RELAY_PORT=${RELAY_PORT:-8443}"
  [[ -n "$TLS_CERT" ]] && echo "NEUROVA_RELAY_TLS_CERT=$TLS_CERT"
  [[ -n "$TLS_KEY" ]] && echo "NEUROVA_RELAY_TLS_KEY=$TLS_KEY"
} > "$CONFIG_DIR/config.env"
chmod 600 "$CONFIG_DIR/config.env"

echo "==> 6/6 systemd 单元与启动"
cp "$(cd -- "$(dirname -- "$0")" && pwd)/neurova-relay.service" \
   "/etc/systemd/system/$SERVICE_NAME.service"
chown root:root "/etc/systemd/system/$SERVICE_NAME.service"
chmod 644 "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl --no-pager --lines=3 status "$SERVICE_NAME" || true

cat <<EOF

部署完成。下一步：
  1) 把你的域名解析到这台机器，并备好 TLS 证书（certbot standalone 一条命令：
     certbot certonly --standalone -d <你的域名>；续期后 systemctl restart $SERVICE_NAME）；
  2) 回到 Neurova 配对面板，选「自建中继」，填：
     - 中继地址：https://<你的域名>[:${RELAY_PORT:-8443}]
     - 准入令牌：（本机 $TOKEN_FILE 里的值）
  3) 面板「预检连通性」通过后即可发码配对（手机经 https://<域名>/t/<route>/... 回连）。
EOF
