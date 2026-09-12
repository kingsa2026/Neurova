/**
 * 渠道配置共享定义（2026-09-13 agent 隔离 Phase C）
 *
 * 从 ChannelIntegrationPage 抽出：字段表（公共 + 各平台独有）、卡片目录、
 * 插件渠道 schema 转换——供系统渠道管理页与 Agent 渠道页共用，
 * 两页字段语义单一来源（agent 维度下同一平台各 agent 各配各的）。
 */

export interface FieldSchema {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'toggle' | 'select'
  required?: boolean
  placeholder?: string
  defaultValue?: unknown
  options?: { value: string; label: string }[]
  inputType?: string
}

export interface ChannelCatalogItem {
  name: string
  icon: string
  iconSrc?: string
  type: string
  enabled: boolean
  color: string
  channelKey: string
  backendType: string
  connected: boolean
}

type T = (key: string) => string

/** 公共配置字段（所有渠道一致，存 extra） */
export function buildCommonFields(t: T): FieldSchema[] {
  return [
    { key: 'bot_prefix', label: 'Bot Prefix', type: 'text', placeholder: '@bot', defaultValue: '@bot' },
    { key: 'show_tool_messages', label: t('nav.showToolMessages'), type: 'toggle', defaultValue: false },
    { key: 'show_thinking', label: t('nav.showThinking'), type: 'toggle', defaultValue: false },
    { key: 'stream_mode', label: t('nav.streamMode'), type: 'toggle', defaultValue: true },
    { key: 'private_chat_strategy', label: t('nav.privateChatStrategy'), type: 'select', defaultValue: 'open', options: [
      { value: 'open', label: t('nav.open') }, { value: 'closed', label: t('nav.closed') }, { value: 'whitelist', label: t('nav.whitelist') },
    ] },
    { key: 'group_chat_strategy', label: t('nav.groupChatStrategy'), type: 'select', defaultValue: 'open', options: [
      { value: 'open', label: t('nav.open') }, { value: 'closed', label: t('nav.closed') }, { value: 'whitelist', label: t('nav.whitelist') },
    ] },
    { key: 'require_mention', label: t('nav.requireMention'), type: 'toggle', defaultValue: false },
  ]
}

/** 公共字段 keys（save 时同样进 extra——修复原"公共字段被静默丢弃"缺陷） */
export const COMMON_FIELD_KEYS = [
  'bot_prefix', 'show_tool_messages', 'show_thinking', 'stream_mode',
  'private_chat_strategy', 'group_chat_strategy', 'require_mention',
]

/** 各平台独有字段表（key=channelKey；imessage 后端适配器未实现故无表） */
export function buildChannelFieldsMap(t: T): Record<string, FieldSchema[]> {
  return {
    xiaoyi: [
      { key: 'access_key', label: 'Access Key', type: 'text', required: true },
      { key: 'secret_key', label: 'Secret Key', type: 'password', required: true },
      { key: 'agent_id', label: 'Agent ID', type: 'text', required: true },
      { key: 'ws_url', label: 'WebSocket URL', type: 'text', placeholder: 'wss://hag.cloud.huawei.com/openclaw/v1/ws/link' },
    ],
    dingtalk: [
      { key: 'app_id', label: 'Client ID', type: 'text', required: true, placeholder: t('nav.dingtalkAppKey') },
      { key: 'app_secret', label: 'Client Secret', type: 'password', required: true, placeholder: t('nav.dingtalkAppSecret') },
      { key: 'use_stream', label: t('nav.streamMode'), type: 'toggle', defaultValue: true },
      { key: 'reply_at_sender', label: t('nav.replyAtSender'), type: 'toggle', defaultValue: false },
      { key: 'share_session_in_group', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: true },
    ],
    feishu: [
      { key: 'app_id', label: 'App ID', type: 'text', required: true },
      { key: 'app_secret', label: 'App Secret', type: 'password', required: true },
      { key: 'encrypt_key', label: 'Encrypt Key', type: 'password' },
      { key: 'verification_token', label: 'Verification Token', type: 'password' },
      { key: 'region', label: t('nav.region'), type: 'select', defaultValue: 'feishu', options: [
        { value: 'feishu', label: t('nav.feishuChina') }, { value: 'lark', label: t('nav.larkInternational') },
      ] },
      { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
      { key: 'share_session_in_group', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: true },
    ],
    discord: [
      { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
      { key: 'http_proxy', label: 'HTTP Proxy', type: 'text', placeholder: 'http://127.0.0.1:7890' },
      { key: 'http_proxy_auth', label: 'HTTP Proxy Auth', type: 'text', placeholder: 'user:pass' },
      { key: 'receive_bot_messages', label: t('nav.receiveBotMessages'), type: 'toggle', defaultValue: false },
    ],
    telegram: [
      { key: 'bot_token', label: 'Bot Token', type: 'password', required: true, placeholder: '123456:ABC-DEF...' },
      { key: 'http_proxy', label: 'HTTP Proxy', type: 'text', placeholder: 'http://127.0.0.1:7890' },
      { key: 'http_proxy_auth', label: 'HTTP Proxy Auth', type: 'text' },
      { key: 'show_typing', label: 'Show Typing', type: 'toggle', defaultValue: true },
      { key: 'share_session_in_group', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: true },
    ],
    qq: [
      { key: 'app_id', label: 'App ID', type: 'text', required: true },
      { key: 'client_secret', label: 'Client Secret', type: 'password', required: true },
      { key: 'instant_confirm', label: t('nav.instantConfirm'), type: 'toggle', defaultValue: false },
    ],
    wechat: [
      { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
      { key: 'token_file', label: t('nav.tokenFile'), type: 'text', placeholder: './token.json' },
      { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
      { key: 'message_merge', label: t('nav.messageMerge'), type: 'toggle', defaultValue: false },
    ],
    wecom: [
      { key: 'app_id', label: 'Bot ID (CorpID)', type: 'text', required: true },
      { key: 'app_secret', label: 'Secret', type: 'password', required: true },
      { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
      { key: 'welcome_message', label: t('nav.welcomeMessage'), type: 'text', placeholder: 'Hello! I am Neurova' },
      { key: 'share_session_in_group', label: t('nav.groupShareSession'), type: 'toggle', defaultValue: true },
    ],
    yuanbao: [
      { key: 'app_id', label: 'App ID', type: 'text', required: true },
      { key: 'app_secret', label: 'App Secret', type: 'password', required: true },
      { key: 'api_domain', label: 'API Domain', type: 'text', placeholder: 'https://api.yuanbao.com' },
      { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
    ],
    matrix: [
      { key: 'homeserver_url', label: 'Homeserver URL', type: 'text', required: true, placeholder: 'https://matrix.org' },
      { key: 'user_id', label: 'User ID', type: 'text', required: true, placeholder: '@bot:matrix.org' },
      { key: 'access_token', label: 'Access Token', type: 'password', required: true },
      { key: 'device_name', label: 'Device Name', type: 'text', placeholder: 'Neurova' },
      { key: 'disable_dm', label: t('nav.disableDm'), type: 'toggle', defaultValue: false },
      { key: 'disable_group', label: t('nav.disableGroup'), type: 'toggle', defaultValue: false },
    ],
    sip: [
      { key: 'sip_mode', label: 'SIP Mode', type: 'select', defaultValue: 'dev', options: [
        { value: 'dev', label: 'Development (pyVoIP)' }, { value: 'production', label: 'Production (LiveKit)' },
      ] },
      { key: 'sip_server', label: 'SIP Server', type: 'text' },
      { key: 'sip_username', label: 'SIP Username', type: 'text', required: true },
      { key: 'sip_password', label: 'SIP Password', type: 'password', required: true },
      { key: 'sip_port', label: 'SIP Port', type: 'number', defaultValue: 5061 },
      { key: 'transport_protocol', label: 'Transport Protocol', type: 'select', defaultValue: 'UDP', options: [
        { value: 'UDP', label: 'UDP' }, { value: 'TCP', label: 'TCP' }, { value: 'TLS', label: 'TLS' },
      ] },
      { key: 'dashscope_api_key', label: 'DashScope API Key', type: 'password' },
      { key: 'tts_provider', label: 'TTS Provider', type: 'text' },
      { key: 'tts_language', label: 'TTS Language', type: 'text', placeholder: 'zh-CN' },
      { key: 'stt_provider', label: 'STT Provider', type: 'text' },
    ],
    mattermost: [
      { key: 'mattermost_url', label: 'Mattermost URL', type: 'text', required: true, placeholder: 'https://mattermost.example.com' },
      { key: 'bot_token', label: 'Bot Token', type: 'password', required: true },
      { key: 'media_directory', label: t('ui.mediaFileDir'), type: 'text', placeholder: './media' },
      { key: 'show_typing', label: 'Show Typing', type: 'toggle', defaultValue: true },
      { key: 'thread_follow_without_mention', label: 'Thread Follow Without Mention', type: 'toggle', defaultValue: false },
    ],
    mqtt: [
      { key: 'host', label: 'MQTT Host', type: 'text', defaultValue: '127.0.0.1' },
      { key: 'port', label: 'Port', type: 'number', defaultValue: 1883 },
      { key: 'username', label: 'Username', type: 'text' },
      { key: 'password', label: 'Password', type: 'password' },
      { key: 'subscribe_topic', label: 'Subscribe Topic', type: 'text', placeholder: 'server/+/up' },
    ],
    twilio: [
      { key: 'app_id', label: 'Account SID', type: 'text', required: true },
      { key: 'app_secret', label: 'Auth Token', type: 'password', required: true },
      { key: 'from_number', label: 'Phone Number', type: 'text', required: true, placeholder: '+1234567890' },
    ],
    onebot: [
      { key: 'access_token', label: 'Access Token', type: 'password', required: true },
      { key: 'http_api_url', label: 'HTTP API URL', type: 'text', defaultValue: 'http://127.0.0.1:3000' },
      { key: 'ws_api_url', label: 'WS API URL', type: 'text', defaultValue: 'ws://127.0.0.1:3001' },
      { key: 'media_directory', label: t('nav.mediaDirectory'), type: 'text', placeholder: './media' },
    ],
  }
}

/** 渠道卡片目录（两页共用；enabled/connected 由加载后按 agent 视图回填） */
export function buildChannelCatalog(t: T): ChannelCatalogItem[] {
  return [
    { name: 'Console', icon: '🖥', type: 'builtin', enabled: true, color: '#6366f1', channelKey: 'console', backendType: 'api', connected: false },
    { name: t('ui.chXiaoyi'), icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png', type: 'builtin', enabled: false, color: '#ec4899', channelKey: 'xiaoyi', backendType: 'xiaoyi', connected: false },
    { name: t('ui.chDingtalk'), icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i1/O1CN01w5mzV01tFtE37wkJI_!!6000000005873-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#2563eb', channelKey: 'dingtalk', backendType: 'dingtalk', connected: false },
    { name: t('ui.chFeishu'), icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01wCpTM41LOPeyP7wKc_!!6000000001289-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#7c3aed', channelKey: 'feishu', backendType: 'feishu', connected: false },
    { name: 'Discord', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01OsQiMO1ZYrJXp3TmX_!!6000000003207-2-tps-42-48.png', type: 'builtin', enabled: false, color: '#5865f2', channelKey: 'discord', backendType: 'discord', connected: false },
    { name: 'Telegram', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN013VVoKf1jsgcNn40KA_!!6000000004604-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#0088cc', channelKey: 'telegram', backendType: 'telegram', connected: false },
    { name: 'QQ', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01ApVkC91JeKBkQfgj9_!!6000000001053-2-tps-41-48.png', type: 'builtin', enabled: false, color: '#e62117', channelKey: 'qq', backendType: 'qq', connected: false },
    { name: t('ui.chWechat'), icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01ikAjLG1jhh721iEUc_!!6000000004580-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#07c160', channelKey: 'wechat', backendType: 'wechat', connected: false },
    { name: t('ui.chWecom'), icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01oWpOyx1TPnmnrzxlq_!!6000000002375-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#3370ff', channelKey: 'wecom', backendType: 'wecom', connected: false },
    { name: t('ui.chYuanbao'), icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN0164yBmJ1a2AftSglge_!!6000000003271-2-tps-225-225.png', type: 'builtin', enabled: false, color: '#f59e0b', channelKey: 'yuanbao', backendType: 'yuanbao', connected: false },
    { name: 'Matrix', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i3/O1CN01YfEzZu1DWdqgAdqtu_!!6000000000224-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#0dbd8b', channelKey: 'matrix', backendType: 'matrix', connected: false },
    { name: 'SIP', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#64748b', channelKey: 'sip', backendType: 'sip', connected: false },
    { name: 'Mattermost', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#0058cc', channelKey: 'mattermost', backendType: 'mattermost', connected: false },
    { name: 'MQTT', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN014ALZcD1iBnv2GeYdE_!!6000000004375-2-tps-64-64.png', type: 'builtin', enabled: false, color: '#667f80', channelKey: 'mqtt', backendType: 'mqtt', connected: false },
    { name: 'Twilio', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i2/O1CN01nwY8ZK1eY0etBKDWb_!!6000000003882-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#f22f46', channelKey: 'twilio', backendType: 'voice', connected: false },
    { name: 'OneBot', icon: '', iconSrc: 'https://gw.alicdn.com/imgextra/i3/O1CN01xqM0EN1oKrRiAFX3K_!!6000000005207-2-tps-400-400.png', type: 'builtin', enabled: false, color: '#10b981', channelKey: 'onebot', backendType: 'qqbot', connected: false },
    { name: 'iMessage', icon: '', iconSrc: 'https://img.alicdn.com/imgextra/i4/O1CN01QtLiI31uAgL02USNH_!!6000000005997-2-tps-48-48.png', type: 'builtin', enabled: false, color: '#34aadc', channelKey: 'imessage', backendType: 'imessage', connected: false },
  ]
}

/** 插件渠道动态 schema → 页面字段形态（secret→password、bool→toggle、int→number） */
export function pluginSchemaToFields(
  fields: { key: string; label?: string; type: string; required?: boolean; default?: unknown; placeholder?: string }[],
): FieldSchema[] {
  return fields.map((f) => ({
    key: f.key,
    label: f.label || f.key,
    type: f.type === 'secret' ? 'password' : f.type === 'bool' ? 'toggle' : f.type === 'int' ? 'number' : (f.type as FieldSchema['type']),
    required: f.required,
    defaultValue: f.default,
    placeholder: f.placeholder,
  }))
}
