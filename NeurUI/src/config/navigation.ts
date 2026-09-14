/**
 * 顶部导航（系统配置区）唯一数据源
 *
 * 三区导航架构:
 *   - 左侧上半区 = Agent 隔离功能（MainLayout.vue）
 *   - 左侧下半区 = 用户隔离功能（MainLayout.vue）
 *   - 顶部导航   = 系统配置类功能（本文件，全局恒定，不随 agent 切换）
 *
 * 约束（由 NavigationZones.test.ts 守卫）:
 *   - 组内路由引用零重复（历史教训: /models 曾双入口）
 *   - 用户级功能页（知识库/协作/技能池）不得回流本区。
 *     例外（2026-09-14 用户决策）：AIGC 属「模型与工具」域，以 /aigc/* 五个
 *     二级页挂本区（旧单页 Tab 形态 /aigc 已废除）。
 */
import type { Component } from 'vue'
import {
  CloudServerOutlined, ToolOutlined, CodeOutlined,
  MonitorOutlined, HeartOutlined, FileTextOutlined, BarChartOutlined,
  SettingOutlined, AudioOutlined, UserOutlined, TeamOutlined,
  AlertOutlined, HistoryOutlined, ControlOutlined,
  ShopOutlined, DashboardOutlined,
  PictureOutlined, VideoCameraOutlined, PlaySquareOutlined,
} from '@ant-design/icons-vue'

export interface TopNavItem {
  to: string
  labelKey: string
  icon: Component
}

export interface TopNavCategory {
  key: string
  labelKey: string
  icon: Component
  items: TopNavItem[]
}

export const TOP_NAV_CATEGORIES: TopNavCategory[] = [
  {
    key: 'modelTools',
    labelKey: 'nav.modelTools',
    icon: CloudServerOutlined,
    items: [
      { to: '/models', labelKey: 'nav.models', icon: CloudServerOutlined },
      { to: '/tool-layers', labelKey: 'nav.toolLayers', icon: ToolOutlined },
      { to: '/sandbox', labelKey: 'nav.sandbox', icon: CodeOutlined },
      { to: '/aigc/text', labelKey: 'nav.aigcText', icon: FileTextOutlined },
      { to: '/aigc/image', labelKey: 'nav.aigcImage', icon: PictureOutlined },
      { to: '/aigc/audio', labelKey: 'nav.aigcAudio', icon: AudioOutlined },
      { to: '/aigc/video', labelKey: 'nav.aigcVideo', icon: VideoCameraOutlined },
      { to: '/aigc/studio', labelKey: 'nav.aigcStudio', icon: PlaySquareOutlined },
    ],
  },
  {
    key: 'opsMonitor',
    labelKey: 'nav.opsMonitor',
    icon: MonitorOutlined,
    items: [
      { to: '/monitor', labelKey: 'nav.monitor', icon: MonitorOutlined },
      { to: '/health', labelKey: 'nav.health', icon: HeartOutlined },
      { to: '/logs', labelKey: 'nav.logs', icon: FileTextOutlined },
      { to: '/stats', labelKey: 'nav.stats', icon: BarChartOutlined },
    ],
  },
  {
    key: 'platformAdmin',
    labelKey: 'nav.platformAdmin',
    icon: SettingOutlined,
    items: [
      { to: '/settings', labelKey: 'nav.settings', icon: SettingOutlined },
      { to: '/settings/voice-transcription', labelKey: 'nav.voiceTranscription', icon: AudioOutlined },
      { to: '/memory/settings', labelKey: 'nav.memorySettings', icon: ControlOutlined },
      { to: '/enhanced-users', labelKey: 'nav.enhancedusers', icon: UserOutlined },
      { to: '/groups', labelKey: 'nav.groups', icon: TeamOutlined },
      { to: '/firewall', labelKey: 'nav.firewall', icon: AlertOutlined },
      { to: '/audit', labelKey: 'nav.audit', icon: HistoryOutlined },
    ],
  },
  {
    key: 'platformService',
    labelKey: 'nav.platformService',
    icon: DashboardOutlined,
    items: [
      { to: '/marketplace', labelKey: 'nav.marketplace', icon: ShopOutlined },
      { to: '/benchmark', labelKey: 'nav.benchmark', icon: DashboardOutlined },
    ],
  },
]
