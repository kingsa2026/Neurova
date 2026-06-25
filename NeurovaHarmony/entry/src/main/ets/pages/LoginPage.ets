/**
 * LoginPage - 登录页
 *
 * 职责：用户登录入口，提供用户名/密码登录、记住我、注册入口
 * 设计：Stack 叠加 [星空背景层] + [居中玻璃面板表单层]；
 *       通过 ApiFacade 调用后端登录接口，AuthStore 写入 token/user，Router 跳转 Dashboard；
 *       失败时由 MessageManager 统一提示，异常由 Logger 记录
 *
 * 依赖：
 *   - ../components/glass：GlassPanel、GlassInput、GlassButton、StarBackground
 *   - ../libs/api/ApiFacade：统一 API 门面
 *   - ../libs/state/stores/AuthStore：认证状态管理
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router 跳转或作为 @Entry 入口；登录成功后 resetTo(DashboardPage)
 */

import { GlassPanel, GlassInput, GlassButton, StarBackground } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

@Entry
@Component
export struct LoginPage {
  // 用户名（受控）
  @State username: string = '';
  // 密码（受控）
  @State password: string = '';
  // 记住我（默认勾选）
  @State remember: boolean = true;
  // 登录中加载态（禁用按钮并显示"登录中..."）
  @State loading: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private authStore = new AuthStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  /**
   * 登录处理
   * 流程：校验输入 → 调用登录 API → 写入 tokens → 拉取用户信息 → 跳转 Dashboard
   * 异常：捕获并记录日志，向用户展示错误消息；无论成败 finally 重置 loading
   */
  private async handleLogin(): Promise<void> {
    // 校验：用户名或密码为空时给出警告，不发起请求
    if (!this.username || !this.password) {
      this.msg.warning('请输入用户名和密码');
      return;
    }
    this.loading = true;
    try {
      // 调用登录 API
      const res = await this.api.auth.login({ username: this.username, password: this.password });
      if (res.code === 0 && res.data) {
        // 写入 tokens（access_token / refresh_token）
        this.authStore.setTokens(res.data);
        // 拉取并写入当前用户信息
        const meRes = await this.api.auth.me();
        if (meRes.code === 0 && meRes.data) {
          this.authStore.setUser(meRes.data);
        }
        this.msg.success('登录成功');
        // 清空栈并跳转到 Dashboard
        this.router.resetTo(RouteNames.DASHBOARD);
      } else {
        // 业务失败：展示后端返回的错误消息
        this.msg.error(res.message || '登录失败');
      }
    } catch (e) {
      // 网络或未知异常：记录日志并提示用户
      this.logger.error('LoginPage', '登录失败', e as Error);
      this.msg.error('登录失败：' + (e as Error).message);
    } finally {
      this.loading = false;
    }
  }

  /**
   * 注册入口
   * 说明：当前路由表尚未提供注册页（RouteNames 无 REGISTER），
   *       此处仅给出提示，待注册页落地后替换为 router.push
   */
  private handleRegister(): void {
    this.msg.info('注册功能即将开放');
  }

  build() {
    Stack() {
      // 背景层：全屏星空
      StarBackground({ starCount: 80, twinkle: true })

      // 表单层：垂直居中
      Column() {
        GlassPanel({ variant: 'elevated', padding: 24, radius: 16 }) {
          Column() {
            // 主标题
            Text('Neurova')
              .fontSize(32)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))

            // 副标题
            Text('登录')
              .fontSize(16)
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 4 })

            // 用户名输入框
            GlassInput({
              placeholder: '用户名',
              value: this.username,
              type: 'text',
              onChange: (v: string) => { this.username = v; }
            })
              .margin({ top: 24 })

            // 密码输入框（间距 16）
            GlassInput({
              placeholder: '密码',
              value: this.password,
              type: 'password',
              onChange: (v: string) => { this.password = v; }
            })
              .margin({ top: 16 })

            // 记住我：ArkUI Checkbox + 文本（点击文本也可切换）
            Row() {
              Checkbox({ name: 'remember', group: 'login' })
                .select(this.remember)
                .selectedColor(this.sm.getColor('primary'))
                .onChange((v: boolean) => { this.remember = v; })
              Text('记住我')
                .fontSize(14)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 8 })
                .onClick(() => { this.remember = !this.remember; })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .margin({ top: 16 })

            // 登录按钮：primary + block，loading 时禁用并显示"登录中..."
            GlassButton({
              text: this.loading ? '登录中...' : '登录',
              type: 'primary',
              block: true,
              disabled: this.loading,
              onClick: () => { this.handleLogin(); }
            })
              .margin({ top: 24 })

            // 注册链接：居中
            Row() {
              Text('还没账号？')
                .fontSize(14)
                .fontColor(this.sm.getColor('text_secondary'))
              Text('注册')
                .fontSize(14)
                .fontColor(this.sm.getColor('primary'))
                .margin({ left: 4 })
                .onClick(() => { this.handleRegister(); })
            }
            .width('100%')
            .justifyContent(FlexAlign.Center)
            .margin({ top: 16 })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Center)
        }
        .width(360)
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      .alignItems(HorizontalAlign.Center)
    }
    .width('100%')
    .height('100%')
  }
}
