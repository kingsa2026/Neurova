"""
MQTT 消息渠道适配器

支持:
- MQTT 3.1.1 / 5.0 协议
- TCP / TLS / WebSocket 传输
- QoS 0/1/2 消息质量
- 主题订阅和发布
- 认证和 TLS 加密

依赖:
pip install paho-mqtt
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class MQTTAdapter(ChannelAdapter):
    """
    MQTT 消息渠道适配器

    支持:
    - MQTT 3.1.1 / 5.0 协议
    - TCP / TLS / WebSocket 传输
    - QoS 0/1/2 消息质量
    - 主题订阅和发布
    - 认证和 TLS 加密
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.MQTT

    def __init__(self):
        # 基础配置
        self.bot_prefix = "@bot"
        self.show_tool_messages = True
        self.show_thinking = True

        # MQTT 连接配置
        self.host = "127.0.0.1"
        self.port = 1883
        self.transport = "tcp"  # tcp / ssl / websockets / websockets_ssl
        self.username = ""
        self.password = ""
        self.clean_session = True
        self.qos = 2

        # 主题配置
        self.subscribe_topic = "server/+/up"
        self.publish_topic = "client/{client_id}/down"

        # TLS 配置
        self.tls_enabled = False
        self.tls_ca_certs = ""
        self.tls_certfile = ""
        self.tls_keyfile = ""

        # 内部状态
        self._initialized = False
        self._client = None
        self._connected = False
        self._client_id = f"neurova_{int(time.time())}"
        self._message_queue = []

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证 MQTT 连接

        参数:
        config: {
            "bot_prefix": "@bot",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
            "host": "MQTT 服务器地址",
            "port": "1883",
            "transport": "tcp/ssl/websockets/websockets_ssl",
            "username": "用户名",
            "password": "密码",
            "clean_session": "true/false",
            "qos": "0/1/2",
            "subscribe_topic": "订阅主题",
            "publish_topic": "发布主题",
            "tls_enabled": "true/false",
            "tls_ca_certs": "CA 证书路径",
            "tls_certfile": "客户端证书路径",
            "tls_keyfile": "客户端私钥路径",
        }
        """
        # 基础配置
        self.bot_prefix = config.get("bot_prefix", "@bot")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"

        # MQTT 连接配置
        self.host = config.get("host", "127.0.0.1")
        self.port = int(config.get("port", "1883"))
        self.transport = config.get("transport", "tcp")
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.clean_session = config.get("clean_session", "true").lower() == "true"
        self.qos = int(config.get("qos", "2"))

        # 主题配置
        self.subscribe_topic = config.get("subscribe_topic", "server/+/up")
        self.publish_topic = config.get("publish_topic", "client/{client_id}/down")

        # TLS 配置
        self.tls_enabled = config.get("tls_enabled", "false").lower() == "true"
        self.tls_ca_certs = config.get("tls_ca_certs", "")
        self.tls_certfile = config.get("tls_certfile", "")
        self.tls_keyfile = config.get("tls_keyfile", "")

        return self._init_connection()

    def _init_connection(self) -> bool:
        """初始化 MQTT 连接"""
        if not MQTT_AVAILABLE:
            logging.warning("paho-mqtt 未安装，MQTT 模式不可用")
            logging.info("安装命令: pip install paho-mqtt")
            self._initialized = True  # 模拟初始化
            return True

        try:
            # 创建 MQTT 客户端
            self._client = mqtt.Client(
                client_id=self._client_id, clean_session=self.clean_session, transport=self.transport
            )

            # 设置回调
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message
            self._client.on_subscribe = self._on_subscribe
            self._client.on_publish = self._on_publish

            # 设置认证
            if self.username:
                self._client.username_pw_set(self.username, self.password)

            # BUG-41: TLS配置初始化 - 验证证书路径有效性
            if self.tls_enabled:
                import os

                tls_kwargs = {}
                if self.tls_ca_certs:
                    if not os.path.exists(self.tls_ca_certs):
                        logging.warning("TLS CA 证书文件不存在: %s，跳过TLS", self.tls_ca_certs)
                    else:
                        tls_kwargs["ca_certs"] = self.tls_ca_certs
                if self.tls_certfile:
                    if not os.path.exists(self.tls_certfile):
                        logging.warning("TLS 证书文件不存在: %s，跳过TLS", self.tls_certfile)
                    else:
                        tls_kwargs["certfile"] = self.tls_certfile
                if self.tls_keyfile:
                    if not os.path.exists(self.tls_keyfile):
                        logging.warning("TLS 私钥文件不存在: %s，跳过TLS", self.tls_keyfile)
                    else:
                        tls_kwargs["keyfile"] = self.tls_keyfile

                if tls_kwargs:
                    self._client.tls_set(**tls_kwargs)
                    self._log_info("MQTT TLS 配置已启用")
                else:
                    logging.warning("TLS 启用但证书文件无效，使用非TLS连接")

            # 连接到服务器
            self._client.connect(self.host, self.port, keepalive=60)

            # 启动循环（非阻塞）
            self._client.loop_start()

            # BUG-18: 连接失败清理 + 订阅重试
            if not self._client.is_connected():
                logging.warning(f"MQTT 连接超时，清理资源并准备重试")
                self.disconnect()
                return False

            logging.info("MQTT 连接初始化成功 - 服务器: %s:%s", self.host, self.port)
            self._initialized = True
            return True

        except Exception as e:
            logging.error("MQTT 连接初始化失败: %s", e)
            return False

    def _on_connect(self, client, userdata, flags, rc):
        """连接成功回调"""
        if rc == 0:
            self._connected = True
            logging.info("MQTT 连接成功 - Client ID: %s", self._client_id)

            # 订阅主题
            if self.subscribe_topic:
                result, mid = client.subscribe(self.subscribe_topic, qos=self.qos)
                if result == mqtt.MQTT_ERR_SUCCESS:
                    logging.info("MQTT 订阅成功: %s", self.subscribe_topic)
                else:
                    logging.error("MQTT 订阅失败: %s", self.subscribe_topic)
        else:
            logging.error("MQTT 连接失败，返回码: %s", rc)

    def _on_disconnect(self, client, userdata, rc):
        """断开连接回调"""
        self._connected = False
        logging.info("MQTT 连接断开，返回码: %s", rc)

    def _on_message(self, client, userdata, msg):
        """收到消息回调"""
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
            logging.debug("MQTT 收到消息 [%s]: %s", msg.topic, payload[:100])

            # 解析消息
            unified_msg = self._parse_mqtt_message(msg, payload)
            if unified_msg:
                self._message_queue.append(unified_msg)
        except Exception as e:
            logging.error("MQTT 消息处理异常: %s", e)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """订阅成功回调"""
        logging.info("MQTT 订阅确认，QoS: %s", granted_qos)

    def _on_publish(self, client, userdata, mid):
        """发布成功回调"""
        logging.debug("MQTT 消息发布确认，Message ID: %s", mid)

    def _parse_mqtt_message(self, msg, payload: str) -> Optional[UnifiedMessage]:
        """解析 MQTT 消息"""
        try:
            # 尝试解析 JSON 格式的消息
            data = json.loads(payload)
        except json.JSONDecodeError:
            # 如果不是 JSON，直接使用原始文本
            data = {"content": payload}

        # 提取消息信息
        message_id = data.get("message_id", f"mqtt_{int(time.time())}")
        user_id = data.get("user_id", msg.topic)
        content = data.get("content", payload)
        timestamp_str = data.get("timestamp", "")

        # 解析时间戳
        timestamp = None
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # 提取 chat_id（从主题或消息中）
        chat_id = data.get("chat_id", msg.topic)

        return UnifiedMessage(
            message_id=message_id,
            channel=MessageChannel.MQTT,
            chat_id=chat_id,
            user_id=user_id,
            agent_id="",
            content=content,
            content_type=ContentType.TEXT,
            timestamp=timestamp,
            global_user_id=f"mqtt:{user_id}",
            session_id=f"mqtt:{chat_id}",
            raw_message={
                "topic": msg.topic,
                "qos": msg.qos,
                "retain": msg.retain,
                "payload": payload,
                "data": data,
            },
            metadata={
                "topic": msg.topic,
                "qos": msg.qos,
                "retain": msg.retain,
            },
        )

    def send_message(self, message: UnifiedMessage) -> bool:
        """发送 MQTT 消息"""
        if not self._initialized or not self._connected:
            logging.error("MQTT 未连接")
            return False

        if not MQTT_AVAILABLE or not self._client:
            logging.info("[MQTT模拟] 发布到 %s: %s", self.publish_topic, message.content[:50])
            return True

        try:
            # 构建发布主题（替换 {client_id} 占位符）
            topic = self.publish_topic.replace("{client_id}", message.chat_id or "default")

            # 构建消息体
            payload = {
                "message_id": message.message_id,
                "content": message.content,
                "content_type": message.content_type.value,
                "timestamp": datetime.now().isoformat(),
                "chat_id": message.chat_id,
                "agent_id": message.agent_id,
            }

            # 添加额外元数据
            if message.metadata:
                payload["metadata"] = message.metadata

            # 发布消息
            result, mid = self._client.publish(
                topic, payload=json.dumps(payload, ensure_ascii=False), qos=self.qos, retain=False
            )

            if result == mqtt.MQTT_ERR_SUCCESS:
                logging.debug("MQTT 消息发布成功 [%s]", topic)
                return True
            else:
                logging.error("MQTT 消息发布失败: %s", result)
                return False

        except Exception as e:
            logging.error("MQTT 消息发送异常: %s", e)
            return False

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收 MQTT 消息"""
        if self._message_queue:
            return self._message_queue.pop(0)
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析 MQTT 原始消息

        参数:
        raw_data: 包含 topic 和 payload 的字典
        """
        if isinstance(raw_data, dict):
            topic = raw_data.get("topic", "")
            payload = raw_data.get("payload", "")

            # 创建模拟的 msg 对象
            class MockMsg:
                def __init__(self, topic, payload):
                    self.topic = topic
                    self.payload = payload.encode("utf-8") if isinstance(payload, str) else payload
                    self.qos = 0
                    self.retain = False

            msg = MockMsg(topic, payload)
            return self._parse_mqtt_message(msg, payload)

        return None

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置"""
        return {
            "channel": self.channel.value,
            "host": self.host,
            "port": self.port,
            "transport": self.transport,
            "username": self.username,
            "clean_session": self.clean_session,
            "qos": self.qos,
            "subscribe_topic": self.subscribe_topic,
            "publish_topic": self.publish_topic,
            "tls_enabled": self.tls_enabled,
            "connected": self._connected,
            "authenticated": self._initialized,
        }

    def update_config(self, config_updates: Dict):
        """更新配置"""
        if "host" in config_updates:
            self.host = config_updates["host"]
        if "port" in config_updates:
            self.port = int(config_updates["port"])
        if "transport" in config_updates:
            self.transport = config_updates["transport"]
        if "username" in config_updates:
            self.username = config_updates["username"]
        if "password" in config_updates:
            self.password = config_updates["password"]
        if "clean_session" in config_updates:
            self.clean_session = config_updates["clean_session"]
        if "qos" in config_updates:
            self.qos = int(config_updates["qos"])
        if "subscribe_topic" in config_updates:
            self.subscribe_topic = config_updates["subscribe_topic"]
        if "publish_topic" in config_updates:
            self.publish_topic = config_updates["publish_topic"]
        if "tls_enabled" in config_updates:
            self.tls_enabled = config_updates["tls_enabled"]
        if "tls_ca_certs" in config_updates:
            self.tls_ca_certs = config_updates["tls_ca_certs"]
        if "tls_certfile" in config_updates:
            self.tls_certfile = config_updates["tls_certfile"]
        if "tls_keyfile" in config_updates:
            self.tls_keyfile = config_updates["tls_keyfile"]

    def disconnect(self):
        """断开 MQTT 连接"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logging.info("MQTT 连接已断开")


def create_mqtt_adapter(
    host: str = "127.0.0.1", port: int = 1883, username: str = "", password: str = ""
) -> MQTTAdapter:
    """创建 MQTT 适配器"""
    adapter = MQTTAdapter()
    if host:
        adapter.authenticate(
            {
                "host": host,
                "port": str(port),
                "username": username,
                "password": password,
            }
        )
    return adapter
