# 自建中继（裸 systemd）部署指南

> 面向：Neurova 服务端跑在**无固定 IP / CGNAT** 网络里、但手上有一台
> **有固定域名或公网 IP** 服务器（VPS）的用户。目标：手机经你自己的服务器
> 回连家里的 Neurova，不再依赖开发者提供的公共入口。

## 1. 原理（30 秒版）

```
[手机 App] ── HTTPS/WSS ──▶ [你的服务器：neurova-relay] ◀── 出站隧道 ── [家里：Neurova 服务端]
```

- 家里的服务端**主动拨出**一条长连接挂到你的服务器上（不需要公网 IP、不开入站端口）；
- 手机扫码后连 `https://<你的域名>/t/<routeId>/...`，由这台中继把流量接回家里；
- 中继**终结 TLS**：它看得见经手流量。跑在你自己的服务器上，信任对象是你自己；
  若选 Cloudflare 之类第三方反代，等于把这份信任交给第三方（面板风险条目会提示）。

## 2. 准备

1. 一台 VPS（1 核 512MB 起步即可），已安装 systemd 与 Python 3.10+；
2. 一个域名，A/AAAA 记录指到这台 VPS；
3. TLS 证书（推荐 certbot standalone，见下）；
4. 本仓源码（`install.sh` 默认用脚本所在仓库；异机部署先 `git clone` 或打包上传）。

## 3. 部署（一条命令）

在 VPS 上、仓库根目录下以 root 执行：

```bash
sudo deploy/relay-systemd/install.sh --port 8443 \
  --tls-cert /etc/letsencrypt/live/pair.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/pair.example.com/privkey.pem
```

脚本做六件事（幂等，可重复执行更新）：建专用系统账号 → 拷贝中继最小文件集到
`/opt/neurova-relay/lib` → 建 venv 并只装 fastapi/uvicorn → 生成准入令牌
（`/etc/neurova-relay/enrollment_token`，首启生成后不变）→ 写
`/etc/neurova-relay/config.env` → 装并启动 `neurova-relay.service`。

证书获取（证书没配好时先跑这条，再重跑 install.sh 传证书路径）：

```bash
sudo certbot certonly --standalone -d pair.example.com
```

## 4. 回到 Neurova 配对面板

1. 打开「模型与工具 → 移动配对」页；
2. 「连接方式」选 **自建中继**，填：
   - 中继地址：`https://pair.example.com:8443`
   - 中继准入令牌：VPS 上 `/etc/neurova-relay/enrollment_token` 的值；
3. 点「预检连通性」——通过（绿）再发码；失败会给出具体原因
   （`tunnel_not_ready`＝服务端还没挂上中继；预检失败＝地址/证书/DNS 问题）；
4. 发码 → 手机扫码/输码 → 配对完成。此后地址漂移（VPS 重启、重注册）只需
   设备重连，不必重扫。

## 5. 故障对照

| 现象 | 含义与处置 |
|---|---|
| 面板通道徽标 `relay_down` | 服务端连不上你的中继：查 VPS 防火墙端口、令牌是否一致 |
| 发码 503 `tunnel_not_ready` | 同上的后端判据形态；中继注册成功后自动恢复发码 |
| 预检 `ok=false` | 面板所填地址本身不可达：查 DNS/证书/端口 |
| 手机连上即断（4001） | 凭证问题，与中继无关；重新配对或检查设备是否被解除 |

## 6. 令牌与安全

- 准入令牌是**唯一**准入凭据：谁拿到它，谁就能把一条隧道挂到你的域名下。
  它只存在 VPS 的 `/etc/neurova-relay/enrollment_token`（600）与 Neurova 服务端配置里；
- 面板读配置时令牌只回掩码；日志不落令牌；
- 更换令牌：VPS 上删掉 `enrollment_token` 重跑 install.sh（或手改 config.env 后
  `systemctl restart neurova-relay`），再回面板重填；
- 卸载：`systemctl disable --now neurova-relay && rm -rf /opt/neurova-relay
  /etc/neurova-relay && userdel neurova-relay`。

## 7. 与 Cloudflare 反代的区别

| | 自建中继（本指南） | Cloudflare 反代 |
|---|---|---|
| 信任对象 | 你自己的服务器 | Cloudflare（边缘终结 TLS，可见明文） |
| 依赖 | 一台 VPS + 域名 | Cloudflare 账号与其可用性 |
| 隧道形态 | 仓内 `neurova/relay`（自研，单源） | 用户自备（本仓只接受其地址，不集成其二进制） |
