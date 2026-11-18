/**
 * ShellPage - 应用导航壳（已登录后的常驻根，对照原型 02 IA / 04 断点自适应）
 *
 * 结构：五 Tab（对话/工作台/智能体/知识/我的）。
 * 断点：@ohos.mediaquery 判定 ≥600vp 切左侧导航栏（RailBar）；
 *       <600vp 用 Tabs 底部页签（barPosition End + barOverlap + barFloatingStyle）——
 *       页签栏挂 API 26 沉浸光感系统材质（uiMaterial.ImmersiveMaterial，官方"液态玻璃"：
 *       材质滤镜/折射/高光/阴影多层叠加，跟随深浅色与壁纸，随设备算力自动降级）。
 *       注意：systemMaterial 仅在底部 TabBar（barPosition End）/ Navigation 标题栏 /
 *       弹窗族 / Slider·Toggle·Select 生效，自绘悬浮容器会报 Material inactive: out of
 *       scope，故页签栏必须走系统 Tabs 承载；材质自带模糊，不再叠 blur/effect（官方功耗约束）。
 * 栈页（聊天详情/智能体详情等）经 Router.push 叠在 Navigation 之上，壳随之下沉——
 * 与原型一致：Tab 栏只出现在五个根页。
 */

import { mediaquery, uiMaterial } from '@kit.ArkUI';
import { StarBackground } from '../components/glass';
import { StyleManager } from '../libs/style/StyleManager';
import { TabIcon } from '../components/shell/TabIcon';
import { RailBar } from '../components/shell/RailBar';
import { SessionListPage } from './SessionListPage';
import { DashboardPage } from './DashboardPage';
import { AgentListPage } from './AgentListPage';
import { KnowledgePage } from './KnowledgePage';
import { SettingPage } from './SettingPage';

@Component
export struct ShellPage {
  // 当前 Tab（AppStorage 双向同步：工作台「最近会话·全部」可切到对话 Tab）
  @StorageLink('shellTab') @Watch('onShellTabChange') activeTab: number = 0;
  @State private isWide: boolean = false;
  /** Tabs 实时页签（watch/onChange 互驱时的对照值，防循环触发） */
  private currentTabIndex: number = 0;
  private tabsController: TabsController = new TabsController();
  /** 系统液态玻璃材质：一次性构造全局复用（运行时频繁改参数会触发材质重算） */
  private tabMaterial: uiMaterial.ImmersiveMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.ULTRA_THIN,
    interactive: true
  });
  private sm: StyleManager = StyleManager.getInstance();
  private mqListener: mediaquery.MediaQueryListener | undefined = undefined;
  private mqCb: ((res: mediaquery.MediaQueryResult) => void) | undefined = undefined;

  aboutToAppear(): void {
    this.currentTabIndex = this.activeTab;
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

  /** 外部驱动切 Tab（工作台「最近会话·全部」→ 对话） */
  onShellTabChange(propName: string): void {
    if (this.activeTab !== this.currentTabIndex) {
      this.currentTabIndex = this.activeTab;
      this.tabsController.changeIndex(this.activeTab);
    }
  }

  /** Tab 页内容（宽屏分支：按 activeTab 切换，单挂载） */
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

  /** Tab 页内容（窄屏 Tabs 分支：idx 为各 TabContent 的静态常量，勿改读 activeTab） */
  @Builder
  tabPage(idx: number) {
    Column() {
      if (idx === 0) {
        SessionListPage()
      } else if (idx === 1) {
        DashboardPage()
      } else if (idx === 2) {
        AgentListPage()
      } else if (idx === 3) {
        KnowledgePage()
      } else {
        SettingPage()
      }
    }
    .width('100%')
    .height('100%')
    // 悬浮页签栏压在内容之上（barOverlap），底部留出净空
    .padding({ bottom: 88 })
  }

  /** 页签项：激活态紫晕光斑 + 图标 + 标签（玻璃底由系统页签栏材质提供，此处不涂背景） */
  @Builder
  renderTabItem(idx: number, kind: string, label: string) {
    Column() {
      Stack() {
        if (this.activeTab === idx) {
          Column()
            .width(38)
            .height(34)
            .borderRadius(16)
            .backgroundColor(this.sm.getColor('primary_soft'))
        }
        TabIcon({ kind: kind, color: this.activeTab === idx ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary') })
      }
      .height(38)

      Text(label)
        .fontSize(10)
        .fontColor(this.activeTab === idx ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary'))
    }
    .justifyContent(FlexAlign.Center)
  }

  /** 各 Tab 页签（CustomBuilder 按引用传入；带参 builder 包箭头函数不会执行，勿改回） */
  @Builder
  tabItemChat() {
    this.renderTabItem(0, 'chat', '对话')
  }

  @Builder
  tabItemHome() {
    this.renderTabItem(1, 'home', '工作台')
  }

  @Builder
  tabItemAgent() {
    this.renderTabItem(2, 'agent', '智能体')
  }

  @Builder
  tabItemBook() {
    this.renderTabItem(3, 'book', '知识')
  }

  @Builder
  tabItemUser() {
    this.renderTabItem(4, 'user', '我的')
  }

  build() {
    Stack() {
      // 星空底层：五个 Tab 共用（页面自身不再涂不透明背景，星穹透出）
      StarBackground({ starCount: 60, twinkle: true })

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
        // <600vp：底部液态玻璃页签栏（系统沉浸光感材质，跟随深浅色与壁纸）
        Tabs({ barPosition: BarPosition.End, index: this.activeTab, controller: this.tabsController }) {
          TabContent() {
            this.tabPage(0)
          }
          .tabBar(this.tabItemChat)

          TabContent() {
            this.tabPage(1)
          }
          .tabBar(this.tabItemHome)

          TabContent() {
            this.tabPage(2)
          }
          .tabBar(this.tabItemAgent)

          TabContent() {
            this.tabPage(3)
          }
          .tabBar(this.tabItemBook)

          TabContent() {
            this.tabPage(4)
          }
          .tabBar(this.tabItemUser)
        }
        .barOverlap(true)
        .barFloatingStyle({ systemMaterial: this.tabMaterial, maskColor: Color.Transparent })
        .onChange((idx: number) => {
          this.currentTabIndex = idx;
          if (this.activeTab !== idx) {
            this.activeTab = idx;
          }
        })
        .width('100%')
        .height('100%')
      }
    }
    .width('100%')
    .height('100%')
  }
}
