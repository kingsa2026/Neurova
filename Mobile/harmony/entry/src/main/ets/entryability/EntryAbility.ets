import { AbilityConstant, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { HttpAdapter } from '../libs/adapters';

export default class EntryAbility extends UIAbility {
  private static readonly DOMAIN: number = 0x0001;
  private static readonly TAG: string = 'EntryAbility';

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(
      EntryAbility.DOMAIN,
      EntryAbility.TAG,
      'Neurova 鸿蒙 App 启动 - HarmonyOS 6.1 (API 13)'
    );
    // 组合根：把平台 HTTP 适配器注入 HttpClient——不调用 install 则所有请求
    // 抛「HttpBackend 未设置」（此前该调用全仓缺失，网络层从未装配）
    HttpAdapter.getInstance().install();
  }

  onDestroy(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, 'App 销毁');
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口创建');
    // 应用色彩模式对齐主题（默认暗色 cosmic）：模糊材质/状态栏/页签栏材质都跟随它——
    // 不设置的话系统按浅色渲染，玻璃卡与状态栏全发白
    try {
      this.context.getApplicationContext()
        .setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
      const mainWindow = windowStage.getMainWindowSync();
      mainWindow.setWindowBackgroundColor('#0a0e1d');
      mainWindow.setWindowSystemBarProperties({
        statusBarColor: '#0a0e1d',
        navigationBarColor: '#0a0e1d',
      });
    } catch (e) {
      hilog.error(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口主题设置失败: %{public}s', (e as Error).message);
    }
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
