/**
 * SleepStatusPage - 休眠状态页
 *
 * 职责：展示当前 Agent 的休眠状态，支持切换休眠模式、唤醒
 * 设计：
 *   - SleepStatusViewHelper（导出）：纯视图模型，封装休眠模式颜色映射、模式图标映射、
 *     模式标签映射、休眠时长格式化、待办数格式化、是否可唤醒判定；无 UI 运行时依赖，可独立单元测试；
 *   - SleepStatusPage（@Component）：Column [TopNavMenu(标题"休眠状态"+返回+刷新)]
 *     + [加载态/空态/内容]；内容含休眠状态概览卡（isSleeping/mode/sleepSince/wakeAt/
 *     pendingTasks）+ 模式切换按钮组（idle/light/deep）+ 唤醒按钮；历史记录区域占位
 *     "暂无历史记录"（无 API）；
 *   - 颜色统一走 StyleManager（颜色方法返回 token 名），路由走 Router，
 *     API 走 ApiFacade.runtime，状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（SleepStatusViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getModeColor / getModeIcon / getModeLabel 三组映射保持一致（idle/light/deep）；
 *   - formatSleepDuration 处理无值/有时长两种分支，时长部分支持小时+分钟混合格式；
 *   - formatPendingCount 处理 0 与 n 两种文案；
 *   - isAwakeable 仅在 isSleeping=true 时返回 true。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassStatCard、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime 模块：getSleepStatus/setSleepMode/awaken）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SleepStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.runtime.getSleepStatus(agentId) 加载状态；
 *   模式切换按钮 → api.runtime.setSleepMode(agentId, mode) → 刷新；
 *   唤醒按钮 → api.runtime.awaken(agentId) → 刷新；
 *   刷新按钮 → 重新加载状态。
 *
 * TDD：SleepStatusViewHelper 各方法按红绿灯垂直切片逐步实现，详见 SleepStatusPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassStatCard } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SleepStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'SleepStatusPage';

/** 休眠模式类型别名（便于在页面内引用） */
type SleepMode = 'idle' | 'light' | 'deep';

// ===========================================================================
// SleepStatusViewHelper - 休眠状态视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class SleepStatusViewHelper {
  /**
   * 获取休眠模式对应的颜色 token 名
   * 映射：idle→success，light→warning，deep→error
   * @param mode 休眠模式
   * @return StyleManager 颜色 token 名
   */
  static getModeColor(mode: SleepMode): string {
    if (mode === 'idle') return 'success';
    if (mode === 'light') return 'warning';
    return 'error';
  }

  /**
   * 获取休眠模式对应的图标 emoji
   * 映射：idle→💡，light→🌤️，deep→🌙
   * @param mode 休眠模式
   * @return emoji 字符串
   */
  static getModeIcon(mode: SleepMode): string {
    if (mode === 'idle') return '💡';
    if (mode === 'light') return '🌤️';
    return '🌙';
  }

  /**
   * 获取休眠模式对应的中文标签
   * 映射：idle→空闲，light→浅睡，deep→深睡
   * @param mode 休眠模式
   * @return 中文短名
   */
  static getModeLabel(mode: SleepMode): string {
    if (mode === 'idle') return '空闲';
    if (mode === 'light') return '浅睡';
    return '深睡';
  }

  /**
   * 格式化休眠时长
   * @param sleepSince 休眠开始时间 ISO 字符串；undefined 表示未休眠
   * @param now 当前时间引用；默认 new Date()（仅用于测试注入）
   * @return 无值→"未休眠"；有时长 → "已休眠 n 小时 n 分钟"（小时为 0 时仅显示分钟）
   */
  static formatSleepDuration(sleepSince: string | undefined, now: Date = new Date()): string {
    if (!sleepSince) return '未休眠';
    const start = new Date(sleepSince);
    if (isNaN(start.getTime())) return '未休眠';
    const diffMs = now.getTime() - start.getTime();
    if (diffMs <= 0) return '未休眠';
    const totalMinutes = Math.floor(diffMs / (60 * 1000));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours > 0) {
      return `已休眠 ${hours} 小时 ${minutes} 分钟`;
    }
    return `已休眠 ${minutes} 分钟`;
  }

  /**
   * 格式化待办任务数
   * @param count 待办数
   * @return 0→"无待办"，n→"待办 n 项"
   */
  static formatPendingCount(count: number): string {
    if (count === 0) return '无待办';
    return `待办 ${count} 项`;
  }

  /**
   * 判断 Agent 是否可被唤醒
   * 规则：仅当 isSleeping=true 时返回 true（休眠中才需要唤醒）
   * @param status 休眠状态对象
   * @return 是否可唤醒
   */
  static isAwakeable(status: SleepStatus): boolean {
    return status.isSleeping === true;
  }
}

// ===========================================================================
// SleepStatusPage - 休眠状态页组件
//
// 设计：Column [TopNavMenu] + [加载态/空态/内容]；
//       数据流：aboutToAppear → api.runtime.getSleepStatus → 渲染；
//       模式切换/唤醒均调用对应 API 后整体刷新 status（@State 嵌套属性整体替换）；
//       历史记录区域为占位（无 API），提示"暂无历史记录"
// ===========================================================================

@Component
export struct SleepStatusPage {
  // 当前休眠状态（API 返回的完整结构，驱动页面渲染）
  @State status: SleepStatus | null = null;
  // 加载态（控制"加载中..."占位与内容的切换）
  @State loading: boolean = true;
  // 操作进行中标志（切换模式/唤醒时禁用按钮避免重复提交）
  @State acting: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadStatus();
  }

  /**
   * 加载休眠状态
   * 流程：取 currentAgentId → 调用 api.runtime.getSleepStatus → 整体写入 status
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadStatus(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId;
      const res = await this.api.runtime.getSleepStatus(agentId || 'default');
      if (res.code === 0 && res.data) {
        // @State 嵌套属性变更必须整体重新赋值
        this.status = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '加载休眠状态失败', e as Error);
      this.msg.error('加载休眠状态失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换休眠模式
   * 流程：调用 api.runtime.setSleepMode → 整体刷新 status
   * 异常：记录日志并提示用户；finally 关闭 acting
   */
  private async switchMode(mode: SleepMode): Promise<void> {
    if (this.acting) return;
    const agentId = this.agentsStore.currentAgentId || 'default';
    this.acting = true;
    try {
      const res = await this.api.runtime.setSleepMode(agentId, mode);
      if (res.code === 0 && res.data) {
        // @State 整体替换
        this.status = res.data;
        this.msg.success(`已切换到${SleepStatusViewHelper.getModeLabel(mode)}模式`);
      } else {
        this.msg.error(res.message || '切换模式失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换休眠模式失败', e as Error);
      this.msg.error('切换休眠模式失败');
    } finally {
      this.acting = false;
    }
  }

  /**
   * 唤醒 Agent
   * 流程：调用 api.runtime.awaken → 整体刷新 status
   * 异常：记录日志并提示用户；finally 关闭 acting
   */
  private async awakenAgent(): Promise<void> {
    if (this.acting) return;
    const agentId = this.agentsStore.currentAgentId || 'default';
    this.acting = true;
    try {
      const res = await this.api.runtime.awaken(agentId);
      if (res.code === 0 && res.data) {
        // @State 整体替换
        this.status = res.data;
        this.msg.success('已唤醒');
      } else {
        this.msg.error(res.message || '唤醒失败');
      }
    } catch (e) {
      this.logger.error(TAG, '唤醒失败', e as Error);
      this.msg.error('唤醒失败');
    } finally {
      this.acting = false;
    }
  }

  /** 刷新按钮回调 */
  private handleRefresh(): void {
    this.loadStatus();
  }

  build() {
    Column() {
      // 顶部导航栏：标题"休眠状态" + 返回按钮 + 刷新按钮
      TopNavMenu({
        title: '休眠状态',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '刷新',
          type: 'primary',
          size: 'small',
          onClick: () => { this.handleRefresh(); }
        })
      }

      // 主体：加载态 / 空态 / 内容
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
      } else if (this.status === null) {
        Column() {
          Text('暂无休眠状态数据')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        Scroll() {
          Column() {
            // ========== 区块1：休眠状态概览卡 ==========
            this.buildStatusCard()

            // ========== 区块2：模式切换 + 唤醒 ==========
            this.buildActionSection()

            // ========== 区块3：历史记录占位 ==========
            this.buildHistoryPlaceholder()
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
  // 区块构建器
  // ===========================================================================

  /** 区块1：休眠状态概览卡 - isSleeping 状态 + mode + 时长 + 待办数 */
  @Builder
  buildStatusCard() {
    GlassCard({ title: '休眠状态概览' }) {
      Column() {
        // 状态行：图标 + 文案
        Row() {
          Text(this.status!.isSleeping ? '😴' : '🙂')
            .fontSize(this.sm.getFontSize('subtitle'))
          Text(this.status!.isSleeping ? '休眠中' : '已唤醒')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(SleepStatusViewHelper.getModeColor(this.status!.mode)))
            .margin({ left: this.sm.getSpacing('xs') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 模式徽章：图标 + 标签
        Row() {
          Text(SleepStatusViewHelper.getModeIcon(this.status!.mode))
            .fontSize(this.sm.getFontSize('caption'))
          Text(SleepStatusViewHelper.getModeLabel(this.status!.mode))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(SleepStatusViewHelper.getModeColor(this.status!.mode)))
            .margin({ left: 4 })
        }
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 休眠时长
        Text(SleepStatusViewHelper.formatSleepDuration(this.status!.sleepSince, new Date()))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ top: this.sm.getSpacing('sm') })

        // 待办数
        Text(SleepStatusViewHelper.formatPendingCount(this.status!.pendingTasks))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ top: this.sm.getSpacing('xs') })

        // 唤醒时间（如有）
        if (this.status!.wakeAt) {
          Text(`预计唤醒：${this.status!.wakeAt}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: this.sm.getSpacing('xs') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 区块2：模式切换按钮组 + 唤醒按钮 */
  @Builder
  buildActionSection() {
    GlassCard({ title: '休眠模式切换' }) {
      Column() {
        // 模式按钮组（横向排列）
        Row({ space: 8 }) {
          GlassButton({
            text: `${SleepStatusViewHelper.getModeIcon('idle')} ${SleepStatusViewHelper.getModeLabel('idle')}`,
            type: this.status!.mode === 'idle' ? 'primary' : 'default',
            size: 'small',
            onClick: () => { this.switchMode('idle'); }
          })
          GlassButton({
            text: `${SleepStatusViewHelper.getModeIcon('light')} ${SleepStatusViewHelper.getModeLabel('light')}`,
            type: this.status!.mode === 'light' ? 'primary' : 'default',
            size: 'small',
            onClick: () => { this.switchMode('light'); }
          })
          GlassButton({
            text: `${SleepStatusViewHelper.getModeIcon('deep')} ${SleepStatusViewHelper.getModeLabel('deep')}`,
            type: this.status!.mode === 'deep' ? 'primary' : 'default',
            size: 'small',
            onClick: () => { this.switchMode('deep'); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.SpaceBetween)

        // 唤醒按钮（仅当 isSleeping=true 时启用）
        GlassButton({
          text: SleepStatusViewHelper.isAwakeable(this.status!) ? '唤醒 Agent' : '已唤醒',
          type: SleepStatusViewHelper.isAwakeable(this.status!) ? 'primary' : 'default',
          size: 'medium',
          onClick: () => {
            if (SleepStatusViewHelper.isAwakeable(this.status!)) {
              this.awakenAgent();
            }
          }
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 区块3：历史记录占位（无 API，提示文案） */
  @Builder
  buildHistoryPlaceholder() {
    GlassCard({ title: '休眠历史' }) {
      Column() {
        Text('暂无历史记录')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .padding(this.sm.getSpacing('lg'))
      }
      .width('100%')
      .alignItems(HorizontalAlign.Center)
    }
    .width('100%')
  }
}
