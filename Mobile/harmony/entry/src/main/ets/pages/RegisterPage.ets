/**
 * RegisterPage - 注册页
 *
 * 职责：新用户注册入口，提供用户名/邮箱/密码/确认密码/条款同意的表单填写与提交
 * 设计：Stack 叠加 [星空背景层] + [TopNavMenu 顶部栏] + [居中玻璃面板表单层]；
 *       通过 ApiFacade.auth.register 调用后端注册接口，成功后引导用户去登录页（不自动登录）；
 *       校验失败时由 MessageManager 提示具体原因，不发起 API 调用；
 *       异常由 Logger 记录，由 MessageManager 提示用户
 *
 * 依赖：
 *   - ../components/glass：StarBackground、TopNavMenu、GlassPanel、GlassInput、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（auth.register）
 *   - ../libs/api/modules/AuthApi：AuthApi 类型（供 RegisterController 依赖注入）
 *   - ../libs/bus/EventBus：统一事件总线（成功后 emit navigation:replace）
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/types：RegisterForm、RegisterResult
 *   - ../routing/Router：RouteNames.LOGIN
 *
 * 用法：
 *   由 Router.push(RouteNames.REGISTER) 跳转进入；
 *   注册成功后通过 EventBus emit 'navigation:replace' 携带 { name: LOGIN }，引导登录；
 *   TopNavMenu 返回按钮调用 router.back()
 *
 * 测试导出：
 *   - RegisterValidator：纯校验器，validate(form) 返回 { valid, field, message }
 *   - RegisterController：提交流程控制器，submit(form) 调用 API 并 emit 导航事件
 *   说明：@Component struct 无法在单元测试中实例化，故将可测试逻辑抽离为上述两个类
 */

import { RegisterForm } from '../libs/types';
import { AuthApi } from '../libs/api/modules/AuthApi';
import { EventBus } from '../libs/bus/EventBus';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { StyleManager } from '../libs/style/StyleManager';
import { Router, RouteNames } from '../routing/Router';
import { StarBackground, TopNavMenu, GlassPanel, GlassInput, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';

/** 校验结果 */
export interface ValidationResult {
  valid: boolean;
  field: string;
  message: string;
}

/**
 * RegisterValidator - 注册表单视图模型校验器
 *
 * 职责：对 RegisterForm 字段进行顺序校验，返回第一个失败字段
 * 设计：纯函数式（无副作用、无 IO），可在单元测试中直接验证
 * 顺序：username → email → password → confirmPassword → agreedTerms
 */
export class RegisterValidator {
  /**
   * 校验表单
   * 返回：{ valid: true, field: '', message: '' } 表示全部通过
   *       { valid: false, field: <字段名>, message: <原因> } 表示首个失败字段
   */
  static validate(form: RegisterForm): ValidationResult {
    // 切片1: 用户名长度校验（3-20 字符，非空）
    if (!form.username || form.username.length < 3 || form.username.length > 20) {
      return {
        valid: false,
        field: 'username',
        message: '用户名长度需为 3-20 字符',
      };
    }
    // 切片2: 邮箱格式校验（正则 ^[\w.+-]+@[\w-]+\.[\w.-]+$）
    const emailRe = /^[\w.+-]+@[\w-]+\.[\w.-]+$/;
    if (!form.email || !emailRe.test(form.email)) {
      return {
        valid: false,
        field: 'email',
        message: '邮箱格式不正确',
      };
    }
    // 切片3: 密码长度校验（≥8 字符）
    if (!form.password || form.password.length < 8) {
      return {
        valid: false,
        field: 'password',
        message: '密码长度至少 8 字符',
      };
    }
    // 切片4: 确认密码一致性校验（confirmPassword === password）
    if (form.confirmPassword !== form.password) {
      return {
        valid: false,
        field: 'confirmPassword',
        message: '两次输入的密码不一致',
      };
    }
    // 切片5: 条款同意校验（agreedTerms 必须为 true）
    if (!form.agreedTerms) {
      return {
        valid: false,
        field: 'agreedTerms',
        message: '请同意服务条款',
      };
    }
    // 切片6: 全部校验通过
    return { valid: true, field: '', message: '' };
  }
}

/** 导航事件载荷 */
interface NavigationReplacePayload {
  name: string;
}

/**
 * RegisterController - 注册提交流程控制器
 *
 * 职责：校验表单 → 调用 AuthApi.register → 成功后通过 EventBus emit 导航事件
 * 设计：依赖注入（AuthApi + EventBus），便于单元测试用 mock backend 验证事件契约；
 *       MessageManager/Logger 通过单例获取，避免构造参数膨胀
 *
 * 流程：
 *   1. 调用 RegisterValidator.validate，失败时 msg.error 并返回
 *   2. 调用 authApi.register({ username, email, password })
 *   3. 成功（code === 0）：msg.success + bus.emit('navigation:replace', { name: LOGIN })
 *   4. 业务失败（code !== 0）：msg.error(res.message)
 *   5. 异常：logger.error + msg.error('注册失败')
 */
export class RegisterController {
  private logger: Logger = Logger.getInstance();
  private msg: MessageManager = MessageManager.getInstance();

  constructor(
    private authApi: AuthApi,
    private bus: EventBus,
  ) {}

  /**
   * 提交注册表单
   * 成功后 emit 'navigation:replace' 事件，由 Router 或页面订阅者执行实际跳转
   */
  async submit(form: RegisterForm): Promise<void> {
    // 1. 前端校验
    const result = RegisterValidator.validate(form);
    if (!result.valid) {
      this.msg.error(result.message);
      return;
    }
    // 2. 调用注册 API
    try {
      const res = await this.authApi.register({
        username: form.username,
        email: form.email,
        password: form.password,
      });
      // 3. 成功：提示并 emit 导航事件，引导去登录
      if (res.code === 0) {
        this.msg.success('注册成功');
        const payload: NavigationReplacePayload = { name: RouteNames.LOGIN };
        this.bus.emit('navigation:replace', payload as Object);
      } else {
        // 4. 业务失败：展示后端返回的错误消息
        this.msg.error(res.message || '注册失败');
      }
    } catch (e) {
      // 5. 异常：记录日志并提示用户
      this.logger.error('RegisterPage', '注册失败', e as Error);
      this.msg.error('注册失败');
    }
  }
}

/** 日志标签 */
const TAG = 'RegisterPage';

/**
 * RegisterPage - 注册页 UI 组件
 *
 * UI 结构：Stack [StarBackground] + [Column(TopNavMenu + GlassPanel 表单)]
 * 表单字段：username / email / password / confirmPassword / agreedTerms
 * 提交：委托 RegisterController.submit，成功后由 controller emit 导航事件
 */
@Component
export struct RegisterPage {
  // 用户名（受控）
  @State username: string = '';
  // 邮箱（受控）
  @State email: string = '';
  // 密码（受控）
  @State password: string = '';
  // 确认密码（受控）
  @State confirmPassword: string = '';
  // 是否同意条款
  @State agreedTerms: boolean = false;
  // 提交中加载态（禁用按钮并显示"注册中..."）
  @State loading: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private bus = EventBus.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  // 提交流程控制器：注入 authApi 与 bus，便于测试
  private controller = new RegisterController(this.api.auth, this.bus);

  /**
   * 提交注册
   * 流程：构造 form → 调用 controller.submit → finally 重置 loading
   */
  private async handleSubmit(): Promise<void> {
    this.loading = true;
    try {
      const form: RegisterForm = {
        username: this.username,
        email: this.email,
        password: this.password,
        confirmPassword: this.confirmPassword,
        agreedTerms: this.agreedTerms,
      };
      await this.controller.submit(form);
    } catch (e) {
      this.logger.error(TAG, 'handleSubmit 异常', e as Error);
      this.msg.error('注册失败');
    } finally {
      this.loading = false;
    }
  }

  /** 跳转登录页（"已有账号？去登录"按钮） */
  private handleGotoLogin(): void {
    this.router.replace(RouteNames.LOGIN);
  }

  build() {
    Stack() {
      // 背景层：全屏星空
      StarBackground({ starCount: 80, twinkle: true })

      // 内容层：顶部栏 + 表单
      Column() {
        // 顶部导航栏：标题"注册账号" + 返回按钮
        TopNavMenu({
          title: '注册账号',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 表单容器：居中玻璃面板
        Column() {
          GlassPanel({ variant: 'elevated', padding: 24, radius: 16 }) {
            Column() {
              // 主标题
              Text('Neurova')
                .fontSize(32)
                .fontWeight(FontWeight.Bold)
                .fontColor(this.sm.getColor('text_primary'))

              // 副标题
              Text('创建账号')
                .fontSize(16)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 4 })

              // 用户名输入框
              GlassInput({
                placeholder: '用户名（3-20 字符）',
                value: this.username,
                type: 'text',
                onChange: (v: string) => { this.username = v; }
              })
                .margin({ top: 24 })

              // 邮箱输入框
              GlassInput({
                placeholder: '邮箱',
                value: this.email,
                type: 'text',
                onChange: (v: string) => { this.email = v; }
              })
                .margin({ top: 16 })

              // 密码输入框
              GlassInput({
                placeholder: '密码（≥8 字符）',
                value: this.password,
                type: 'password',
                onChange: (v: string) => { this.password = v; }
              })
                .margin({ top: 16 })

              // 确认密码输入框
              GlassInput({
                placeholder: '确认密码',
                value: this.confirmPassword,
                type: 'password',
                onChange: (v: string) => { this.confirmPassword = v; }
              })
                .margin({ top: 16 })

              // 同意条款：Checkbox + 文本（点击文本也可切换）
              Row() {
                Checkbox({ name: 'agreedTerms', group: 'register' })
                  .select(this.agreedTerms)
                  .selectedColor(this.sm.getColor('primary'))
                  .onChange((v: boolean) => { this.agreedTerms = v; })
                Text('我已阅读并同意服务条款')
                  .fontSize(14)
                  .fontColor(this.sm.getColor('text_secondary'))
                  .margin({ left: 8 })
                  .onClick(() => { this.agreedTerms = !this.agreedTerms; })
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)
              .margin({ top: 16 })

              // 注册按钮：primary + block，loading 时禁用并显示"注册中..."
              GlassButton({
                text: this.loading ? '注册中...' : '注册',
                type: 'primary',
                block: true,
                disabled: this.loading,
                onClick: () => { this.handleSubmit(); }
              })
                .margin({ top: 24 })

              // 去登录按钮：ghost + block
              GlassButton({
                text: '已有账号？去登录',
                type: 'ghost',
                block: true,
                disabled: this.loading,
                onClick: () => { this.handleGotoLogin(); }
              })
                .margin({ top: 12 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Center)
          }
          .width(360)
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }
      .width('100%')
      .height('100%')
    }
    .width('100%')
    .height('100%')
  }
}
