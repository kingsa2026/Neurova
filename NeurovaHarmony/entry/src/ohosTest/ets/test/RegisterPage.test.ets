// RegisterPage 注册页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：
//   1. RegisterValidator.validate(form) 视图模型函数的 6 条校验规则
//   2. RegisterController.submit(form) 提交流程的事件契约（navigation:replace）
//
// 说明：@Component struct 依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此将可测试逻辑抽取为 RegisterValidator（纯函数式校验器）与
//       RegisterController（提交流程控制器，依赖注入），从 RegisterPage.ets 导出供测试。
//       RegisterPage 的 @Component 仅做 UI 绑定，调用 RegisterController.submit。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { EventBus } from '../../../../main/ets/libs/bus/EventBus';
import { HttpClient, HttpBackend } from '../../../../main/ets/libs/api/HttpClient';
import { AuthApi } from '../../../../main/ets/libs/api/modules/AuthApi';
import { RouteNames } from '../../../../main/ets/routing/Router';
import { ApiResponse, RegisterForm, RegisterResult } from '../../../../main/ets/libs/types';
// 切片1-6 仅需 RegisterValidator；切片7 起追加 RegisterController 导入
import { RegisterValidator, RegisterController } from '../../../../main/ets/pages/RegisterPage';

// 复用 HealthApi.test.ets 的 MockBackend 模式：注入 HttpClient 走 mock 后端
class MockBackend implements HttpBackend {
  public requests: { method: string; url: string; body: Object | null }[] = [];
  public response: ApiResponse<Object> = { code: 0, message: 'ok', data: {} };

  async request(
    method: string,
    url: string,
    body: Object | null,
    _headers: Record<string, string>,
  ): Promise<{ status: number; data: ApiResponse<Object> }> {
    this.requests.push({ method, url, body });
    return { status: 200, data: this.response };
  }
}

export default function registerPageTest() {
  describe('RegisterPage', () => {
    let bus: EventBus;

    beforeEach(() => {
      bus = EventBus.getInstance();
      bus.clearAll();
    });

    // ========== 切片1: 用户名长度校验 ==========

    it('validate_username_too_short_returns_error', 0, () => {
      const form: RegisterForm = {
        username: 'ab',          // 仅 2 字符，< 3
        email: 'user@example.com',
        password: 'password123',
        confirmPassword: 'password123',
        agreedTerms: true,
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertFalse();
      expect(result.field).assertEqual('username');
    });

    // ========== 切片2: 邮箱格式校验 ==========

    it('validate_invalid_email_returns_error', 0, () => {
      const form: RegisterForm = {
        username: 'validuser',           // 通过用户名校验
        email: 'not-an-email',           // 缺少 @
        password: 'password123',
        confirmPassword: 'password123',
        agreedTerms: true,
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertFalse();
      expect(result.field).assertEqual('email');
    });

    // ========== 切片3: 密码长度校验 ==========

    it('validate_password_too_short_returns_error', 0, () => {
      const form: RegisterForm = {
        username: 'validuser',
        email: 'user@example.com',       // 通过邮箱校验
        password: '1234567',             // 仅 7 字符，< 8
        confirmPassword: '1234567',
        agreedTerms: true,
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertFalse();
      expect(result.field).assertEqual('password');
    });

    // ========== 切片4: 确认密码一致性校验 ==========

    it('validate_password_mismatch_returns_error', 0, () => {
      const form: RegisterForm = {
        username: 'validuser',
        email: 'user@example.com',
        password: 'password123',         // 通过密码长度校验
        confirmPassword: 'password456',  // 与 password 不一致
        agreedTerms: true,
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertFalse();
      expect(result.field).assertEqual('confirmPassword');
    });

    // ========== 切片5: 条款同意校验 ==========

    it('validate_terms_not_agreed_returns_error', 0, () => {
      const form: RegisterForm = {
        username: 'validuser',
        email: 'user@example.com',
        password: 'password123',
        confirmPassword: 'password123',  // 通过确认密码校验
        agreedTerms: false,              // 未勾选条款
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertFalse();
      expect(result.field).assertEqual('agreedTerms');
    });

    // ========== 切片6: 全部校验通过路径 ==========

    it('validate_all_valid_returns_success', 0, () => {
      const form: RegisterForm = {
        username: 'validuser',           // 长度 9，符合 3-20
        email: 'user@example.com',       // 合法邮箱
        password: 'password123',         // 长度 11，≥8
        confirmPassword: 'password123',  // 一致
        agreedTerms: true,               // 已勾选
      };
      const result = RegisterValidator.validate(form);
      expect(result.valid).assertTrue();
      expect(result.field).assertEqual('');
      expect(result.message).assertEqual('');
    });

    // ========== 切片7: 注册成功应 emit navigation:replace 事件 ==========

    it('register_success_emits_navigation_event', 0, () => {
      // 准备 mock 后端：返回 code=0 的成功响应
      const backend = new MockBackend();
      backend.response = {
        code: 0,
        message: 'ok',
        data: {
          userId: 'u-1',
          username: 'validuser',
          email: 'user@example.com',
          createdAt: '2026-06-25T00:00:00Z',
        } as RegisterResult,
      };
      const client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      const authApi = new AuthApi(client);

      // 订阅 navigation:replace 事件
      let receivedNav: Record<string, string> | null = null;
      bus.on('navigation:replace', (data) => {
        receivedNav = data as Record<string, string>;
      });

      const controller = new RegisterController(authApi, bus);
      const form: RegisterForm = {
        username: 'validuser',
        email: 'user@example.com',
        password: 'password123',
        confirmPassword: 'password123',
        agreedTerms: true,
      };
      controller.submit(form);

      // 异步断言：等待 promise resolve 后验证事件已 emit
      setTimeout(() => {
        expect(receivedNav !== null).assertTrue();
        expect(receivedNav!['name']).assertEqual(RouteNames.LOGIN);
        // 验证 API 调用契约：POST /v1/auth/register
        expect(backend.requests[0].method).assertEqual('POST');
        expect(backend.requests[0].url).assertEqual('https://api.example.com/v1/auth/register');
      }, 20);
    });

    // ========== 切片8: API 业务失败不应 emit 导航事件 ==========

    it('register_api_failure_does_not_navigate', 0, () => {
      // 准备 mock 后端：返回 code=1001（用户已存在）的业务失败响应
      const backend = new MockBackend();
      backend.response = {
        code: 1001,
        message: '用户名已存在',
        data: {} as RegisterResult,
      };
      const client = HttpClient.getInstanceWithBackend(backend);
      client.setBaseUrl('https://api.example.com');
      const authApi = new AuthApi(client);

      // 订阅 navigation:replace 事件
      let navEmitted: boolean = false;
      bus.on('navigation:replace', () => {
        navEmitted = true;
      });

      const controller = new RegisterController(authApi, bus);
      const form: RegisterForm = {
        username: 'validuser',
        email: 'user@example.com',
        password: 'password123',
        confirmPassword: 'password123',
        agreedTerms: true,
      };
      controller.submit(form);

      // 异步断言：等待 promise resolve 后验证未 emit 导航事件
      setTimeout(() => {
        expect(navEmitted).assertFalse();
        // 验证 API 仍被调用（校验通过才会发起请求）
        expect(backend.requests.length).assertEqual(1);
        expect(backend.requests[0].method).assertEqual('POST');
      }, 20);
    });
  });
}
