import { AbilityConstant, ConfigurationConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { HttpAdapter } from '../libs/adapters';
import { EventBus } from '../libs/bus/EventBus';
import { PendingDeepLink } from '../routing/PendingDeepLink';
import { Router, RouteNames } from '../routing/Router';
import { DeviceBridgeService } from '../libs/capability/DeviceBridgeService';

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
    // 设备桥（2026-11-23 计划 H1/H3）：应用级装配——命令执行、hello 上报、
    // 与聊天页解耦的常驻连接消费方
    DeviceBridgeService.getInstance().init(this.context);
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
    } catch (e) {
      hilog.error(EntryAbility.DOMAIN, EntryAbility.TAG, '色彩模式设置失败: %{public}s', (e as Error).message);
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
      // 窗口背景/系统栏属性必须在首页装载、窗口进入就绪态后再设——同步期调用
      // 会报「This window state is abnormal」，且异常会吞掉系统栏设置，
      // 把窗口留在未绘制态（实测表现为登录后整屏黑）。
      // 三个设置都是异步 Promise：拒绝不进同步 catch，统一走 setupWindow 的 catch 记日志。
      const setupWindow = async (): Promise<void> => {
        const mainWindow = windowStage.getMainWindowSync();
        // 边到边：窗口铺满全屏（含状态栏/导航栏带），星野上下连贯不留白带；
        // 系统栏透明显出应用背景，栏内容色按主题亮/暗
        mainWindow.setWindowBackgroundColor('#0a0e1d');
        await mainWindow.setWindowLayoutFullScreen(true);
        await mainWindow.setWindowSystemBarProperties({
          statusBarColor: '#00000000',
          navigationBarColor: '#00000000',
          statusBarContentColor: '#ffffff',
          navigationBarContentColor: '#ffffff',
        });
        // 键盘避让改 RESIZE：默认 OFFSET 会把整页上移，聊天页头部/消息被顶出屏幕
        // （真机实测键盘弹起即"消失"）；RESIZE 让页面收缩、输入条上浮，头部与消息
        // 保持可见——在 Index.aboutToAppear 里经组件 UIContext 设置（UIAbility 无此接口）
        // 避让高度按设备实况读取（不同分辨率/挖孔/导航栏形态自适应），存全局供根容器取用
        const sysArea = mainWindow.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM);
        const navArea = mainWindow.getWindowAvoidArea(window.AvoidAreaType.TYPE_SYSTEM_GESTURE);
        AppStorage.setOrCreate('appTopInsetPx', sysArea.topRect.height);
        AppStorage.setOrCreate('appBottomInsetPx', navArea.bottomRect.height);
      };
      setupWindow().catch((e: Error) => {
        hilog.error(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口主题设置失败: %{public}s', (e as Error).message);
      });
      hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '首页加载完成');
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '窗口销毁');
  }

  onForeground(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '进入前台');
    // 前台恢复广播：聊天页据此补连 WS（重连预算耗尽/退后台定时器挂起后，
    // 不再依赖页面重建才恢复——2026-11-24 真机验证发现的断线不自愈缺口）
    EventBus.getInstance().emit('app:foreground', Date.now() as Object);
  }

  onBackground(): void {
    hilog.info(EntryAbility.DOMAIN, EntryAbility.TAG, '进入后台');
  }
}
