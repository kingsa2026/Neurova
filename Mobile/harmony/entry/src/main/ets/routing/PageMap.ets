/**
 * PageMap - 路由名 → 页面组件的**唯一**挂载点
 *
 * 此前 MainLayout 的 Navigation 未接 navDestination，Router.push 的页面名
 * 没有任何组件映射（内容区永远显示占位"加载中..."）——这是鸿蒙端路由的实际断点。
 * 本文件补上映射；未注册的页面名走 fallback 占位页。
 */

import { RouteNames } from './Router';
import { ShellPage } from '../pages/ShellPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { DashboardPage } from '../pages/DashboardPage';
import { ChatPage } from '../pages/ChatPage';
import { PairingPage } from '../pages/PairingPage';
import { ConnectionPage } from '../pages/ConnectionPage';
import { AgentListPage } from '../pages/AgentListPage';
import { AgentDetailPage } from '../pages/AgentDetailPage';
import { KnowledgePage } from '../pages/KnowledgePage';
import { MemoryPage } from '../pages/MemoryPage';
import { ModelPage } from '../pages/ModelPage';
import { HealthPage } from '../pages/HealthPage';
import { SettingPage } from '../pages/SettingPage';
import { TaskPage } from '../pages/TaskPage';
import { FilePage } from '../pages/FilePage';
import { NotificationPage } from '../pages/NotificationPage';
import { AgentChannelPage } from '../pages/AgentChannelPage';

@Builder
export function pageMap(name: string) {
  if (name === RouteNames.SHELL) {
    NavDestination() { ShellPage() }.hideTitleBar(true)
  } else if (name === RouteNames.LOGIN) {
    NavDestination() { LoginPage() }.hideTitleBar(true)
  } else if (name === RouteNames.REGISTER) {
    NavDestination() { RegisterPage() }.hideTitleBar(true)
  } else if (name === RouteNames.DASHBOARD) {
    NavDestination() { DashboardPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CHAT) {
    NavDestination() { ChatPage() }.hideTitleBar(true)
  } else if (name === RouteNames.PAIRING) {
    NavDestination() { PairingPage() }.hideTitleBar(true)
  } else if (name === RouteNames.CONNECTION) {
    NavDestination() { ConnectionPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_LIST) {
    NavDestination() { AgentListPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_DETAIL) {
    NavDestination() { AgentDetailPage() }.hideTitleBar(true)
  } else if (name === RouteNames.KNOWLEDGE) {
    NavDestination() { KnowledgePage() }.hideTitleBar(true)
  } else if (name === RouteNames.MEMORY) {
    NavDestination() { MemoryPage() }.hideTitleBar(true)
  } else if (name === RouteNames.MODEL) {
    NavDestination() { ModelPage() }.hideTitleBar(true)
  } else if (name === RouteNames.HEALTH) {
    NavDestination() { HealthPage() }.hideTitleBar(true)
  } else if (name === RouteNames.SETTINGS) {
    NavDestination() { SettingPage() }.hideTitleBar(true)
  } else if (name === RouteNames.TASK) {
    NavDestination() { TaskPage() }.hideTitleBar(true)
  } else if (name === RouteNames.FILE) {
    NavDestination() { FilePage() }.hideTitleBar(true)
  } else if (name === RouteNames.NOTIFICATION) {
    NavDestination() { NotificationPage() }.hideTitleBar(true)
  } else if (name === RouteNames.AGENT_CHANNEL) {
    NavDestination() { AgentChannelPage() }.hideTitleBar(true)
  } else {
    NavDestination() {
      Column() {
        Text('页面未注册').fontSize(16)
        Text(name).fontSize(12).opacity(0.6).margin({ top: 6 })
      }.width('100%').height('100%').justifyContent(FlexAlign.Center)
    }.hideTitleBar(false)
  }
}
