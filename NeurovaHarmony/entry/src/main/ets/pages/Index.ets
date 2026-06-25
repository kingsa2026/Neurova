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

@Entry
@Component
struct Index {
  private router = Router.getInstance();
  private authStore = new AuthStore();
  private logger = Logger.getInstance();

  aboutToAppear() {
    // M5.2.3 冷启动优化：立即分发，无占位渲染
    if (this.authStore.isAuthenticated) {
      this.logger.info('Index', '冷启动：已登录，跳转仪表盘');
      this.router.replace(RouteNames.DASHBOARD);
    } else {
      this.logger.info('Index', '冷启动：未登录，跳转登录页');
      this.router.replace(RouteNames.LOGIN);
    }
  }

  build() {
    // 透明占位（路由 replace 后立即消失）
    Column()
      .width('100%')
      .height('100%')
      .backgroundColor('#FFFFFF')
  }
}
