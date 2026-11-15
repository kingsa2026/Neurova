/**
 * ReflectionPage - 反思记录页
 *
 * 职责：按时间倒序展示反思记录列表，支持查看详情、新建反思、删除反思
 * 设计：
 *   - ReflectionViewHelper（导出）：纯视图模型，封装洞察数文案、改进项数文案、内容截断、
 *     触发原因截断、相对时间格式化（今天/昨天/本周/其他边界场景），无 UI 运行时依赖，
 *     可独立单元测试；
 *   - ReflectionPage（@Component）：Stack[Column[TopNavMenu(标题"反思记录"+返回+新建)]
 *     + [加载态/空态/列表]] + [详情弹窗] + [新建弹窗]；列表项 GlassCard 含触发原因摘要、
 *     内容摘要（截断）、洞察数、改进项数、创建时间、查看/删除操作；
 *     详情弹窗内嵌 Stack 条件渲染（不单独建 CustomDialog 文件），
 *     展示完整 trigger、content、洞察列表（bullets）、改进项列表（bullets）；
 *     新建弹窗含 trigger 输入、content 文本域、insights 多行、improvements 多行；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.cognition，
 *     状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（cognition.listReflections/getReflection/
 *     createReflection/removeReflection）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ReflectionRecord
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 加载当前 Agent 的反思列表（按 createdAt 倒序）；
 *   新建按钮 → 弹出新建 Dialog → 调用 api.cognition.createReflection → 刷新列表；
 *   详情按钮 → 弹出 Dialog 展示完整内容与洞察/改进列表；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.cognition.removeReflection → 刷新列表
 *
 * TDD：ReflectionViewHelper 各方法按红绿灯垂直切片逐步实现，详见 ReflectionPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ReflectionRecord } from '../libs/types';

/** 日志标签 */
const TAG = 'ReflectionPage';

/** 默认内容截断长度 */
const DEFAULT_CONTENT_MAX_LEN = 150;

/** 默认触发原因截断长度 */
const DEFAULT_TRIGGER_MAX_LEN = 60;

/** 星期中文映射表（getDay 0=周日） */
const WEEKDAY_LABELS: string[] = ['日', '一', '二', '三', '四', '五', '六'];

// ===========================================================================
// ReflectionViewHelper - 反思视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ReflectionViewHelper {
  /**
   * 获取洞察数文案
   * @param count 洞察数量
   * @return 0 → "无洞察"，n → "洞察 n 条"
   */
  static getInsightCount(count: number): string {
    if (count <= 0) return '无洞察';
    return `洞察 ${count} 条`;
  }

  /**
   * 获取改进项数文案
   * @param count 改进项数量
   * @return 0 → "无改进"，n → "改进 n 项"
   */
  static getImprovementCount(count: number): string {
    if (count <= 0) return '无改进';
    return `改进 ${count} 项`;
  }

  /**
   * 截断反思内容，超长时截取 maxLen 字符并追加省略号
   * @param content 原始内容
   * @param maxLen 最大字符数，默认 150
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateContent(content: string, maxLen?: number): string {
    const limit = maxLen !== undefined ? maxLen : DEFAULT_CONTENT_MAX_LEN;
    if (content.length <= limit) return content;
    return content.substring(0, limit) + '...';
  }

  /**
   * 截断触发原因，超长时截取 maxLen 字符并追加省略号
   * @param trigger 原始触发原因
   * @param maxLen 最大字符数，默认 60
   * @return 截断后的触发原因；未超长则原样返回
   */
  static truncateTrigger(trigger: string, maxLen?: number): string {
    const limit = maxLen !== undefined ? maxLen : DEFAULT_TRIGGER_MAX_LEN;
    if (trigger.length <= limit) return trigger;
    return trigger.substring(0, limit) + '...';
  }

  /**
   * 格式化相对时间
   * 映射：今天 → "今天 HH:mm"，昨天 → "昨天 HH:mm"，
   *       本周（2-6 天内）→ "周X HH:mm"，其他 → "YYYY-MM-DD"
   * @param timeStr ISO 时间字符串
   * @return 格式化后的相对时间文案；空值或无效日期返回 "未知"
   */
  static formatRelativeTime(timeStr: string): string {
    if (!timeStr) return '未知';
    const input = new Date(timeStr);
    if (isNaN(input.getTime())) return '未知';

    const now = new Date();
    const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const inputMidnight = new Date(input.getFullYear(), input.getMonth(), input.getDate());
    const diffDays = Math.floor(
      (todayMidnight.getTime() - inputMidnight.getTime()) / (24 * 60 * 60 * 1000),
    );

    const hh = input.getHours().toString().padStart(2, '0');
    const mm = input.getMinutes().toString().padStart(2, '0');

    if (diffDays === 0) {
      return `今天 ${hh}:${mm}`;
    }
    if (diffDays === 1) {
      return `昨天 ${hh}:${mm}`;
    }
    if (diffDays >= 2 && diffDays <= 6) {
      const weekDayChar = WEEKDAY_LABELS[input.getDay()];
      return `周${weekDayChar} ${hh}:${mm}`;
    }

    const yyyy = input.getFullYear();
    const MM = (input.getMonth() + 1).toString().padStart(2, '0');
    const dd = input.getDate().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd}`;
  }
}

// ===========================================================================
// ReflectionPage - 反思记录页组件
//
// 设计：Stack[Column[TopNavMenu + 主体] + 详情弹窗 + 新建弹窗]；
//       数据流：aboutToAppear → api.cognition.listReflections → 按 createdAt 倒序排序 → 渲染；
//       新建/删除完成后自动刷新列表；
//       弹窗不单独建文件，通过 Stack 条件渲染内嵌在 build() 中
// ===========================================================================

@Component
export struct ReflectionPage {
  // 反思列表（由 API 加载，按 createdAt 倒序）
  @State reflections: ReflectionRecord[] = [];
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 详情弹窗可见性
  @State showDetail: boolean = false;
  // 新建弹窗可见性
  @State showCreate: boolean = false;
  // 当前选中的反思（详情弹窗使用）
  @State selectedReflection: ReflectionRecord | null = null;
  // 新建表单数据（嵌套对象，整体重新赋值）
  @State formData: {
    trigger: string;
    content: string;
    insightsText: string;
    improvementsText: string;
  } = {
    trigger: '',
    content: '',
    insightsText: '',
    improvementsText: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadReflections();
  }

  /**
   * 加载当前 Agent 的反思列表
   * 流程：取 currentAgentId → 调用 api.cognition.listReflections → 按 createdAt 倒序排序
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadReflections(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      if (!agentId) {
        this.reflections = [];
        return;
      }
      const res = await this.api.cognition.listReflections(agentId);
      if (res.code === 0 && res.data) {
        this.reflections = this.sortByCreatedAtDesc(res.data.items);
      }
    } catch (e) {
      this.logger.error(TAG, '加载反思列表失败', e as Error);
      this.msg.error('加载反思列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 按 createdAt 倒序排序（最新的在前）
   */
  private sortByCreatedAtDesc(items: ReflectionRecord[]): ReflectionRecord[] {
    return items.slice().sort((a, b) => {
      const ta = new Date(a.createdAt).getTime();
      const tb = new Date(b.createdAt).getTime();
      return tb - ta;
    });
  }

  /**
   * 打开新建弹窗
   * 重置表单为初始空值
   */
  private openCreateDialog(): void {
    this.formData = {
      trigger: '',
      content: '',
      insightsText: '',
      improvementsText: '',
    };
    this.showCreate = true;
  }

  /**
   * 关闭新建弹窗
   */
  private closeCreateDialog(): void {
    this.showCreate = false;
  }

  /**
   * 提交新建反思
   * 流程：将多行文本拆分为数组 → 调用 api.cognition.createReflection → 成功后关闭弹窗 + 刷新
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    const trigger = this.formData.trigger.trim();
    const content = this.formData.content.trim();
    if (!trigger || !content) {
      this.msg.warning('触发原因和内容不能为空');
      return;
    }
    const insights = this.splitLines(this.formData.insightsText);
    const improvements = this.splitLines(this.formData.improvementsText);
    try {
      const res = await this.api.cognition.createReflection({
        agentId: this.agentsStore.currentAgentId,
        trigger,
        content,
        insights,
        improvements,
      });
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.closeCreateDialog();
        this.loadReflections();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建反思失败', e as Error);
      this.msg.error('创建反思失败');
    }
  }

  /**
   * 将多行文本拆分为非空字符串数组（每行一条，自动 trim，过滤空行）
   */
  private splitLines(text: string): string[] {
    if (!text) return [];
    return text
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  /**
   * 打开详情弹窗
   */
  private openDetailDialog(reflection: ReflectionRecord): void {
    this.selectedReflection = reflection;
    this.showDetail = true;
  }

  /**
   * 关闭详情弹窗
   */
  private closeDetailDialog(): void {
    this.showDetail = false;
    this.selectedReflection = null;
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(reflection: ReflectionRecord): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除这条反思吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteReflection(reflection.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.cognition.removeReflection → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteReflection(reflectionId: string): Promise<void> {
    try {
      const res = await this.api.cognition.removeReflection(reflectionId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadReflections();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除反思失败', e as Error);
      this.msg.error('删除反思失败');
    }
  }

  build() {
    Stack() {
      // ========== 主页面 ==========
      Column() {
        // 顶部导航栏：标题"反思记录" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '反思记录',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openCreateDialog(); }
          })
        }

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
        } else if (this.reflections.length === 0) {
          Column() {
            Text('暂无反思记录')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
            GlassButton({
              text: '新建反思',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.openCreateDialog(); }
            })
              .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.reflections, (reflection: ReflectionRecord) => {
              ListItem() {
                this.buildReflectionCard(reflection)
              }
            }, (reflection: ReflectionRecord) => reflection.id)
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

      // ========== 详情弹窗（Stack 条件渲染，不单独建文件） ==========
      if (this.showDetail && this.selectedReflection !== null) {
        this.buildDetailDialog(this.selectedReflection)
      }

      // ========== 新建弹窗（Stack 条件渲染） ==========
      if (this.showCreate) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 列表项卡片构建器
  // ===========================================================================

  /** 单条反思卡片：触发原因 + 内容摘要 + 洞察数 + 改进项数 + 创建时间 + 操作 */
  @Builder
  buildReflectionCard(reflection: ReflectionRecord) {
    GlassCard() {
      Column() {
        // 触发原因摘要（截断到 60 字符）
        Text(ReflectionViewHelper.truncateTrigger(reflection.trigger))
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')

        // 内容摘要（截断到 150 字符，最多 3 行）
        Text(ReflectionViewHelper.truncateContent(reflection.content))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 底部行：洞察数 + 改进项数 + 创建时间
        Row() {
          Text(ReflectionViewHelper.getInsightCount(reflection.insights.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('info'))

          Text(ReflectionViewHelper.getImprovementCount(reflection.improvements.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('success'))
            .margin({ left: this.sm.getSpacing('sm') })

          Text(ReflectionViewHelper.formatRelativeTime(reflection.createdAt))
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
            text: '查看',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetailDialog(reflection); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(reflection); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
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
  // 详情弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 详情弹窗：完整 trigger、content、洞察列表（bullets）、改进项列表（bullets） */
  @Builder
  buildDetailDialog(reflection: ReflectionRecord) {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      GlassCard({ title: '反思详情' }) {
        Scroll() {
          Column() {
            // 触发原因
            Text('触发原因')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(reflection.trigger)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 反思内容
            Text('反思内容')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(reflection.content)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 洞察列表（bullets）
            Text(`洞察（${reflection.insights.length}）`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('xs') })
            if (reflection.insights.length === 0) {
              Text('无洞察')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .width('100%')
                .margin({ top: 4 })
            } else {
              Column() {
                ForEach(reflection.insights, (insight: string, index: number) => {
                  Text(`• ${insight}`)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_primary'))
                    .width('100%')
                    .margin({ top: 2 })
                }, (insight: string, index: number) => `${index}-${insight}`)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
              .margin({ top: 4 })
            }

            // 改进项列表（bullets）
            Text(`改进项（${reflection.improvements.length}）`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            if (reflection.improvements.length === 0) {
              Text('无改进')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .width('100%')
                .margin({ top: 4 })
            } else {
              Column() {
                ForEach(reflection.improvements, (improvement: string, index: number) => {
                  Text(`• ${improvement}`)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_primary'))
                    .width('100%')
                    .margin({ top: 2 })
                }, (improvement: string, index: number) => `${index}-${improvement}`)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
              .margin({ top: 4 })
            }

            // 创建时间
            Text(`创建时间：${ReflectionViewHelper.formatRelativeTime(reflection.createdAt)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Off)

        // 底部按钮
        Row() {
          GlassButton({
            text: '关闭',
            type: 'default',
            size: 'medium',
            onClick: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('90%')
      .height('70%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('overlay_mask'))
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .onClick(() => { this.closeDetailDialog(); })
  }

  // ===========================================================================
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建弹窗：trigger 输入、content 文本域、insights 多行、improvements 多行 */
  @Builder
  buildCreateDialog() {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      GlassCard({ title: '新建反思' }) {
        Scroll() {
          Column() {
            // 触发原因输入
            Text('触发原因')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            GlassInput({
              placeholder: '什么触发了这次反思？',
              value: this.formData.trigger,
              onChange: (v: string) => {
                this.formData = { ...this.formData, trigger: v };
              }
            })
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 反思内容输入
            Text('反思内容')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            TextArea({
              placeholder: '详细记录你的反思...',
              text: this.formData.content,
            })
              .width('100%')
              .height(120)
              .fontSize(this.sm.getFontSize('body'))
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
              .onChange((v: string) => {
                this.formData = { ...this.formData, content: v };
              })

            // 洞察输入（多行，每行一条）
            Text('洞察（每行一条）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
              .width('100%')
            TextArea({
              placeholder: '发现了什么？\n每行一条洞察',
              text: this.formData.insightsText,
            })
              .width('100%')
              .height(100)
              .fontSize(this.sm.getFontSize('body'))
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
              .onChange((v: string) => {
                this.formData = { ...this.formData, insightsText: v };
              })

            // 改进项输入（多行，每行一条）
            Text('改进项（每行一条）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
              .width('100%')
            TextArea({
              placeholder: '计划如何改进？\n每行一条改进项',
              text: this.formData.improvementsText,
            })
              .width('100%')
              .height(100)
              .fontSize(this.sm.getFontSize('body'))
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
              .onChange((v: string) => {
                this.formData = { ...this.formData, improvementsText: v };
              })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Off)

        // 底部按钮：取消 + 提交
        Row() {
          GlassButton({
            text: '取消',
            type: 'default',
            size: 'medium',
            onClick: () => { this.closeCreateDialog(); }
          })
          GlassButton({
            text: '提交',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.submitCreate(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('90%')
      .height('75%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('overlay_mask'))
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .onClick(() => { this.closeCreateDialog(); })
  }
}
