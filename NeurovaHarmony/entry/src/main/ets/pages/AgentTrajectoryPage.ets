/**
 * AgentTrajectoryPage - Agent 轨迹点页
 *
 * 职责：展示当前 Agent 的轨迹点序列，按 sessionId 筛选，支持查看详情
 * 设计：
 *   - TrajectoryViewHelper（导出）：纯视图模型，封装动作图标映射、动作标签映射、
 *     步骤格式化、奖励值格式化、观察摘要截断、时间戳格式化；无 UI 运行时依赖，可独立单元测试；
 *   - AgentTrajectoryPage（@Component）：Stack [Column(TopNavMenu(标题"轨迹点"+返回)
 *     + 加载态/空态/列表)] + [详情弹窗条件渲染]；列表项 GlassCard 含 step 序号、action emoji、
 *     observation 摘要、reward（如有）、timestamp、查看详情按钮；详情走内嵌 Stack 条件渲染弹窗
 *     展示完整 step/action/observation/reward/timestamp；列表按 step 升序排列；
 *   - 颜色统一走 StyleManager（颜色方法返回 token 名），路由走 Router，
 *     API 走 ApiFacade.runtime，状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（TrajectoryViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getActionIcon / getActionLabel 返回 emoji 与中文短名；
 *   - formatStep 将 step 数字格式化为 "步骤 n"；
 *   - formatReward 处理 4 种分支：无值/正/负/零；
 *   - truncateObservation 默认 150 字符；
 *   - formatTimestamp 输出 YYYY-MM-DD HH:mm:ss 格式，无效值回退 "未知"。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime 模块：listTrajectory）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：TrajectoryPoint
 *
 * 用法：
 *   由 Router.push 跳转进入（携带可选 sessionId 参数过滤）；
 *   aboutToAppear 调用 api.runtime.listTrajectory(agentId) 加载列表；
 *   列表按 step 升序排列后渲染；
 *   详情按钮 → 弹出内嵌 Stack 弹窗展示完整字段。
 *
 * TDD：TrajectoryViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentTrajectoryPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { TrajectoryPoint } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentTrajectoryPage';

// ===========================================================================
// TrajectoryViewHelper - 轨迹点视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class TrajectoryViewHelper {
  /**
   * 获取动作对应的图标 emoji
   * 映射：click→👆，type→⌨️，scroll→📜，screenshot→📷，think→💭，speak→💬，其他→❓
   * @param action 动作类型字符串
   * @return emoji 字符串
   */
  static getActionIcon(action: string): string {
    if (action === 'click') return '👆';
    if (action === 'type') return '⌨️';
    if (action === 'scroll') return '📜';
    if (action === 'screenshot') return '📷';
    if (action === 'think') return '💭';
    if (action === 'speak') return '💬';
    return '❓';
  }

  /**
   * 获取动作对应的中文标签
   * 映射：click→点击，type→输入，scroll→滚动，screenshot→截图，think→思考，speak→说话，其他→未知
   * @param action 动作类型字符串
   * @return 中文短名
   */
  static getActionLabel(action: string): string {
    if (action === 'click') return '点击';
    if (action === 'type') return '输入';
    if (action === 'scroll') return '滚动';
    if (action === 'screenshot') return '截图';
    if (action === 'think') return '思考';
    if (action === 'speak') return '说话';
    return '未知';
  }

  /**
   * 格式化步骤序号
   * @param step 步骤序号
   * @return "步骤 n" 格式字符串
   */
  static formatStep(step: number): string {
    return `步骤 ${step}`;
  }

  /**
   * 格式化奖励值
   * @param reward 奖励值；undefined 表示无奖励
   * @return 无值→"—"，正数→"+n.nn"（带正号），负数→"n.nn"（保留负号），0→"0.00"
   */
  static formatReward(reward: number | undefined): string {
    if (reward === undefined) return '—';
    if (reward > 0) return `+${reward.toFixed(2)}`;
    if (reward < 0) return reward.toFixed(2);
    return '0.00';
  }

  /**
   * 截断观察内容，超长时截取 maxLen 字符并追加省略号
   * @param observation 原始观察内容
   * @param maxLen 最大字符数；默认 150
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateObservation(observation: string, maxLen: number = 150): string {
    if (observation.length <= maxLen) return observation;
    return observation.substring(0, maxLen) + '...';
  }

  /**
   * 格式化时间戳为 YYYY-MM-DD HH:mm:ss
   * @param ts ISO 字符串或时间戳字符串
   * @return 格式化后的时间；无效值回退 "未知"
   */
  static formatTimestamp(ts: string): string {
    if (!ts) return '未知';
    const d = new Date(ts);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    const ss = d.getSeconds().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}:${ss}`;
  }
}

// ===========================================================================
// AgentTrajectoryPage - 轨迹点页组件
//
// 设计：Stack [Column(TopNavMenu + 加载态/空态/列表)] + [详情弹窗条件渲染]；
//       数据流：aboutToAppear → api.runtime.listTrajectory → 排序渲染；
//       @State 嵌套属性变更必须整体重新赋值（detailPoint 整体替换）；
//       详情走内嵌 Stack 条件渲染弹窗（buildDetailDialog）；列表按 step 升序排列
// ===========================================================================

@Component
export struct AgentTrajectoryPage {
  // 轨迹点列表（API 返回并按 step 升序排序后，驱动列表渲染）
  @State points: TrajectoryPoint[] = [];
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 当前详情选中的轨迹点（null 时关闭弹窗；非 null 时显示详情弹窗）
  @State detailPoint: TrajectoryPoint | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTrajectory();
  }

  /**
   * 加载轨迹点
   * 流程：取 currentAgentId → 调用 api.runtime.listTrajectory → 按 step 升序排序 → 写入 points
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadTrajectory(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId;
      const res = await this.api.runtime.listTrajectory(agentId || undefined);
      if (res.code === 0 && res.data) {
        // 按 step 升序排序（不可变排序，避免直接 mutate API 返回）
        const sorted = [...res.data.items].sort((a, b) => a.step - b.step);
        this.points = sorted;
      }
    } catch (e) {
      this.logger.error(TAG, '加载轨迹点失败', e as Error);
      this.msg.error('加载轨迹点失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 展示轨迹点详情
   * 流程：整体替换 detailPoint（嵌套属性变更必须整体重新赋值）
   */
  private showDetail(point: TrajectoryPoint): void {
    this.detailPoint = point;
  }

  /** 关闭详情弹窗：整体重置为 null */
  private closeDetail(): void {
    this.detailPoint = null;
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"轨迹点" + 返回按钮
        TopNavMenu({
          title: '轨迹点',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 主体：加载态 / 空态 / 列表 三选一
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
        } else if (this.points.length === 0) {
          Column() {
            Text('暂无轨迹点')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.points, (point: TrajectoryPoint) => {
              ListItem() {
                this.buildTrajectoryCard(point)
              }
            }, (point: TrajectoryPoint) => point.id)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('sm'),
          })
        }
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // 详情弹窗：内嵌 Stack 条件渲染（detailPoint 非空时显示）
      if (this.detailPoint !== null) {
        this.buildDetailDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 轨迹点卡片构建器
  // ===========================================================================

  /** 单条轨迹点卡片：step 序号 + action emoji + observation 摘要 + reward + timestamp + 详情按钮 */
  @Builder
  buildTrajectoryCard(point: TrajectoryPoint) {
    GlassCard() {
      Column() {
        // 上部：step 序号 + action emoji + action 标签
        Row() {
          Text(TrajectoryViewHelper.formatStep(point.step))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Text(TrajectoryViewHelper.getActionIcon(point.action))
            .fontSize(this.sm.getFontSize('subtitle'))
            .margin({ left: this.sm.getSpacing('sm') })
          Text(TrajectoryViewHelper.getActionLabel(point.action))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // observation 摘要（最多 3 行）
        Text(TrajectoryViewHelper.truncateObservation(point.observation, 150))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 底部行：reward + timestamp
        Row() {
          Text(`奖励 ${TrajectoryViewHelper.formatReward(point.reward)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(point.reward !== undefined && point.reward > 0
              ? this.sm.getColor('success')
              : (point.reward !== undefined && point.reward < 0
                ? this.sm.getColor('error')
                : this.sm.getColor('text_secondary')))
          Text(TrajectoryViewHelper.formatTimestamp(point.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '查看详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(point); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器（内嵌 Stack 条件渲染）
  //
  // 设计：Stack [背景遮罩层（点击关闭）] + [GlassPanel 内容层（居中）]；
  //       detailPoint 为 null 时不渲染（由 build() 顶层 if 控制）
  // ===========================================================================

  @Builder
  buildDetailDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示详情
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题
          Text('轨迹点详情')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('md') })
            .width('100%')

          // step 序号
          Text(TrajectoryViewHelper.formatStep(this.detailPoint!.step))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // action
          Text(`${TrajectoryViewHelper.getActionIcon(this.detailPoint!.action)} ${TrajectoryViewHelper.getActionLabel(this.detailPoint!.action)}`)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')

          // observation 完整内容
          Text('观察内容')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')
          Text(this.detailPoint!.observation)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: 4 })
            .width('100%')

          // reward
          Text(`奖励：${TrajectoryViewHelper.formatReward(this.detailPoint!.reward)}`)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')

          // timestamp
          Text(`时间：${TrajectoryViewHelper.formatTimestamp(this.detailPoint!.timestamp)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.closeDetail(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('85%')
    }
    .width('100%')
    .height('100%')
  }
}
