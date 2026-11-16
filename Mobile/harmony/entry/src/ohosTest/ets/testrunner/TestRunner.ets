/**
 * TestRunner - ohosTest 测试执行器（ hypium 标准装配）
 *
 * 形态对齐 SDK 自带 OpenHarmonyTestRunner（ets-loader/node_modules/@ohos/hypium）：
 * onRun 里取 abilityDelegator 与启动参数，交给 Hypium.hypiumTest 跑 List.test 的全套件。
 */
import abilityDelegatorRegistry from '@ohos.app.ability.abilityDelegatorRegistry';
import TestRunner from '@ohos.application.testRunner';
import { hilog } from '@kit.PerformanceAnalysisKit';
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
    Hypium.hypiumTest(abilityDelegator, abilityDelegatorArguments, testsuite);
    hilog.info(domain, tag, '%{public}s', 'NeurovaTestRunner onRun end');
  }
}
