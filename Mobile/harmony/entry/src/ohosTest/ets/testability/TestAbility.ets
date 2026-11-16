/**
 * TestAbility - ohosTest 宿主 Ability（hypium 标准装配）
 *
 * 仅加载空页面承载测试进程；delegator 由 TestRunner 自取，不经全局变量传递。
 */
import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';

const domain: number = 0x0000;
const tag: string = 'testTag';

export default class TestAbility extends UIAbility {
  onCreate(): void {
    hilog.info(domain, tag, '%{public}s', 'TestAbility onCreate');
  }

  onDestroy(): void {
    hilog.info(domain, tag, '%{public}s', 'TestAbility onDestroy');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(domain, tag, '%{public}s', 'TestAbility onWindowStageCreate');
    windowStage.loadContent('testability/pages/Index', (err) => {
      if (err.code) {
        hilog.error(domain, tag, 'Failed to load content. Cause: %{public}s', JSON.stringify(err));
        return;
      }
      hilog.info(domain, tag, '%{public}s', 'Succeeded in loading content.');
    });
  }
}
