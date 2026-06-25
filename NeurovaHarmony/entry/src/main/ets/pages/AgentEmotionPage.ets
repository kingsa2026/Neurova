/**
 * AgentEmotionPage - 情绪记录页
 *
 * 职责：展示当前 Agent 情绪历史列表，含当前情绪概览卡，支持记录创建、查看详情、删除
 * 设计：
 *   - AgentEmotionViewHelper（导出）：纯视图模型，封装情绪类型颜色映射、emoji 图标映射、
 *     中文标签、强度百分比格式化、触发原因截断，无 UI 运行时依赖，可独立单元测试；
 *   - AgentEmotionPage（@Component）：Stack[Column[TopNavMenu(标题"情绪"+返回+新建)]
 *     + [当前情绪概览卡（type 徽章 + emoji 大图 + intensity 进度条 + 触发原因 + 创建时间）]
 *     + [加载态/空态/列表] + [详情弹窗] + [新建弹窗]]；
 *     列表项 GlassCard 含 type emoji、type 徽章、intensity 进度条、触发原因摘要、
 *     创建时间、查看/删除操作；删除走 AlertDialog 二次确认；
 *     详情弹窗内嵌 Stack 条件渲染（不单独建 CustomDialog 文件），展示完整 type、intensity 百分比、
 *     trigger、创建时间；新建弹窗含 type 选择、intensity slider（0-1）、trigger 输入；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，API 走 ApiFacade.personality，
 *     状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（personality.listEmotions/getEmotion/
 *     createEmotion/removeEmotion/getCurrentEmotion）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Emotion
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 并行加载当前情绪 + 情绪历史列表；
 *   新建按钮 → 弹出新建 Dialog（type 选择/intensity slider/trigger 输入）→
 *     调用 api.personality.createEmotion → 成功后刷新列表与当前情绪；
 *   查看按钮 → 弹出详情 Dialog 展示完整字段；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.personality.removeEmotion → 刷新列表
 *
 * TDD：AgentEmotionViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentEmotionPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Emotion } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentEmotionPage';

/** 情绪类型枚举（用于新建弹窗的 type 选择列表，与 §18 Emotion.type 对齐） */
const EMOTION_TYPES: string[] = [
  'happy', 'sad', 'angry', 'surprised', 'neutral', 'fear', 'disgust',
];

// ===========================================================================
// AgentEmotionViewHelper - 情绪视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentEmotionViewHelper {
  /**
   * 获取情绪类型对应的颜色 token 名
   * 映射：happy→success，sad→info，angry→error，surprised→warning，
   *       neutral→text_secondary，fear→text_disabled，disgust→text_secondary，其他→text_disabled
   * @param type 情绪类型字符串
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: string): string {
    if (type === 'happy') return 'success';
    if (type === 'sad') return 'info';
    if (type === 'angry') return 'error';
    if (type === 'surprised') return 'warning';
    if (type === 'neutral') return 'text_secondary';
    if (type === 'fear') return 'text_disabled';
    if (type === 'disgust') return 'text_secondary';
    return 'text_disabled';
  }

  /**
   * 获取情绪类型对应的 emoji 图标
   * 映射：happy→😊，sad→😢，angry→😠，surprised→😮，neutral→😐，
   *       fear→😨，disgust→🤢，其他→❓
   * @param type 情绪类型字符串
   * @return emoji 字符串
   */
  static getTypeIcon(type: string): string {
    if (type === 'happy') return '😊';
    if (type === 'sad') return '😢';
    if (type === 'angry') return '😠';
    if (type === 'surprised') return '😮';
    if (type === 'neutral') return '😐';
    if (type === 'fear') return '😨';
    if (type === 'disgust') return '🤢';
    return '❓';
  }

  /**
   * 获取情绪类型对应的中文标签
   * 映射：happy→开心，sad→难过，angry→愤怒，surprised→惊讶，neutral→平静，
   *       fear→恐惧，disgust→厌恶，其他→未知
   * @param type 情绪类型字符串
   * @return 中文标签
   */
  static getTypeLabel(type: string): string {
    if (type === 'happy') return '开心';
    if (type === 'sad') return '难过';
    if (type === 'angry') return '愤怒';
    if (type === 'surprised') return '惊讶';
    if (type === 'neutral') return '平静';
    if (type === 'fear') return '恐惧';
    if (type === 'disgust') return '厌恶';
    return '未知';
  }

  /**
   * 格式化强度（0-1）为百分比字符串
   * @param value 强度值 0-1
   * @return 百分比字符串，如 0.5 → "50%"
   */
  static formatIntensity(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  /**
   * 截断触发原因文本
   * @param trigger 触发原因；undefined 或空字符串返回 "—"
   * @param maxLen 最大字符数，默认 60；超长时截取并追加省略号
   * @return 截断后的文本；未超长原样返回；无值返回 "—"
   */
  static truncateTrigger(trigger?: string, maxLen?: number): string {
    if (!trigger) return '—';
    const limit = maxLen ?? 60;
    if (trigger.length <= limit) return trigger;
    return trigger.substring(0, limit) + '...';
  }
}

// ===========================================================================
// AgentEmotionPage - 情绪记录页组件
//
// 设计：Stack[Column[TopNavMenu + 当前情绪概览卡 + 加载态/空态/列表] + 详情弹窗 + 新建弹窗]；
//       数据流：aboutToAppear → 并行 getCurrentEmotion + listEmotions → 渲染；
//       新建/删除操作完成后刷新列表与当前情绪；弹窗内嵌 Stack 条件渲染
// ===========================================================================

@Component
export struct AgentEmotionPage {
  // 当前情绪（概览卡数据源；null 表示尚未加载或无当前情绪）
  @State currentEmotion: Emotion | null = null;
  // 情绪历史列表（由 API 加载，驱动列表渲染）
  @State emotions: Emotion[] = [];
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 详情弹窗可见性
  @State showDetail: boolean = false;
  // 新建弹窗可见性
  @State showCreate: boolean = false;
  // 当前选中的情绪记录（详情弹窗使用）
  @State selectedEmotion: Emotion | null = null;
  // 新建表单字段：type（默认 happy）
  @State formType: string = 'happy';
  // 新建表单字段：intensity（0-1，默认 0.5）
  @State formIntensity: number = 0.5;
  // 新建表单字段：trigger（可空）
  @State formTrigger: string = '';
  // 提交中态（防止重复点击）
  @State submitting: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadAll();
  }

  /**
   * 并行加载当前情绪 + 历史列表
   * 任一失败不影响另一项；finally 关闭 loading
   */
  private async loadAll(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      if (!agentId) {
        this.currentEmotion = null;
        this.emotions = [];
        return;
      }
      // 并行加载（任一失败不阻塞另一项）
      await Promise.all([
        this.loadCurrentEmotion(agentId),
        this.loadEmotionList(agentId),
      ]);
    } finally {
      this.loading = false;
    }
  }

  /**
   * 加载当前情绪
   * 流程：调用 api.personality.getCurrentEmotion → 写入 currentEmotion
   * 异常：记录日志，不抛出（保留 currentEmotion=null 状态）
   */
  private async loadCurrentEmotion(agentId: string): Promise<void> {
    try {
      const res = await this.api.personality.getCurrentEmotion(agentId);
      if (res.code === 0 && res.data) {
        this.currentEmotion = res.data;
      } else {
        this.currentEmotion = null;
      }
    } catch (e) {
      this.logger.error(TAG, '加载当前情绪失败', e as Error);
      this.currentEmotion = null;
    }
  }

  /**
   * 加载情绪历史列表
   * 流程：调用 api.personality.listEmotions → 写入 emotions
   * 异常：记录日志并提示用户
   */
  private async loadEmotionList(agentId: string): Promise<void> {
    try {
      const res = await this.api.personality.listEmotions(agentId, { page: 1, size: 50 });
      if (res.code === 0 && res.data) {
        this.emotions = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载情绪列表失败', e as Error);
      this.msg.error('加载情绪列表失败');
    }
  }

  /**
   * 打开新建弹窗
   * 重置表单字段为默认值（type=happy, intensity=0.5, trigger=''）
   */
  private openCreateDialog(): void {
    this.formType = 'happy';
    this.formIntensity = 0.5;
    this.formTrigger = '';
    this.showCreate = true;
  }

  /** 关闭新建弹窗 */
  private closeCreateDialog(): void {
    this.showCreate = false;
  }

  /**
   * 提交新建情绪记录
   * 流程：构造 Emotion payload → 调用 api.personality.createEmotion → 成功后关闭弹窗 + 刷新
   * 异常：记录日志并提示用户
   * 防抖：submitting 状态防止重复提交
   */
  private async submitCreate(): Promise<void> {
    if (this.submitting) return;
    const agentId = this.agentsStore.currentAgentId || '';
    if (!agentId) {
      this.msg.error('未选择 Agent');
      return;
    }
    this.submitting = true;
    try {
      const payload: Partial<Emotion> = {
        agentId,
        type: this.formType,
        intensity: this.formIntensity,
        trigger: this.formTrigger.trim() || undefined,
      };
      const res = await this.api.personality.createEmotion(payload);
      if (res.code === 0) {
        this.msg.success('记录已创建');
        this.closeCreateDialog();
        await this.loadAll();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建情绪记录失败', e as Error);
      this.msg.error('创建情绪记录失败');
    } finally {
      this.submitting = false;
    }
  }

  /**
   * 打开详情弹窗
   * @param emotion 选中的情绪记录
   */
  private openDetailDialog(emotion: Emotion): void {
    this.selectedEmotion = emotion;
    this.showDetail = true;
  }

  /** 关闭详情弹窗 */
  private closeDetailDialog(): void {
    this.showDetail = false;
    this.selectedEmotion = null;
  }

  /**
   * 删除前二次确认（AlertDialog）
   * @param emotion 待删除的情绪记录
   */
  private confirmDelete(emotion: Emotion): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除这条${AgentEmotionViewHelper.getTypeLabel(emotion.type)}情绪记录吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteEmotion(emotion.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.personality.removeEmotion → 成功后刷新列表与当前情绪
   * 异常：记录日志并提示用户
   */
  private async deleteEmotion(emotionId: string): Promise<void> {
    try {
      const res = await this.api.personality.removeEmotion(emotionId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        await this.loadAll();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除情绪记录失败', e as Error);
      this.msg.error('删除情绪记录失败');
    }
  }

  /**
   * 格式化时间（YYYY-MM-DD HH:mm），无效值回退 '未知'
   */
  private formatTime(iso: string): string {
    if (!iso) return '未知';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack() {
      // ========== 主页面 ==========
      Column() {
        // 顶部导航栏：标题"情绪" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '情绪',
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

        if (this.loading) {
          // 加载态
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
          // 当前情绪概览卡（无当前情绪时占位提示）
          this.buildCurrentOverview()

          // 列表区：空态 / 列表
          if (this.emotions.length === 0) {
            Column() {
              Text('暂无情绪记录')
                .fontSize(this.sm.getFontSize('subtitle'))
                .fontColor(this.sm.getColor('text_secondary'))
              GlassButton({
                text: '新建记录',
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
              ForEach(this.emotions, (emotion: Emotion) => {
                ListItem() {
                  this.buildEmotionCard(emotion)
                }
              }, (emotion: Emotion) => emotion.id)
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
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // ========== 详情弹窗 ==========
      if (this.showDetail && this.selectedEmotion !== null) {
        this.buildDetailDialog(this.selectedEmotion)
      }

      // ========== 新建弹窗 ==========
      if (this.showCreate) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 区块构建器
  // ===========================================================================

  /** 当前情绪概览卡：type 徽章 + emoji 大图 + intensity 进度条 + 触发原因 + 创建时间 */
  @Builder
  buildCurrentOverview() {
    GlassCard({ title: '当前情绪' }) {
      Column() {
        if (this.currentEmotion === null) {
          // 无当前情绪占位
          Text('暂无当前情绪')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_disabled'))
            .width('100%')
            .textAlign(TextAlign.Center)
            .padding({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })
        } else {
          // 行1：type 徽章（左）+ 创建时间（右）
          Row() {
            Text(AgentEmotionViewHelper.getTypeLabel(this.currentEmotion!.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .padding({ left: 8, right: 8, top: 2, bottom: 2 })
              .borderRadius(10)
              .backgroundColor(
                this.sm.getColor(AgentEmotionViewHelper.getTypeColor(this.currentEmotion!.type))
              )
            Text(this.formatTime(this.currentEmotion!.createdAt))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .layoutWeight(1)
              .textAlign(TextAlign.End)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // 行2：emoji 大图（居中）
          Text(AgentEmotionViewHelper.getTypeIcon(this.currentEmotion!.type))
            .fontSize(48)
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')
            .textAlign(TextAlign.Center)

          // 行3：intensity 进度条 + 百分比
          Row() {
            Row() {
              Row()
                .width(`${Math.round(this.currentEmotion!.intensity * 100)}%`)
                .height(6)
                .borderRadius(3)
                .backgroundColor(
                  this.sm.getColor(AgentEmotionViewHelper.getTypeColor(this.currentEmotion!.type))
                )
            }
            .width('70%')
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('divider'))
            .alignItems(VerticalAlign.Start)

            Text(AgentEmotionViewHelper.formatIntensity(this.currentEmotion!.intensity))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)

          // 行4：触发原因
          Row() {
            Text('触发：')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(AgentEmotionViewHelper.truncateTrigger(this.currentEmotion!.trigger))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_primary'))
              .layoutWeight(1)
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({
      left: this.sm.getSpacing('md'),
      right: this.sm.getSpacing('md'),
      top: this.sm.getSpacing('sm'),
      bottom: this.sm.getSpacing('sm'),
    })
  }

  /** 单条情绪卡片：type emoji + 徽章 + intensity 进度条 + 触发原因摘要 + 创建时间 + 操作 */
  @Builder
  buildEmotionCard(emotion: Emotion) {
    GlassCard() {
      Column() {
        // 行1：emoji + type 徽章 + 创建时间
        Row() {
          Text(AgentEmotionViewHelper.getTypeIcon(emotion.type))
            .fontSize(this.sm.getFontSize('subtitle'))
          Text(AgentEmotionViewHelper.getTypeLabel(emotion.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(AgentEmotionViewHelper.getTypeColor(emotion.type)))
            .margin({ left: this.sm.getSpacing('sm') })
          Text(this.formatTime(emotion.createdAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 行2：intensity 进度条 + 百分比
        Row() {
          Row() {
            Row()
              .width(`${Math.round(emotion.intensity * 100)}%`)
              .height(4)
              .borderRadius(2)
              .backgroundColor(this.sm.getColor(AgentEmotionViewHelper.getTypeColor(emotion.type)))
          }
          .width(80)
          .height(4)
          .borderRadius(2)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`强度 ${AgentEmotionViewHelper.formatIntensity(emotion.intensity)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 行3：触发原因摘要（截断到 60 字符）
        Text(AgentEmotionViewHelper.truncateTrigger(emotion.trigger))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 行4：操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetailDialog(emotion); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(emotion); }
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
  // 详情弹窗构建器（Stack 条件渲染，不单独建文件）
  // ===========================================================================

  /** 详情弹窗：完整 type、intensity 百分比、trigger、创建时间 */
  @Builder
  buildDetailDialog(emotion: Emotion) {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      GlassCard({ title: '情绪详情' }) {
        Column() {
          // 类型
          Text('类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Text(
            `${AgentEmotionViewHelper.getTypeIcon(emotion.type)} ${AgentEmotionViewHelper.getTypeLabel(emotion.type)}`
          )
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 强度
          Text('强度')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Text(AgentEmotionViewHelper.formatIntensity(emotion.intensity))
            .fontSize(this.sm.getFontSize('body'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(AgentEmotionViewHelper.getTypeColor(emotion.type)))
            .width('100%')
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 触发原因
          Text('触发原因')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Text(emotion.trigger || '—')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 创建时间
          Text('创建时间')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Text(this.formatTime(emotion.createdAt))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            size: 'medium',
            block: true,
            onClick: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('rgba(0, 0, 0, 0.5)')
    .onClick(() => { this.closeDetailDialog(); })
  }

  // ===========================================================================
  // 新建弹窗构建器（Stack 条件渲染，不单独建文件）
  // ===========================================================================

  /** 新建弹窗：type 选择 + intensity slider + trigger 输入 */
  @Builder
  buildCreateDialog() {
    // 遮罩层：点击空白处关闭（提交中时不可关闭）
    Column() {
      // 弹窗主体
      GlassCard({ title: '新建情绪记录' }) {
        Column() {
          // type 选择：横向胶囊列表（7 种情绪类型）
          Text('情绪类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              ForEach(EMOTION_TYPES, (t: string) => {
                Text(`${AgentEmotionViewHelper.getTypeIcon(t)} ${AgentEmotionViewHelper.getTypeLabel(t)}`)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.formType === t
                    ? this.sm.getColor('text_on_primary')
                    : this.sm.getColor('text_primary'))
                  .padding({ left: 10, right: 10, top: 6, bottom: 6 })
                  .borderRadius(16)
                  .backgroundColor(this.formType === t
                    ? this.sm.getColor(AgentEmotionViewHelper.getTypeColor(t))
                    : Color.Transparent)
                  .onClick(() => {
                    // 整体重新赋值以满足 @State 嵌套属性变更触发刷新（标量直接赋值即可）
                    this.formType = t;
                  })
              }, (t: string) => t)
            }
            .padding({ top: 4, bottom: 4 })
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // intensity slider
          Row() {
            Text('强度')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(AgentEmotionViewHelper.formatIntensity(this.formIntensity))
              .fontSize(this.sm.getFontSize('body'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('primary'))
              .layoutWeight(1)
              .textAlign(TextAlign.End)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          Slider({
            value: this.formIntensity,
            min: 0,
            max: 1,
            step: 0.01,
          })
            .width('100%')
            .margin({ top: this.sm.getSpacing('xs') })
            .onChange((v: number) => {
              // Slider onChange 给出的是 step 对齐后的值；直接赋值即可触发刷新
              this.formIntensity = v;
            })

          // trigger 输入
          Text('触发原因（可选）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '例如：收到用户问候',
            value: this.formTrigger,
            type: 'text',
            onChange: (v: string) => { this.formTrigger = v; }
          })
            .width('100%')
            .margin({ top: this.sm.getSpacing('xs') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.closeCreateDialog(); }
            })
              .layoutWeight(1)
            GlassButton({
              text: this.submitting ? '提交中...' : '提交',
              type: 'primary',
              size: 'medium',
              disabled: this.submitting,
              onClick: () => { this.submitCreate(); }
            })
              .layoutWeight(1)
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .backgroundColor('rgba(0, 0, 0, 0.5)')
    .onClick(() => {
      // 提交中时不允许点击遮罩关闭
      if (!this.submitting) {
        this.closeCreateDialog();
      }
    })
  }
}
