/**
 * TestRunner - ohosTest 测试执行器（ hypium 标准装配）
 *
 * 形态对齐 SDK 自带 OpenHarmonyTestRunner（ets-loader/node_modules/@ohos/hypium）：
 * onRun 里取 abilityDelegator 与启动参数，交给 Hypium.hypiumTest 跑 List.test 的全套件。
 * aa test 直跑本 runner、不经 TestAbility 生命周期——这里先 startAbility 拉起
 * TestAbility，需要真实 Context 的测试（AuthStore 持久化等）才能拿到 UIAbilityContext。
 */
import abilityDelegatorRegistry from '@ohos.app.ability.abilityDelegatorRegistry';
import TestRunner from '@ohos.application.testRunner';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Want } from '@kit.AbilityKit';
import { Hypium } from '@ohos/hypium';
import testsuite from '../test/List.test';

const domain: number = 0x0000;
const tag: string = 'testTag';

export default class NeurovaTestRunner implements TestRunner {
  constructor() {
  }

  public onPrepare: () => void = () => {
    hilog.info(domain, tag, '%{public}s', 'NeurovaTestRunner OnPrepare');
  }

  public onRun: () => void = () => {
    hilog.info(domain, tag, '%{public}s', 'NeurovaTestRunner onRun run');
    const abilityDelegator = abilityDelegatorRegistry.getAbilityDelegator();
    const abilityDelegatorArguments = abilityDelegatorRegistry.getArguments();
    hilog.info(domain, tag, '%{public}s', 'start run testcase!!!');
    const want: Want = { bundleName: 'com.neurova.mobile', abilityName: 'TestAbility' };
    try {
      abilityDelegator.startAbility(want);
    } catch (e) {
      hilog.error(domain, tag, 'startAbility(TestAbility) 失败: %{public}s', (e as Error).message);
    }
    Hypium.hypiumTest(abilityDelegator, abilityDelegatorArguments, testsuite);
    hilog.info(domain, tag, '%{public}s', 'NeurovaTestRunner onRun end');
  }
}
