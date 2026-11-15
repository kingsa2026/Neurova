/**
 * ShellPage - 应用导航壳（已登录后的常驻根，对照原型 02 IA / 04 断点自适应）
 *
 * 结构：五 Tab（对话/工作台/智能体/知识/我的），Tab 内容为既有页面组件内嵌。
 * 断点：@ohos.mediaquery 判定 ≥600vp 切左侧导航栏（RailBar），
 *       <600vp 悬浮液态玻璃胶囊（LiquidTabBar）。
 * 栈页（聊天详情/智能体详情等）经 Router.push 叠在 Navigation 之上，壳随之下沉——
 * 与原型一致：Tab 栏只出现在五个根页。
 *
 * 已知断点：对话 Tab 当前内嵌 ChatPage（流式直聊），会话列表（F4，同源 PC
 * /console/chat/sessions）在 M3 落地后替换。
 */

import { mediaquery } from '@kit.ArkUI';
import { StyleManager } from '../libs/style/StyleManager';
import { LiquidTabBar } from '../components/shell/LiquidTabBar';
import { RailBar } from '../components/shell/RailBar';
import { SessionListPage } from './SessionListPage';
import { ChatPage } from './ChatPage';
import { DashboardPage } from './DashboardPage';
import { AgentListPage } from './AgentListPage';
import { KnowledgePage } from './KnowledgePage';
import { SettingPage } from './SettingPage';

@Component
export struct ShellPage {
  @State private activeTab: number = 0;
  @State private isWide: boolean = false;
  private sm: StyleManager = StyleManager.getInstance();
  private mqListener: mediaquery.MediaQueryListener | undefined = undefined;
  private mqCb: ((res: mediaquery.MediaQueryResult) => void) | undefined = undefined;

  aboutToAppear(): void {
    this.mqListener = mediaquery.matchMediaSync('(min-width: 600vp)');
    this.isWide = this.mqListener.matches;
    const cb = (res: mediaquery.MediaQueryResult) => {
      this.isWide = res.matches;
    };
    this.mqCb = cb;
    this.mqListener.on('change', cb);
  }

  aboutToDisappear(): void {
    if (this.mqListener && this.mqCb) {
      this.mqListener.off('change', this.mqCb);
    }
  }

  @Builder
  tabContent() {
    if (this.activeTab === 0) {
      SessionListPage()
    } else if (this.activeTab === 1) {
      DashboardPage()
    } else if (this.activeTab === 2) {
      AgentListPage()
    } else if (this.activeTab === 3) {
      KnowledgePage()
    } else {
      SettingPage()
    }
  }

  build() {
    Stack() {
      if (this.isWide) {
        // ≥600vp：左侧导航栏 + 内容区
        Row() {
          RailBar({ active: this.activeTab, onPick: (idx: number) => { this.activeTab = idx; } })
          Column() {
            this.tabContent()
          }
          .layoutWeight(1)
        }
        .width('100%')
        .height('100%')
      } else {
        // <600vp：内容 + 悬浮液态玻璃胶囊（Stack 底部对齐）
        Stack({ alignContent: Alignment.Bottom }) {
          Column() {
            this.tabContent()
          }
          .width('100%')
          .height('100%')
          .padding({ bottom: 88 })

          Column() {
            LiquidTabBar({ active: this.activeTab, onPick: (idx: number) => { this.activeTab = idx; } })
          }
          .width('100%')
          .padding({ left: 14, right: 14, bottom: 14 })
        }
        .width('100%')
        .height('100%')
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
