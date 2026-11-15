/**
 * Index - 应用入口路由分发器
 *
 * 职责：应用启动后立即根据登录状态分发到登录页或仪表盘，避免占位文本闪烁
 * 设计：@Entry + aboutToAppear 同步路由 replace，渲染期无可见内容
 *
 * 依赖：
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/state/stores/AuthStore：认证状态读取
 *   - ../libs/logger/Logger：启动日志
 *
 * TDD：本页为薄分发器，逻辑由 AuthStore + Router 单元测试覆盖，不单独写测试
 */

import { Router, RouteNames } from '../routing/Router';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { Logger } from '../libs/logger/Logger';
import { ServerProfiles } from '../libs/config/ServerProfiles';
import { ConfigManager } from '../libs/config/ConfigManager';
import { pageMap } from '../routing/PageMap';
import { ToastHost } from '../components/system/ToastHost';

@Entry
@Component
struct Index {
  private router = Router.getInstance();
  private authStore = new AuthStore();
  private logger = Logger.getInstance();

  async aboutToAppear() {
    // 冷启动先恢复服务器档案并把地址落到 HTTP 装配点（设计方案 §4.5，S0 接线）
    await ServerProfiles.getInstance().load(getContext(this) as Context);
    const apiBase = ServerProfiles.getInstance().getActiveApiBase();
    if (!apiBase) {
      // 无可用服务器档案：先去连接页录入，否则登录无从发起（登录按钮空转的根因）
      this.logger.info('Index', '冷启动：无服务器档案，跳转连接页');
      this.router.replace(RouteNames.CONNECTION);
      return;
    }
    ConfigManager.getInstance().applyServerProfile(apiBase, getContext(this) as Context);
    // 档案就绪后再分发，避免异步竞争导致带空地址登录
    if (this.authStore.isAuthenticated) {
      this.logger.info('Index', '冷启动：已登录，进入导航壳');
      this.router.replace(RouteNames.SHELL);
    } else {
      this.logger.info('Index', '冷启动：未登录，跳转登录页');
      this.router.replace(RouteNames.LOGIN);
    }
  }

  @Builder
  destBuilder(name: string) {
    pageMap(name)
  }

  build() {
    // 根容器：Navigation + 顶层 ToastHost（修复 toast 全盲——MessageManager 分发此前无 UI 订阅）
    Stack() {
    Navigation(this.router.getNavStack()) {
      Column() {
        Text('Neurova')
          .fontSize(18)
          .opacity(0.6)
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
    }
    .navDestination(this.destBuilder)
    .hideTitleBar(true)
    .mode(NavigationMode.Stack)
    .width('100%')
    .height('100%')
    ToastHost()
    }
    .width('100%')
    .height('100%')
  }
}
