# Neurova 渠道配置模板

> 渠道配置的**真实落点**是数据根下的 `channel_configs.json`，通过 REST 端点
> `/api/v1/channel-configs` 增删改查；保存后适配器立即注册并连接，服务重启时按
> 同一份配置自动装配。本模板给出各渠道的字段与凭据获取方式。

## 配置说明

### 飞书 (feishu)
```json
{
  "channel_type": "feishu",
  "enabled": true,
  "app_id": "cli_xxxxxxxxxxxxx",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
  "verification_token": "xxxxxxxxxxxxxxxxxxxxxxxx",
  "encrypt_key": "",
  "use_stream": true,
  "extra": {
    "domain": "feishu"
  }
}
```

**获取方式**:
1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 在"应用凭证"中获取 `App ID` 和 `App Secret`
4. 在"事件订阅"中获取 `Verification Token`（`Encrypt Key` 可不配；配置后密文回调会被明确拒绝，见下文安全注意事项）
5. 站点选择写进 `extra.domain`：国内飞书 `feishu` / 国际 Lark `lark`（也可填完整网关 URL）

---

### 企业微信 (wecom)
```json
{
  "channel_type": "wecom",
  "enabled": true,
  "app_id": "ww1234567890abcdef",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "webhook_token": "your_callback_token",
  "encrypt_key": "your_encoding_aes_key",
  "use_stream": true,
  "extra": {
    "agentid": "1000002"
  }
}
```

**获取方式**:
1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 在"应用管理"中创建应用
3. `app_id` 填企业 `CorpID`，`extra.agentid` 填应用 `AgentID`，`app_secret` 填应用 `Secret`
4. 回调模式的 `Token`/`EncodingAESKey` 分别填 `webhook_token`/`encrypt_key`（走智能机器人 WebSocket 长连接时填 `extra.mode: "aibot"`，无需公网回调）

---

### 微信 (wechat)
微信是**一个** `wechat` 渠道，用 `extra.mode` 区分三种接入方式（`ilink` / `wecom` / `official`），默认 `ilink`：

**iLink 模式（默认，个人微信扫码接入）**
```json
{
  "channel_type": "wechat",
  "enabled": true,
  "extra": {
    "mode": "ilink",
    "bot_token": "",
    "token_file": "~/.Neurova/weixin_bot_token"
  }
}
```
首次配置无需填 token：保存后接口返回 `needs_scan: true`，通过
`GET /api/v1/channel-configs/wechat/qrcode` 出码、`.../qrcode/status` 轮询，
扫码成功后 token 自动落盘，重存配置即认证成功。

**微信公众号模式（official）**
```json
{
  "channel_type": "wechat",
  "enabled": true,
  "extra": {
    "mode": "official",
    "appid": "wx1234567890abcdef",
    "secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "token": "your_webhook_token",
    "encoding_aes_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

**企业微信客服模式（wecom）**
```json
{
  "channel_type": "wechat",
  "enabled": true,
  "app_id": "ww1234567890abcdef",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "extra": {
    "mode": "wecom",
    "agentid": "1000002",
    "token": "your_webhook_token",
    "encoding_aes_key": "your_encoding_aes_key"
  }
}
```

**获取方式**:
1. 公众号：登录 [微信公众平台](https://mp.weixin.qq.com/)，在"开发" → "基本配置"中获取 `AppID`、`AppSecret`、服务器配置的 `Token` 和 `EncodingAESKey`
2. 企业微信客服：同企业微信后台，另在"微信客服"中创建客服账号拿 `open_kfid`
3. iLink：在渠道页扫码即可，无需预先申请

---

### Telegram (telegram)
```json
{
  "channel_type": "telegram",
  "enabled": true,
  "extra": {
    "bot_token": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"
  }
}
```

**获取方式**:
1. 在 Telegram 中与 [@BotFather](https://t.me/BotFather) 对话
2. 发送 `/newbot` 创建新机器人
3. 获取 Bot Token（格式：`数字:字母数字混合字符串`），填入 `extra.bot_token`
4. Webhook 模式需另设验签密钥：调 `POST /api/v1/channel-adapters/telegram/webhook/set`，body 带 `webhook_url` 与 `secret_token`（Telegram 回调时经 `X-Telegram-Bot-Api-Secret-Token` 头恒定时间比对）

---

### 其他内置渠道

`channel_type` 还支持：`dingtalk`（钉钉，`extra.client_id`/`extra.client_secret` 保存时会自动提升为 `app_id`/`app_secret`）、`discord`（`extra.bot_token`）、`qq`、`qqbot`（`extra.access_token`）、`xiaoyi`（`extra.access_key`/`extra.secret_key`）、`sip`（`extra.sip_username`/`extra.sip_password`）、`mqtt`（`extra.host`/`extra.port`/`extra.username`/`extra.password`）、`qclaw`、`voice`（Twilio：`app_id`=AccountSid、`app_secret`=AuthToken、`extra.from_number`=出振号）等。插件化自定义渠道的动态表单见 `GET /api/v1/channel-configs/schemas`。

---

## 完整配置示例（channel_configs.json）

```json
{
  "version": 2,
  "agents": {
    "default": {
      "feishu": {
        "channel_type": "feishu",
        "enabled": true,
        "app_id": "cli_xxxxxxxxxxxxx",
        "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
        "verification_token": "xxxxxxxxxxxxxxxxxxxxxxxx",
        "encrypt_key": "",
        "use_stream": true,
        "webhook_url": "",
        "extra": { "domain": "feishu" }
      },
      "telegram": {
        "channel_type": "telegram",
        "enabled": true,
        "app_id": "",
        "app_secret": "",
        "use_stream": true,
        "webhook_url": "",
        "extra": { "bot_token": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ" }
      },
      "wecom": {
        "channel_type": "wecom",
        "enabled": false,
        "app_id": "ww1234567890abcdef",
        "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "webhook_token": "your_callback_token",
        "encrypt_key": "your_encoding_aes_key",
        "use_stream": true,
        "extra": { "agentid": "1000002" }
      }
    }
  }
}
```

说明：
- 顶层结构是 `{version, agents}`，配置按 `(agent_id, channel_type)` 隔离落表；`version: 1` 的旧平铺结构会被自动迁移到 `default` agent 名下。
- 通用字段（`channel_type`/`enabled`/`app_id`/`app_secret`/`use_stream`/`webhook_url`/`webhook_token`/`encrypt_key`/`verification_token`/`extra`）由 `ChannelConfig` 定义；各平台专有键放 `extra`。
- `app_secret`、`extra` 里的 token 类字段落盘时会自动加密封存，读取接口返回的是掩码（如 `app_id` 前 8 位 + `***`）。

---

## 使用方式

### 1. 配置文件位置

```
<数据根>/channel_configs.json
```

数据根缺省是仓库根的 `data/`，可用环境变量 `NEUROVA_DATA_DIR` 注入到其他目录。
换锚前留在包内 `neurova/data/channel_configs.json` 的存量文件会在首次读取时被自动收养迁移。

### 2. 通过 REST 端点管理（推荐）

配置基路径 `/api/v1/channel-configs`（管理面），连接/收发基路径 `/api/v1/channel-adapters`（运行面）：

```bash
# 列出某 agent 的渠道配置
curl -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:9527/api/v1/channel-configs?agent_id=default"

# 创建/更新渠道配置（保存即注册适配器并连接；微信 iLink 无 token 时返回 needs_scan）
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"channel_type":"feishu","enabled":true,"app_id":"cli_xxx","app_secret":"xxx","verification_token":"xxx","use_stream":true,"extra":{"domain":"feishu"}}' \
  "http://127.0.0.1:9527/api/v1/channel-configs?agent_id=default"

# 测试连接（真实 connect + health_check 后断开）
curl -X POST -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:9527/api/v1/channel-configs/feishu/test?agent_id=default"

# 删除渠道配置
curl -X DELETE -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:9527/api/v1/channel-configs/feishu?agent_id=default"

# 运行面：查询健康 / 主动连接 / 断开 / 重启
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:9527/api/v1/channel-adapters/health/all"
curl -X POST -H "Authorization: Bearer <token>" "http://127.0.0.1:9527/api/v1/channel-adapters/feishu/connect"
curl -X POST -H "Authorization: Bearer <token>" "http://127.0.0.1:9527/api/v1/channel-adapters/feishu/restart?agent_id=default"
```

配置读写有归属门：`default` agent 仅管理员可配，有属主的 agent 仅属主可配。

### 3. 代码侧（ChannelManager）

`ChannelManager` 是运行期单例，负责适配器生命周期与消息路由；它**不读配置文件**——
配置的装载与持久化全部在 `channel_config.py` 的 REST 端点里完成：

```python
from neurova.channels.manager import get_channel_manager

manager = get_channel_manager()
manager.list_adapters()      # 当前 (agent_id, channel_type) 实例表
# manager.start() / manager.stop()   # 由服务启动脚本调用
# await manager.send_message(...)    # 经指定渠道实例外发
```

服务启动时会执行 `bootstrap_channel_adapters()`：逐 `(agent_id, channel_type)` 读取
`channel_configs.json`、跳过 `enabled=false` 与待扫码的微信 iLink、重建适配器并连接。

---

## 安全注意事项

1. **不要将配置文件提交到 Git**
   - `data/` 落点已整根豁免出库；若自定义了 `NEUROVA_DATA_DIR`，请确保该目录不在版本库内。

2. **凭据在磁盘上是加密封存的**
   - 保存时经 `sealSecrets()` 加密、读取时对称解密（`neurova/security/secret_store.py`）。
   - 加密密钥按 `NEUROVA_SECRET_KEY` 环境变量 → 系统钥匙串（keyring）→ 数据根下
     `.secret_key` 文件（自动生成）的顺序获取；生产环境建议显式配置 `NEUROVA_SECRET_KEY`。

3. **渠道凭据不走环境变量**
   - 代码不存在 `NEUROVA_FEISHU_APP_ID`、`NEUROVA_TELEGRAM_TOKEN` 之类的渠道凭据环境变量；
     凭据一律通过配置端点写入并封存。（唯一的密钥类环境变量是上述 `NEUROVA_SECRET_KEY`。）

4. **Webhook 回调逐渠道验签，全部 fail-closed**
   - 飞书：回调 token 与 `verification_token` 比对，未配置即拒绝；配置了 Encrypt Key 的密文回调会被明确拒绝（当前链路不解密），请勿在平台侧配置 Encrypt Key。
   - 钉钉：校验回调头 `timestamp` + `sign`（基于 app_secret 的 HMAC）。
   - 企业微信/微信客服：校验查询参数 `msg_signature`（基于 callback token 与 EncodingAESKey）。
   - Telegram：恒定时间比对 `X-Telegram-Bot-Api-Secret-Token` 头与 `webhook/set` 登记的 `secret_token`；未配置密钥的实例直接拒绝。
   - 同类型多实例时，由各实例自己的凭据裁决回调落到哪一只（凭据不匹配返回 404/403，不静默投递）。

5. **定期轮换密钥**
   - 建议每 90 天更换一次 API 密钥；轮换时更新配置端点里的对应字段即可。

6. **限制 Webhook IP**
   - 在飞书/微信/钉钉/企业微信后台设置回调 IP 白名单。

---

## Webhook 端点

平台回调的真实入口是：

```
POST /api/v1/channel-adapters/{channel_type}/webhook
```

仅 `feishu` / `dingtalk` / `wecom` / `wechat` / `telegram` 五类支持 webhook 回调
（其余渠道走长连接/轮询，无回调入口）。在平台后台填写的回调 URL 形如：

```
https://your-domain.com/api/v1/channel-adapters/feishu/webhook
https://your-domain.com/api/v1/channel-adapters/telegram/webhook
```

需要在服务器上配置反向代理时，整段透传即可：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # 渠道平台回调统一透传到后端（飞书/钉钉/企微/微信/Telegram 共用这一段）
    location /api/v1/channel-adapters/ {
        proxy_pass http://127.0.0.1:9527;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

**核对基准 2026-11-19，依据 neurova/api/endpoints/channels.py、channel_config.py、neurova/channels/**
