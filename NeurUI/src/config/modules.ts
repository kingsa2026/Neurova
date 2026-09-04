/**
 * 功能模块目录 — 用户组菜单权限的唯一事实源
 *
 * 模块 key 直接复用前端菜单的路由 path（动态段用 :id 占位），
 * 管理员在用户组页面按此目录勾选；登录用户的 allowed_modules
 * （后端 /auth/me 返回，所属组并集）与之匹配后过滤侧栏/顶部菜单。
 *
 * 语义约定（与后端 neurova/auth/user_group_model.py 对齐）:
 *  - allowed_modules 为空 = 不限制（全模块可见），向后兼容存量用户组
 *  - /dashboard 是兜底主页，恒可见，不入目录
 */

export interface ModuleItem {
  /** 路由 path（动态段 :id 占位），同时作为 allowed_modules 里的 key */
  key: string
  /** i18n key，位于 nav.* 命名空间 */
  labelKey: string
}

export interface ModuleSection {
  /** 分区标识：侧栏 Agent 区 / 侧栏用户区 / 顶部系统配置区 */
  zone: 'agentZone' | 'userZone' | 'topNav'
  /** 分区标题 i18n key（nav.*） */
  zoneLabelKey: string
  items: ModuleItem[]
}

/** 顶部系统配置区（与 config/navigation.ts 的 TOP_NAV_CATEGORIES 一致） */
const TOP_MODULES: ModuleItem[] = [
  { key: '/models', labelKey: 'models' },
  { key: '/tool-layers', labelKey: 'toolLayers' },
  { key: '/sandbox', labelKey: 'sandbox' },
  { key: '/monitor', labelKey: 'monitor' },
  { key: '/health', labelKey: 'health' },
  { key: '/logs', labelKey: 'logs' },
  { key: '/stats', labelKey: 'stats' },
  { key: '/settings', labelKey: 'settings' },
  { key: '/settings/voice-transcription', labelKey: 'voiceTranscription' },
  { key: '/memory/settings', labelKey: 'memorySettings' },
  { key: '/enhanced-users', labelKey: 'enhancedusers' },
  { key: '/groups', labelKey: 'groups' },
  { key: '/firewall', labelKey: 'firewall' },
  { key: '/audit', labelKey: 'audit' },
  { key: '/marketplace', labelKey: 'marketplace' },
  { key: '/benchmark', labelKey: 'benchmark' },
]

/** 侧栏 Agent 区（动态段 :id 占位，匹配时按前缀命中） */
const AGENT_MODULES: ModuleItem[] = [
  { key: '/chat', labelKey: 'chat' },
  { key: '/agent/:id/memory', labelKey: 'memory' },
  { key: '/agent/:id/files', labelKey: 'agentfiles' },
  { key: '/agent/:id/experience-knowledge', labelKey: 'experience' },
  { key: '/agent/:id/knowledge-graph', labelKey: 'knowledgeGraph' },
  { key: '/agent/:id/metacognition', labelKey: 'metacognition' },
  { key: '/agent/:id/reflection', labelKey: 'reflection' },
  { key: '/agent/:id/growth', labelKey: 'growth' },
  { key: '/agent/:id/emotion', labelKey: 'emotion' },
  { key: '/agent/:id/personality', labelKey: 'personality' },
  { key: '/agent/:id/skills', labelKey: 'skills' },
  { key: '/agent/:id/rules', labelKey: 'rules' },
  { key: '/agent/:id/media', labelKey: 'media' },
  { key: '/agent/:id/scheduler', labelKey: 'scheduler' },
  { key: '/agent/:id/channel', labelKey: 'channels' },
  { key: '/agent/:id/sleep', labelKey: 'sleep' },
  { key: '/agent/:id/computer', labelKey: 'computer' },
  { key: '/agent/:id/trace', labelKey: 'debug' },
]

/** 侧栏用户区（协作组内为该组的一级模块，覆盖其子路由） */
const USER_MODULES: ModuleItem[] = [
  { key: '/agents', labelKey: 'agents' },
  { key: '/knowledge', labelKey: 'knowledge' },
  { key: '/skill-pool', labelKey: 'skillPool' },
  { key: '/marketplace/skills', labelKey: 'skillMarket' },
  { key: '/aigc', labelKey: 'aigc' },
  { key: '/files', labelKey: 'files' },
  { key: '/neuron', labelKey: 'neuron' },
  { key: '/collaboration', labelKey: 'collaboration' },
  { key: '/channels', labelKey: 'channels' },
  { key: '/notifications', labelKey: 'notifications' },
  { key: '/usage-stats', labelKey: 'usageStats' },
  { key: '/analytics', labelKey: 'analytics' },
  { key: '/memory/search-settings', labelKey: 'searchSettings' },
]

export const MODULE_SECTIONS: ModuleSection[] = [
  { zone: 'agentZone', zoneLabelKey: 'agentZone', items: AGENT_MODULES },
  { zone: 'userZone', zoneLabelKey: 'userZone', items: USER_MODULES },
  { zone: 'topNav', zoneLabelKey: 'topNav', items: TOP_MODULES },
]

/** 三个分区标题的 i18n key 后缀（nav.* 命名空间；nav.topNav 为本功能新增） */
export const MODULE_ZONE_LABEL_KEYS = ['topNav', 'agentZone', 'userZone']

/** 全部可勾选模块 key（扁平） */
export function allModuleKeys(): string[] {
  return MODULE_SECTIONS.flatMap(s => s.items.map(i => i.key))
}

export const ALL_MODULE_KEYS: string[] = allModuleKeys()
