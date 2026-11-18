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
import { AppIcon } from '../components/common/AppIcon';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager, ThemeMode } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ConfigManager } from '../libs/config/ConfigManager';
import { PlatformAdapter } from '../libs/adapters/PlatformAdapter';
import { ServerProfiles } from '../libs/config/ServerProfiles';

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
  // 当前服务器档案（F1 服务器胶囊：当前服务器 xxx）
  @State serverLabel: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private cm = ConfigManager.getInstance();
  private platform = PlatformAdapter.getInstance();
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
        // 登录成功后上报推送令牌（fail-soft；设计方案 §8.4 S-3）。
        // 只上报真实令牌：本应用尚未集成 Push Kit，config 里不会有真值——
        // 此前伪造 local- 随机串上报只会污染后端推送注册表（审计 3.8-5），
        // 真实集成落地后由集成方写入 push_token，这里才会上报。
        // deviceId 走 PlatformAdapter.getDeviceId() 单源，与登出注销同口径。
        try {
          const pushToken = this.cm.get<string>('push_token', '');
          if (pushToken.length > 0) {
            await this.api.push.upsert('harmony', pushToken, this.platform.getDeviceId());
          }
        } catch (pushErr) {
          this.logger.warn('LoginPage', '推送令牌上报失败（不影响登录）', pushErr as Error);
        }
        this.msg.success('登录成功');
        // 清空栈并跳转到 Dashboard
        this.router.resetTo(RouteNames.SHELL);
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
   * 忘记密码：恢复流程（POST /auth/recover-password）需管理员账号与主恢复密码
   * 双重校验——完整双表单留在 PC 端；移动端诚实指引，不提供残缺表单
   */
  private handleForgotPassword(): void {
    this.msg.info('找回密码需管理员账号与主恢复密码，请在 PC 端操作');
  }

  aboutToAppear(): void {
    // F1 服务器胶囊：展示当前活动档案（Index 冷启动已 load，此处只读）
    const active = ServerProfiles.getInstance().getActive();
    if (active) {
      this.serverLabel = `${active.name} · ${active.baseUrl}`;
    }
  }

  /**
   * 注册入口（RegisterPage 已落地：RegisterController → auth.register）
   */
  private handleRegister(): void {
    this.router.push(RouteNames.REGISTER);
  }

  build() {
    Stack() {
      // 背景层：全屏星空
      StarBackground({ starCount: 80, twinkle: true })

      // 表单层：垂直居中
      Column() {
        Column() {
          GlassPanel({ variant: 'elevated', innerPadding: 24, radius: 16 }) {
            Column() {
              // 品牌 LOGO（仓内真实资产：深色底用白标 / 浅色底用黑标，随主题切换；设计高 54）
              Image(this.sm.getThemeMode() === ThemeMode.DARK
                ? $r('app.media.neurova_logo_dark')
                : $r('app.media.neurova_logo_light'))
                .height(54)
                .objectFit(ImageFit.Contain)
                .margin({ top: 4 })

              // 副标题
              Text('你的私有 AI 工作台')
                .fontSize(this.sm.getFontSize('body_sm'))
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6 })

              // 用户名输入框（前缀单线图标）
              GlassInput({
                placeholder: '用户名',
                value: this.username,
                type: 'text',
                iconName: 'user',
                onChange: (v: string) => { this.username = v; }
              })
                .margin({ top: 24 })

              // 密码输入框（前缀图标 + 可见性切换）
              GlassInput({
                placeholder: '密码',
                value: this.password,
                type: 'password',
                iconName: 'lock',
                passwordToggle: true,
                onChange: (v: string) => { this.password = v; }
              })
                .margin({ top: 16 })

              // 记住我：渐变滑块开关（设计 .switch）+ 说明文案
              Row() {
                Toggle({ type: ToggleType.Switch, isOn: this.remember })
                  .selectedColor(this.sm.getColor('primary'))
                  .onChange((v: boolean) => { this.remember = v; })
                Text('记住我，下次免登录')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ left: 8 })
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
              .margin({ top: 16 })

              // 登录按钮：品牌渐变 + block，loading 时禁用并显示"登录中..."
              GlassButton({
                text: this.loading ? '登录中...' : '登 录',
                type: 'gradient',
                block: true,
                disabled: this.loading,
                onTap: () => { this.handleLogin(); }
              })
                .margin({ top: 24 })

              // 服务器档案胶囊（F1 .srv-chip：当前服务器 xxx）
              if (this.serverLabel !== '') {
                Row() {
                  AppIcon({ name: 'server', iconSize: 14, color: this.sm.getColor('success') })
                  Text('当前服务器 ')
                    .fontSize(this.sm.getFontSize('badge'))
                    .fontColor(this.sm.getColor('text_secondary'))
                  Text(this.serverLabel)
                    .fontSize(this.sm.getFontSize('badge'))
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                }
                .width('100%')
                .padding({ left: 14, right: 14, top: 9, bottom: 9 })
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('glass'))
                .border({ width: 1, color: this.sm.getColor('border') })
                .margin({ top: 22 })
                .alignItems(VerticalAlign.Center)
              }

              // 注册 / 忘记密码链接：居中（44 触控热区）
              Row() {
                Text('还没账号？')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('text_secondary'))
                Text('注册新账号')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('primary'))
                  .padding({ left: 8, right: 8, top: 10, bottom: 10 })
                  .onClick(() => { this.handleRegister(); })
                Text('忘记密码')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('primary'))
                  .padding({ left: 8, right: 8, top: 10, bottom: 10 })
                  .onClick(() => { this.handleForgotPassword(); })
              }
              .width('100%')
              .justifyContent(FlexAlign.Center)
              .margin({ top: 12 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Center)
          }
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
