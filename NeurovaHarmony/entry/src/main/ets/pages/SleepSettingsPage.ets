/**
 * SleepSettingsPage - 休眠设置页
 *
 * 职责：配置 Agent 的休眠策略（触发条件、唤醒策略）
 * 设计：
 *   - SleepSettingsViewHelper（导出）：纯视图模型，封装设置项标签映射、分钟格式化、
 *     时间格式校验、脏数据判定、设置项负载构建、模式选项列表；无 UI 运行时依赖，可独立单元测试；
 *   - SleepSettingsPage（@Component）：Column [TopNavMenu(标题"休眠设置"+返回+保存)]
 *     + [加载态/空态/内容]；内容含 5 项设置 GlassCard：
 *       idleTimeout（slider 5-60 分钟）、sleepMode（select idle/light/deep）、
 *       wakeOnMessage（toggle）、wakeOnSchedule（toggle）、wakeTime（input HH:mm）；
 *   - 暂无专门 API，使用 api.settings.list/update 兜底；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.settings，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（SleepSettingsViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getSettingLabel 处理 5 个已知 key + 未知 key 原样返回；
 *   - formatMinutes 处理 <60 / =60 / >60 三种格式分支；
 *   - isValidTimeFormat 严格匹配 HH:mm 24 小时制；
 *   - isDirty 比较两个字段集合，任一字段不同返回 true；
 *   - buildSettingsPayload 转换 Record 为 settings.update 所需的数组格式；
 *   - getModeOptions 返回 3 个模式选项。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（settings 模块：list/update）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SettingItem（部分字段）
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.settings.list() 加载设置项并缓存原始值；
 *   修改设置项 → 本地更新 current 字典；
 *   保存按钮 → 调用 isDirty 判定 → buildSettingsPayload 转换 → api.settings.update 批量提交。
 *
 * TDD：SleepSettingsViewHelper 各方法按红绿灯垂直切片逐步实现，详见 SleepSettingsPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'SleepSettingsPage';

/** 休眠模式类型别名 */
type SleepMode = 'idle' | 'light' | 'deep';

/** 设置项 key 列表（顺序固定，便于渲染） */
const SETTING_KEYS: string[] = [
  'idleTimeout',
  'sleepMode',
  'wakeOnMessage',
  'wakeOnSchedule',
  'wakeTime',
];

/** 设置项负载条目 */
interface SettingPayloadEntry {
  key: string;
  value: Object;
}

/** 模式选项 */
interface ModeOption {
  value: string;
  label: string;
}

// ===========================================================================
// SleepSettingsViewHelper - 休眠设置视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class SleepSettingsViewHelper {
  /**
   * 获取设置项 key 对应的中文标签
   * 映射：idleTimeout→空闲超时，sleepMode→休眠模式，wakeOnMessage→消息唤醒，
   *       wakeOnSchedule→定时唤醒，wakeTime→唤醒时间，其他→key 原样返回
   * @param key 设置项 key
   * @return 中文标签；未知 key 返回原 key
   */
  static getSettingLabel(key: string): string {
    if (key === 'idleTimeout') return '空闲超时';
    if (key === 'sleepMode') return '休眠模式';
    if (key === 'wakeOnMessage') return '消息唤醒';
    if (key === 'wakeOnSchedule') return '定时唤醒';
    if (key === 'wakeTime') return '唤醒时间';
    return key;
  }

  /**
   * 格式化分钟数
   * @param minutes 分钟数
   * @return <60 → "n 分钟"，=60 → "1 小时"，>60 → "n 小时 m 分钟"
   */
  static formatMinutes(minutes: number): string {
    if (minutes < 60) {
      return `${minutes} 分钟`;
    }
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (mins === 0) {
      return `${hours} 小时`;
    }
    return `${hours} 小时 ${mins} 分钟`;
  }

  /**
   * 校验时间格式是否为 HH:mm（24 小时制）
   * @param time 时间字符串
   * @return 匹配且小时 0-23、分钟 0-59 返回 true；否则 false
   */
  static isValidTimeFormat(time: string): boolean {
    if (!time) return false;
    // 严格匹配 HH:mm（两位小时 + 冒号 + 两位分钟）
    const match = time.match(/^(\d{2}):(\d{2})$/);
    if (!match) return false;
    const hours = parseInt(match[1], 10);
    const minutes = parseInt(match[2], 10);
    if (hours < 0 || hours > 23) return false;
    if (minutes < 0 || minutes > 59) return false;
    return true;
  }

  /**
   * 判断设置项是否有改动（dirty）
   * @param current 当前值字典
   * @param original 原始值字典
   * @return 任一字段不同返回 true；全部相同返回 false
   */
  static isDirty(current: Record<string, Object>, original: Record<string, Object>): boolean {
    const keys = Object.keys(current);
    for (const key of keys) {
      if (current[key] !== original[key]) {
        return true;
      }
    }
    return false;
  }

  /**
   * 将当前值字典转换为 settings.update 所需的负载格式
   * @param current 当前值字典
   * @return 数组，每项 { key, value }
   */
  static buildSettingsPayload(current: Record<string, Object>): SettingPayloadEntry[] {
    const result: SettingPayloadEntry[] = [];
    const keys = Object.keys(current);
    for (const key of keys) {
      result.push({ key, value: current[key] });
    }
    return result;
  }

  /**
   * 获取休眠模式选项列表
   * @return 3 个选项：idle(空闲)、light(浅睡)、deep(深睡)
   */
  static getModeOptions(): ModeOption[] {
    return [
      { value: 'idle', label: '空闲' },
      { value: 'light', label: '浅睡' },
      { value: 'deep', label: '深睡' },
    ];
  }
}

// ===========================================================================
// SleepSettingsPage - 休眠设置页组件
//
// 设计：Column [TopNavMenu] + [加载态/空态/内容]；
//       数据流：aboutToAppear → api.settings.list() 加载并缓存原始值；
//       修改设置项 → 本地更新 current（嵌套属性变更必须整体替换 current 字典）；
//       保存按钮 → isDirty 判定 → buildSettingsPayload → api.settings.update 批量提交；
//       toggle/slider 实时更新本地 current，但不持久化（统一保存按钮提交）
// ===========================================================================

@Component
export struct SleepSettingsPage {
  // 当前设置项值字典（key → value），驱动表单渲染
  @State current: Record<string, Object> = {};
  // 原始设置项值字典（aboutToAppear 时缓存，用于 isDirty 比较）
  @State original: Record<string, Object> = {};
  // 加载态（控制"加载中..."占位与内容的切换）
  @State loading: boolean = true;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSettings();
  }

  /**
   * 加载设置项
   * 流程：调用 api.settings.list() → 过滤休眠相关 key → 写入 current 与 original
   * 异常：记录日志并使用默认值兜底；finally 关闭 loading
   */
  private async loadSettings(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.settings.list();
      if (res.code === 0 && res.data && res.data.length > 0) {
        // 从分组中提取休眠相关设置项
        const collected: Record<string, Object> = {};
        for (const group of res.data) {
          for (const item of group.items) {
            if (SETTING_KEYS.indexOf(item.key) >= 0) {
              collected[item.key] = item.value;
            }
          }
        }
        // 兜底默认值（API 未返回某 key 时使用默认）
        this.current = this.mergeWithDefaults(collected);
        // 深拷贝原始值用于 isDirty 比较
        this.original = { ...this.current };
      } else {
        // 后端无数据时使用默认值
        this.current = this.buildDefaults();
        this.original = { ...this.current };
      }
    } catch (e) {
      this.logger.error(TAG, '加载休眠设置失败，使用默认值', e as Error);
      this.current = this.buildDefaults();
      this.original = { ...this.current };
    } finally {
      this.loading = false;
    }
  }

  /** 构建默认设置值字典 */
  private buildDefaults(): Record<string, Object> {
    return {
      idleTimeout: 15,
      sleepMode: 'idle',
      wakeOnMessage: true,
      wakeOnSchedule: false,
      wakeTime: '08:00',
    };
  }

  /** 合并 API 返回值与默认值，确保所有 key 都有值 */
  private mergeWithDefaults(collected: Record<string, Object>): Record<string, Object> {
    const defaults = this.buildDefaults();
    return { ...defaults, ...collected };
  }

  /**
   * 更新设置项值（不可变更新）
   * @param key 设置项 key
   * @param value 新值
   */
  private updateValue(key: string, value: Object): void {
    // @State 嵌套属性变更必须整体重新赋值（spread 创建新字典）
    this.current = { ...this.current, [key]: value };
  }

  /**
   * 保存按钮回调
   * 流程：isDirty 判定 → 无修改提示"无修改" → 有修改则 buildSettingsPayload → 逐项 api.settings.update
   * 异常：记录日志并提示用户；成功后刷新 original 快照
   */
  private async handleSave(): Promise<void> {
    if (!SleepSettingsViewHelper.isDirty(this.current, this.original)) {
      this.msg.info('无修改');
      return;
    }
    // 校验 wakeTime 格式（仅在 wakeOnSchedule 开启时）
    if (this.current['wakeOnSchedule'] === true) {
      const wakeTime = String(this.current['wakeTime'] ?? '');
      if (wakeTime && !SleepSettingsViewHelper.isValidTimeFormat(wakeTime)) {
        this.msg.error('唤醒时间格式错误，应为 HH:mm');
        return;
      }
    }
    const payload = SleepSettingsViewHelper.buildSettingsPayload(this.current);
    let saved = 0;
    for (const entry of payload) {
      try {
        await this.api.settings.update(entry.key, entry.value);
        saved++;
      } catch (e) {
        this.logger.error(TAG, `保存设置项失败: ${entry.key}`, e as Error);
      }
    }
    // 刷新原始快照
    this.original = { ...this.current };
    if (saved > 0) {
      this.msg.success(`已保存 ${saved} 项`);
    } else {
      this.msg.error('保存失败');
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"休眠设置" + 返回按钮 + 保存按钮
      TopNavMenu({
        title: '休眠设置',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '保存',
          type: 'primary',
          size: 'small',
          onClick: () => { this.handleSave(); }
        })
      }

      // 主体：加载态 / 内容
      if (this.loading) {
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        Scroll() {
          Column() {
            // 5 项设置 GlassCard
            this.buildIdleTimeoutItem()
            this.buildSleepModeItem()
            this.buildWakeOnMessageItem()
            this.buildWakeOnScheduleItem()
            this.buildWakeTimeItem()
          }
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.TopStart)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 设置项构建器（每个 GlassCard 一项设置）
  // ===========================================================================

  /** 1. idleTimeout - slider 5-60 分钟 */
  @Builder
  buildIdleTimeoutItem() {
    GlassCard() {
      Column() {
        Row() {
          Text(SleepSettingsViewHelper.getSettingLabel('idleTimeout'))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
          Text(SleepSettingsViewHelper.formatMinutes(Number(this.current['idleTimeout'] ?? 15)))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('primary'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Slider({
          value: Number(this.current['idleTimeout'] ?? 15),
          min: 5,
          max: 60,
          step: 5,
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })
          .onChange((v: number) => { this.updateValue('idleTimeout', Math.round(v)); })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }

  /** 2. sleepMode - select idle/light/deep */
  @Builder
  buildSleepModeItem() {
    GlassCard() {
      Column() {
        Text(SleepSettingsViewHelper.getSettingLabel('sleepMode'))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')

        Row({ space: 8 }) {
          ForEach(SleepSettingsViewHelper.getModeOptions(), (opt: ModeOption) => {
            GlassButton({
              text: opt.label,
              type: this.current['sleepMode'] === opt.value ? 'primary' : 'default',
              size: 'small',
              onClick: () => { this.updateValue('sleepMode', opt.value); }
            })
          }, (opt: ModeOption) => opt.value)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .justifyContent(FlexAlign.SpaceBetween)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }

  /** 3. wakeOnMessage - toggle */
  @Builder
  buildWakeOnMessageItem() {
    GlassCard() {
      Row() {
        Text(SleepSettingsViewHelper.getSettingLabel('wakeOnMessage'))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
        Toggle({ type: ToggleType.Switch, isOn: Boolean(this.current['wakeOnMessage'] ?? false) })
          .onChange((isOn: boolean) => { this.updateValue('wakeOnMessage', isOn); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }

  /** 4. wakeOnSchedule - toggle */
  @Builder
  buildWakeOnScheduleItem() {
    GlassCard() {
      Row() {
        Text(SleepSettingsViewHelper.getSettingLabel('wakeOnSchedule'))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
        Toggle({ type: ToggleType.Switch, isOn: Boolean(this.current['wakeOnSchedule'] ?? false) })
          .onChange((isOn: boolean) => { this.updateValue('wakeOnSchedule', isOn); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }

  /** 5. wakeTime - input HH:mm */
  @Builder
  buildWakeTimeItem() {
    GlassCard() {
      Column() {
        Text(SleepSettingsViewHelper.getSettingLabel('wakeTime'))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')

        GlassInput({
          placeholder: '请输入 HH:mm（如 08:30）',
          value: String(this.current['wakeTime'] ?? ''),
          type: 'text',
          onChange: (v: string) => { this.updateValue('wakeTime', v); }
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('sm') })
  }
}
