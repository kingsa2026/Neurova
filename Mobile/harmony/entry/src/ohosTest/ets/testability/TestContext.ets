/**
 * TestContext - 测试期共享的 Ability 上下文
 *
 * aa test 直跑 TestRunner、不经 TestAbility 生命周期——TestRunner.onRun 先 startAbility
 * 拉起 TestAbility，onCreate 里装配；需要真实 Context 的测试（preferences 持久化等）
 * 轮询取用。
 */
import { common } from '@kit.AbilityKit';

export class TestContext {
  private static context: common.UIAbilityContext | null = null;

  static set(context: common.UIAbilityContext): void {
    TestContext.context = context;
  }

  /** 未装配时返回 null（调用方轮询等待） */
  static tryGet(): common.UIAbilityContext | null {
    return TestContext.context;
  }

  static get(): common.UIAbilityContext {
    const context = TestContext.tryGet();
    if (context === null) {
      throw new Error('TestContext 未初始化：TestAbility 尚未拉起');
    }
    return context;
  }
}
