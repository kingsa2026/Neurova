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
import { http } from '@kit.NetworkKit';

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
  // 当前 PC 终端档案（F1 终端胶囊：只显示地址 IP:端口）
  @State serverLabel: string = '';
  // 终端连通性：0=检测中（灰）1=可达（绿）-1=不可达（红）——胶囊图标据此变色
  @State serverReachable: number = 0;
  // 终端档案编辑（胶囊点击呼出：改名称/地址三要素，保存后立即重连装配点）
  @State showServerEdit: boolean = false;
  @State editServerName: string = '';
  @State editServerHost: string = '';
  @State editServerPort: string = '';
  @State editServerSsl: boolean = false;

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
    // F1 终端胶囊：只显示地址（IP:端口，去协议头与名称）——胶囊不堆文字
    const active = ServerProfiles.getInstance().getActive();
    if (active) {
      this.serverLabel = active.baseUrl.replace(/^https?:\/\//, '');
      this.checkServerReachable(active.baseUrl);
    }
  }

  /**
   * 终端连通性探测：GET {baseUrl}/health，3s 超时。
   * 可达 → 胶囊图标绿；不可达/超时 → 红；检测中 → 灰。fail-soft，不阻塞登录。
   */
  private checkServerReachable(baseUrl: string): void {
    this.serverReachable = 0;
    const httpRequest = http.createHttp();
    httpRequest.request(baseUrl + '/health', {
      method: http.RequestMethod.GET,
      connectTimeout: 3000,
      readTimeout: 3000
    }, (err, data) => {
      const ok = !err && data.responseCode >= 200 && data.responseCode < 300;
      this.serverReachable = ok ? 1 : -1;
      httpRequest.destroy();
    });
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

              // 终端档案胶囊（F1 .srv-chip：仅显示地址 IP:端口）
              if (this.serverLabel !== '') {
                Row() {
                  AppIcon({ name: 'server', iconSize: 14, color: this.serverReachable === 1 ? this.sm.getColor('success') : (this.serverReachable === -1 ? this.sm.getColor('error') : this.sm.getColor('text_tertiary')) })
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
                .onClick(() => {
                  const active = ServerProfiles.getInstance().getActive();
                  if (active) {
                    this.editServerName = active.name;
                    const parts = ServerProfiles.splitBaseUrl(active.baseUrl);
                    this.editServerHost = parts.addr;
                    this.editServerPort = parts.port;
                    this.editServerSsl = parts.ssl;
                    this.showServerEdit = true;
                  }
                })
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

      // 终端档案编辑弹层（F1 胶囊点击呼出）
      this.buildServerEditDialog()
    }
    .width('100%')
    .height('100%')
  }

  /** 终端档案编辑弹层（F1 胶囊点击呼出：改名称/URL，保存后立即重连装配点） */
  @Builder
  buildServerEditDialog() {
    if (this.showServerEdit) {
      Stack({ alignContent: Alignment.Center }) {
        // 背景遮罩层：点击空白处关闭
        Column()
          .width('100%')
          .height('100%')
          .backgroundColor(this.sm.getColor('overlay_mask'))
          .onClick(() => { this.showServerEdit = false; })

        // 面板层：不透明 surface 底（用户拍板编辑弹层不用透明玻璃——防下层渐变透成背景条）
        Column() {
            Column() {
              Text('编辑终端档案')
                .fontSize(this.sm.getFontSize('subtitle'))
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))
                .width('100%')

              Text('名称')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: this.sm.getSpacing('sm') })
              GlassInput({
                placeholder: '如：家里 / VPS',
                value: this.editServerName,
                type: 'text',
                onChange: (v: string) => { this.editServerName = v; }
              })

              Text('地址（IP 或中继域名）')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: this.sm.getSpacing('sm') })
              GlassInput({
                placeholder: '如 192.168.1.5 或 relay.example.com',
                value: this.editServerHost,
                type: 'text',
                onChange: (v: string) => { this.editServerHost = v; }
              })

              Text('端口')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .margin({ top: this.sm.getSpacing('sm') })
              GlassInput({
                placeholder: '如 9527',
                value: this.editServerPort,
                type: 'text',
                onChange: (v: string) => { this.editServerPort = v; }
              })

              // SSL 开关：开自动补 https，关自动补 http（滑动开关）
              Row() {
                Text('SSL')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                Toggle({ type: ToggleType.Switch, isOn: this.editServerSsl })
                  .selectedColor(this.sm.getColor('primary'))
                  .onChange((on: boolean) => { this.editServerSsl = on; })
              }
              .width('100%')
              .justifyContent(FlexAlign.End)
              .margin({ top: this.sm.getSpacing('sm') })

              Row() {
                GlassButton({
                  text: '取消',
                  type: 'default',
                  btnSize: 'medium',
                  onTap: () => { this.showServerEdit = false; }
                })
                GlassButton({
                  text: '保存',
                  type: 'primary',
                  btnSize: 'medium',
                  onTap: () => { this.saveServerEdit(); }
                })
                  .margin({ left: this.sm.getSpacing('sm') })
              }
              .width('100%')
              .justifyContent(FlexAlign.End)
              .margin({ top: this.sm.getSpacing('md') })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
        }
        .width('90%')
        .padding(20)
        .borderRadius(16)
        .backgroundColor(this.sm.getColor('surface'))
        .border({ width: 1, color: this.sm.getColor('border') })
      }
      .width('100%')
      .height('100%')
    }
  }

  /** 保存终端档案编辑：三要素拼完整地址 → 更新档案 → 重连 HTTP 装配点 → 刷新胶囊 */
  private async saveServerEdit(): Promise<void> {
    if (this.editServerHost.trim().length === 0) {
      this.msg.warning('请填写终端地址（IP 或中继域名）');
      return;
    }
    const url = ServerProfiles.joinBaseUrl(this.editServerSsl, this.editServerHost, this.editServerPort);
    const profiles = ServerProfiles.getInstance();
    const active = profiles.getActive();
    if (!active) {
      return;
    }
    await profiles.update(active.id, this.editServerName.trim(), url);
    const updated = profiles.getActive();
    if (updated) {
      this.serverLabel = updated.baseUrl.replace(/^https?:\/\//, '');
      this.checkServerReachable(updated.baseUrl);
    }
    await this.cm.applyServerProfile(profiles.getActiveApiBase(), getContext(this) as Context);
    this.showServerEdit = false;
    this.msg.success('终端档案已更新');
  }
}
