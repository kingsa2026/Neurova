# Neurova 自建中继 —— 裸 systemd 部署包

把仓内的 [`neurova/relay`](../../neurova/relay/app.py)（自研中继）部署到一台
**有固定域名/公网 IP** 的服务器上，让无固定 IP 的 Neurova 服务端经出站隧道接到
公网入口，手机即可扫码配对回连。

文件：

- `install.sh` —— 幂等安装脚本（建专用系统用户、拷最小文件集、建 venv、生成准入令牌、装 systemd 单元并启动）。
- `neurova-relay.service` —— systemd 单元（专用账号 + `ProtectSystem=strict` 加固）。

快速使用（服务器上以 root 执行）：

```bash
sudo ./install.sh --port 8443 \
  --tls-cert /etc/letsencrypt/live/pair.example.com/fullchain.pem \
  --tls-key  /etc/letsencrypt/live/pair.example.com/privkey.pem
```

随后回到 Neurova 配对面板：「连接方式 → 自建中继」，填 `https://<你的域名>:8443`
与本机 `/etc/neurova-relay/enrollment_token` 里的准入令牌，点「预检连通性」，
通过后即可发码配对。

完整说明（DNS/TLS 获取、令牌安全、卸载、故障对照）见
[`docs/03-user-guide/RELAY_SELF_HOSTING_GUIDE.md`](../../docs/03-user-guide/RELAY_SELF_HOSTING_GUIDE.md)。
