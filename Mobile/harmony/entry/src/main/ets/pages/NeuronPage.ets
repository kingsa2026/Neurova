/**
 * NeuronPage - 神经元页
 *
 * 职责：展示 NEURON 网络神经元列表，按 agentId 筛选，显示状态徽章、连接数、
 *   激活值/阈值进度条，支持点击查看详情、触发放电
 * 设计：
 *   - NeuronViewHelper（导出）：纯视图模型，封装神经元状态颜色/图标/标签映射、
 *     激活值百分比格式化、激活条颜色分级（低/中/高）、神经元名称截断，
 *     无 UI 运行时依赖，可独立单元测试；
 *   - NeuronPage（@Component）：Stack[Column[TopNavMenu(标题"神经元"+返回+新建)]
 *     + [agentId 筛选输入]
 *     + [加载态/空态/列表] + [详情弹窗]]；
 *     列表项 GlassCard 含 状态徽章（颜色按状态区分）、名称、连接数、
 *     activation 进度条（颜色按值分级）、threshold 进度条；
 *     点击项 → 打开详情弹窗（内嵌 Stack 条件渲染）；
 *     详情弹窗含完整信息 + "触发放电"按钮（调用 api.monitor.fireNeuron）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor.listNeurons/getNeuron/updateNeuron/fireNeuron）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Neuron、NeuronState
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listNeurons 加载列表；
 *   agentId 筛选输入 → 重新加载；
 *   点击列表项 → 打开详情弹窗；
 *   详情弹窗"触发放电"按钮 → 调用 api.monitor.fireNeuron → 刷新列表；
 *   新建按钮 → 提示"功能开发中"（MonitorApi 暂无 createNeuron 接口）
 *
 * TDD：NeuronViewHelper 各方法按红绿灯垂直切片逐步实现，详见 NeuronPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Neuron, NeuronState } from '../libs/types';

/** 日志标签 */
const TAG = 'NeuronPage';

/** 默认神经元名称截断长度（神经元页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

// ===========================================================================
// NeuronViewHelper - 神经元视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'success'/'error'/
//   'warning'/'text_secondary'），不加 'status_' 前缀。StyleManager 的 ColorToken 类型
//   仅包含未加前缀的 token，'status_info' 不在其列，调用 getColor('status_info') 会
//   回退到 '#000000'（黑色）。为避免此 bug，统一使用未加前缀的 token。
// ===========================================================================

export class NeuronViewHelper {
  /**
   * 获取神经元状态对应的颜色 token 名
   * 映射：idle→text_secondary, active→info, firing→success, inhibited→error
   * @param state 神经元状态
   * @return StyleManager 颜色 token 名
   */
  static getStateColor(state: NeuronState): string {
    if (state === 'idle') return 'text_secondary';
    if (state === 'active') return 'info';
    if (state === 'firing') return 'success';
    return 'error';
  }

  /**
   * 获取神经元状态对应的图标 emoji
   * 映射：idle→💤, active→⚡, firing→🔥, inhibited→🚫
   * @param state 神经元状态
   * @return emoji 字符串
   */
  static getStateIcon(state: NeuronState): string {
    if (state === 'idle') return '💤';
    if (state === 'active') return '⚡';
    if (state === 'firing') return '🔥';
    return '🚫';
  }

  /**
   * 获取神经元状态对应的中文标签
   * 映射：idle→空闲, active→活跃, firing→激发, inhibited→抑制
   * @param state 神经元状态
   * @return 中文标签
   */
  static getStateLabel(state: NeuronState): string {
    if (state === 'idle') return '空闲';
    if (state === 'active') return '活跃';
    if (state === 'firing') return '激发';
    return '抑制';
  }

  /**
   * 格式化激活值为百分比字符串
   * 规则：
   *   - activation 范围 [0, 1]，超出则截断到边界
   *   - 保留 1 位小数，格式 "XX.X%"
   * @param activation 激活值（0-1）
   * @return 百分比字符串
   */
  static formatActivation(activation: number): string {
    // 截断到 [0, 1] 范围
    const clamped = Math.max(0, Math.min(1, activation));
    const percent = clamped * 100;
    return `${percent.toFixed(1)}%`;
  }

  /**
   * 获取激活进度条对应的颜色 token 名（按激活值分级）
   * 映射：
   *   - <0.3 → info（低激活，蓝色）
   *   - 0.3~0.7 → warning（中激活，黄色）
   *   - >0.7 → success（高激活，绿色）
   * @param activation 激活值（0-1）
   * @return StyleManager 颜色 token 名
   */
  static getActivationBarColor(activation: number): string {
    if (activation < 0.3) return 'info';
    if (activation > 0.7) return 'success';
    return 'warning';
  }

  /**
   * 截断神经元名称
   * 规则：
   *   - name 为空 → 原样返回
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param name 神经元名称
   * @param maxLen 最大长度，默认 100
   * @return 截断后的名称
   */
  static truncateNeuronName(name: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!name || name.length === 0) return name;
    if (name.length <= len) return name;
    return name.substring(0, len) + '...';
  }
}

@Component
export struct NeuronPage {
  // 神经元列表
  @State neurons: Neuron[] = [];
  // 加载态
  @State loading: boolean = true;
  // agentId 筛选输入值
  @State agentIdFilter: string = '';
  // 详情弹窗显示状态
  @State showDetailDialog: boolean = false;
  // 当前查看详情的神经元
  @State currentNeuron: Neuron | undefined = undefined;
  // 触发放电中态
  @State firing: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadNeurons();
  }

  /**
   * 加载神经元列表
   * 流程：调用 api.monitor.listNeurons(agentId) → 写入 neurons
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadNeurons(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentIdFilter.length > 0 ? this.agentIdFilter : undefined;
      const res = await this.api.monitor.listNeurons(agentId, { page: 1, size: 200 });
      if (res.code === 0 && res.data) {
        this.neurons = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载神经元失败', e as Error);
      this.msg.error('加载神经元列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** agentId 筛选输入变更 */
  private onAgentIdChange(v: string): void {
    this.agentIdFilter = v;
  }

  /** 触发筛选（重新加载） */
  private applyFilter(): void {
    this.loadNeurons();
  }

  /** 打开详情弹窗 */
  private openDetail(n: Neuron): void {
    this.currentNeuron = n;
    this.showDetailDialog = true;
  }

  /** 关闭详情弹窗 */
  private closeDetail(): void {
    this.showDetailDialog = false;
    this.currentNeuron = undefined;
  }

  /** 新建按钮（占位，MonitorApi 暂无 createNeuron 接口） */
  private handleCreate(): void {
    this.msg.info('功能开发中');
  }

  /**
   * 触发神经元放电
   * 流程：调用 api.monitor.fireNeuron → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async fireNeuron(): Promise<void> {
    if (!this.currentNeuron) return;
    this.firing = true;
    try {
      const res = await this.api.monitor.fireNeuron(this.currentNeuron.id);
      if (res.code === 0) {
        this.msg.success('触发放电成功');
        this.closeDetail();
        this.loadNeurons();
      } else {
        this.msg.error(res.message || '触发失败');
      }
    } catch (e) {
      this.logger.error(TAG, '触发放电失败', e as Error);
      this.msg.error('触发放电失败');
    } finally {
      this.firing = false;
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"神经元" + 返回按钮 + 新建按钮
        TopNavMenu({
          title: '神经元',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.handleCreate(); }
          })
        }

        // agentId 筛选输入 + 搜索按钮
        Row({ space: 8 }) {
          GlassInput({
            placeholder: '按 agentId 筛选',
            value: this.agentIdFilter,
            type: 'text',
            onChange: (v: string) => { this.onAgentIdChange(v); }
          })
            .layoutWeight(1)
          GlassButton({
            text: '筛选',
            type: 'default',
            size: 'small',
            onClick: () => { this.applyFilter(); }
          })
        }
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md'), top: 4, bottom: 4 })
        .alignItems(VerticalAlign.Center)

        // 主体：加载态 / 空态 / 列表
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
        } else if (this.neurons.length === 0) {
          Column() {
            Text('暂无神经元')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.neurons, (n: Neuron) => {
              ListItem() {
                this.buildNeuronCard(n)
              }
            }, (n: Neuron) => n.id)
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

      // 详情弹窗：内嵌 Stack 条件渲染
      if (this.showDetailDialog) {
        this.buildDetailDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 神经元卡片构建器
  // ===========================================================================

  /** 单个神经元卡片：状态徽章 + 名称 + 连接数 + 激活进度条 + 阈值进度条 */
  @Builder
  buildNeuronCard(n: Neuron) {
    GlassCard() {
      Column() {
        // 上部：状态徽章 + 名称
        Row() {
          // 状态徽章
          Row() {
            Text(NeuronViewHelper.getStateIcon(n.state))
              .fontSize(14)
            Text(NeuronViewHelper.getStateLabel(n.state))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(NeuronViewHelper.getStateColor(n.state)))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor('surface'))

          // 名称
          Text(NeuronViewHelper.truncateNeuronName(n.name, DEFAULT_TRUNCATE_LEN))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 8 })
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 连接数
        Text(`连接数：${n.connections}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })

        // 激活值进度条
        Column() {
          Row() {
            Text('激活值')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(NeuronViewHelper.formatActivation(n.activation))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(NeuronViewHelper.getActivationBarColor(n.activation)))
              .margin({ left: 8 })
          }
          .width('100%')
          // 进度条（用 Row 模拟）
          Row()
            .width('100%')
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('surface'))
            .margin({ top: 4 })
          Row()
            .width(`${Math.max(0, Math.min(1, n.activation)) * 100}%`)
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor(NeuronViewHelper.getActivationBarColor(n.activation)))
            .margin({ top: -6 })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: 8 })

        // 阈值进度条
        Column() {
          Row() {
            Text('阈值')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(NeuronViewHelper.formatActivation(n.threshold))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 8 })
          }
          .width('100%')
          Row()
            .width('100%')
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('surface'))
            .margin({ top: 4 })
          Row()
            .width(`${Math.max(0, Math.min(1, n.threshold)) * 100}%`)
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('text_secondary'))
            .margin({ top: -6 })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: 8 })

        // 查看详情按钮
        GlassButton({
          text: '查看详情',
          type: 'default',
          size: 'small',
          onClick: () => { this.openDetail(n); }
        })
          .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .onClick(() => { this.openDetail(n); })
  }

  // ===========================================================================
  // 详情弹窗构建器
  // ===========================================================================

  /** 神经元详情弹窗：完整信息 + 触发放电按钮 */
  @Builder
  buildDetailDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Scroll() {
          Column() {
            Text('神经元详情')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')

            // 状态徽章
            Row() {
              Text(NeuronViewHelper.getStateIcon(this.currentNeuron!.state))
                .fontSize(16)
              Text(NeuronViewHelper.getStateLabel(this.currentNeuron!.state))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor(NeuronViewHelper.getStateColor(this.currentNeuron!.state)))
                .margin({ left: 4 })
            }
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor('surface'))
            .margin({ top: 8 })

            // 名称
            Text(`名称：${this.currentNeuron!.name}`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 8 })

            // ID
            Text(`ID：${this.currentNeuron!.id}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: 4 })

            // agentId
            Text(`Agent ID：${this.currentNeuron!.agentId}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: 4 })

            // 连接数
            Text(`连接数：${this.currentNeuron!.connections}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: 4 })

            // 激活值
            Text(`激活值：${NeuronViewHelper.formatActivation(this.currentNeuron!.activation)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(NeuronViewHelper.getActivationBarColor(this.currentNeuron!.activation)))
              .width('100%')
              .margin({ top: 4 })

            // 阈值
            Text(`阈值：${NeuronViewHelper.formatActivation(this.currentNeuron!.threshold)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: 4 })

            // 上次激发时间
            Text(`上次激发：${this.currentNeuron!.lastFiredAt || '—'}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: 4 })

            // 操作按钮
            Row() {
              GlassButton({
                text: '关闭',
                type: 'default',
                size: 'medium',
                onClick: () => { this.closeDetail(); }
              })
              GlassButton({
                text: '触发放电',
                type: 'primary',
                size: 'medium',
                onClick: () => { this.fireNeuron(); }
              })
                .margin({ left: this.sm.getSpacing('sm') })
            }
            .width('100%')
            .justifyContent(FlexAlign.End)
            .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .scrollBar(BarState.Off)
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }
}
