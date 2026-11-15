import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';

export default class EntryAbility extends UIAbility {
  private static readonly DOMAIN: number = 0x0001;
  private static readonly TAG: string = 'EntryAbility';

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(
      EntryAbility.DOMAIN,
      EntryAbility.TAG,
      'Neurova 鸿蒙 App 启动 - HarmonyOS 6.1 (API 13)'
    );
  }

  onDestroy(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, 'App 销毁');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口创建');
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(
          EntryAbility.DOMAIN,
          EntryAbility.TAG,
          '加载首页失败: %{public}s',
          JSON.stringify(err)
        );
        return;
      }
      hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '首页加载完成');
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口销毁');
  }

  onForeground(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '进入前台');
  }

  onBackground(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '进入后台');
  }
}
