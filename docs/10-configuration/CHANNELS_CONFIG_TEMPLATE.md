# Neurova 渠道 API 配置模板

> 将实际 API 密钥填入此文件后，重命名为 `channels_config.json`

## 配置说明

### 飞书 (Feishu)
```json
{
  "feishu": {
    "app_id": "cli_xxxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
    "verification_token": "xxxxxxxxxxxxxxxxxxxxxxxx",
    "encrypt_key": "xxxxxxxxxxxxxxxxxxxxxxxx",
    "region": "cn"
  }
}
```

**获取方式**:
1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 在"应用凭证"中获取 `App ID` 和 `App Secret`
4. 在"事件订阅"中获取 `Verification Token` 和 `Encrypt Key`
5. 地区选择：国内 `cn` / 国际 `sg`

---

### 微信公众号 (WeChat Official)
```json
{
  "wechat_official": {
    "appid": "wx1234567890abcdef",
    "secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "token": "your_webhook_token",
    "encoding_aes_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

**获取方式**:
1. 登录 [微信公众平台](https://mp.weixin.qq.com/)
2. 在"开发" → "基本配置"中获取 `AppID` 和 `AppSecret`
3. 设置服务器配置中的 `Token` 和 `EncodingAESKey`

---

### 企业微信 (WeChat Work)
```json
{
  "wechat_wecom": {
    "corpid": "ww1234567890abcdef",
    "corpsecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "agentid": "1000002"
  }
}
```

**获取方式**:
1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)
2. 在"应用管理"中创建应用
3. 获取 `CorpID`、`AgentID` 和应用 `Secret`

---

### Telegram Bot
```json
{
  "telegram": {
    "token": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
    "proxy": {
      "host": "127.0.0.1",
      "port": 1080,
      "username": "",
      "password": ""
    }
  }
}
```

**获取方式**:
1. 在 Telegram 中与 [@BotFather](https://t.me/BotFather) 对话
2. 发送 `/newbot` 创建新机器人
3. 获取 Bot Token（格式：`数字:字母数字混合字符串`）
4. 国内使用需要配置代理

---

## 完整配置示例

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "cli_xxxxxxxxxxxxx",
      "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx",
      "verification_token": "xxxxxxxxxxxxxxxxxxxxxxxx",
      "encrypt_key": "xxxxxxxxxxxxxxxxxxxxxxxx",
      "region": "cn",
      "webhook_url": "https://your-domain.com/webhook/feishu"
    },
    "wechat_official": {
      "enabled": true,
      "appid": "wx1234567890abcdef",
      "secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "token": "your_webhook_token",
      "encoding_aes_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "wechat_wecom": {
      "enabled": false,
      "corpid": "ww1234567890abcdef",
      "corpsecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "agentid": "1000002"
    },
    "telegram": {
      "enabled": true,
      "token": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
      "proxy": {
        "host": "127.0.0.1",
        "port": 1080
      },
      "webhook_url": "https://your-domain.com/webhook/telegram"
    }
  },
  "global": {
    "default_agent": "Yiling",
    "session_timeout": 3600,
    "max_history_messages": 100
  }
}
```

---

## 使用方式

### 1. 配置文件位置

```
/opt/neurova/config/channels_config.json
```

### 2. 加载配置

```python
from neurova.channels.manager import ChannelManager

# 从配置文件加载
manager = ChannelManager()
manager.load_config("/opt/neurova/config/channels_config.json")

# 启动渠道
manager.enable_channel("feishu")
manager.enable_channel("telegram")
```

### 3. CLI 方式

```bash
# 启动 CLI
cd /opt/neurova && python neurova/start.py cli

# 配置渠道
> config channel feishu app_id cli_xxxxx
> config channel feishu app_secret xxxxxxxx
> config channel telegram token 1234567890:ABC...
```

---

## 安全注意事项

1. **不要将配置文件提交到 Git**
   - 确保 `channels_config.json` 在 `.gitignore` 中
   
2. **使用环境变量 (推荐)**
   ```bash
   export NEUROVA_FEISHU_APP_ID="cli_xxxxx"
   export NEUROVA_FEISHU_APP_SECRET="xxxxxx"
   export NEUROVA_TELEGRAM_TOKEN="1234567890:ABC..."
   ```

3. **定期轮换密钥**
   - 建议每 90 天更换一次 API 密钥
   
4. **限制 Webhook IP**
   - 在飞书/微信后台设置 Webhook 回调 IP 白名单

---

## Webhook 端点

配置渠道后，需要在服务器上配置反向代理：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    # 飞书 Webhook
    location /webhook/feishu {
        proxy_pass http://127.0.0.1:9527/webhook/feishu;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # 微信 Webhook
    location /webhook/wechat {
        proxy_pass http://127.0.0.1:9527/webhook/wechat;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # Telegram Webhook
    location /webhook/telegram {
        proxy_pass http://127.0.0.1:9527/webhook/telegram;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 测试渠道连接

```python
from neurova.channels.manager import ChannelManager

manager = ChannelManager()
manager.load_config("channels_config.json")

# 测试飞书
result = manager.test_channel("feishu")
print(f"飞书连接: {'成功' if result.success else result.error}")

# 测试 Telegram
result = manager.test_channel("telegram")
print(f"Telegram 连接: {'成功' if result.success else result.error}")
```

---

**配置完成后，记得告诉我密钥类型（飞书/微信/Telegram），我可以帮你验证连接！** 🚀
