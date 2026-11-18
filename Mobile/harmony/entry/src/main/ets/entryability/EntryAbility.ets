import { AbilityConstant, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { HttpAdapter } from '../libs/adapters';
import { PendingDeepLink } from '../routing/PendingDeepLink';
import { Router, RouteNames } from '../routing/Router';

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
    // C7：扫码配对深链（neurova://pair?ref=…&host=…）——冷启动先暂存，
    // Index 在档案/认证就绪完成分发后再消费（路由栈就绪时序）
    const coldUri = want?.uri ?? '';
    if (coldUri) {
      PendingDeepLink.getInstance().set(coldUri);
      hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '冷启动携带配对深链');
    }
  }

  onNewIntent(want: Want): void {
    // C7：温启动深链——应用已在前台时扫 PC 二维码进入。路由栈已挂载则直接
    // 推配对页；否则暂存待 Index 消费。
    const uri = want?.uri ?? '';
    if (!uri) {
      return;
    }
    const router = Router.getInstance();
    if (router.hasNavStack()) {
      const params: Record<string, Object> = { 'deepLinkUri': uri };
      router.push(RouteNames.PAIRING, params);
      hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '温启动深链直达配对页');
    } else {
      PendingDeepLink.getInstance().set(uri);
      hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '温启动深链暂存（路由栈未挂载）');
    }
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
