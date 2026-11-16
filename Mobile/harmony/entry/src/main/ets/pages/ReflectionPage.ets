/**
 * ReflectionPage - 反思记录页（growth.py /reflection 真实契约版）
 *
 * 数据：GET /v1/growth/reflection?agent_id=&limit=
 *       （_reflection_entry_to_item 投影：log_id/agent_id/timestamp/
 *        reflection_type/content/insights/confidence/related_memories/status）
 * 操作：POST /v1/growth/reflection（ReflectionLogCreate：reflection_type/content/
 *       insights/confidence/related_memories）。
 * 契约说明：后端无删除端点，本页不提供删除；旧"改进项"字段后端不存在，
 *       展示位改为真实字段 related_memories（相关记忆）。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ReflectionDto, ReflectionCreateRequest } from '../libs/api/modules/CognitionApi';

/** 日志标签 */
const TAG = 'ReflectionPage';

/** 默认内容截断长度 */
const DEFAULT_CONTENT_MAX_LEN = 150;

/** 星期中文映射表（getDay 0=周日） */
const WEEKDAY_LABELS: string[] = ['日', '一', '二', '三', '四', '五', '六'];

/** 反思类型选项（ReflectionType 枚举词汇，与后端同源） */
const REFLECTION_TYPES: string[] = ['performance', 'error', 'improvement', 'pattern', 'insight', 'strategy'];

/** 类型筛选配置 */
interface TypeOption {
  value: string;
  label: string;
}

/** 反思类型 → 中文标签 */
const TYPE_LABELS: TypeOption[] = [
  { value: 'performance', label: '性能反思' },
  { value: 'error', label: '错误反思' },
  { value: 'improvement', label: '改进反思' },
  { value: 'pattern', label: '模式反思' },
  { value: 'insight', label: '洞察反思' },
  { value: 'strategy', label: '策略反思' },
  { value: 'general', label: '通用反思' },
];

// ===========================================================================
// ReflectionViewHelper - 反思视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
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
   * 获取相关记忆数文案
   * @param count 相关记忆数量
   * @return 0 → "无关联"，n → "关联 n 条"
   */
  static getRelatedCount(count: number): string {
    if (count <= 0) return '无关联';
    return `关联 ${count} 条`;
  }

  /**
   * 反思类型 → 中文标签（未知词原样返回，不臆造）
   */
  static reflectionTypeLabel(type: string): string {
    for (const opt of TYPE_LABELS) {
      if (opt.value === type) {
        return opt.label;
      }
    }
    return type;
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
   * 格式化相对时间（ISO 字符串入参）
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

  /**
   * 格式化秒级时间戳（后端 timestamp 为 float 秒）→ 复用 ISO 相对时间逻辑
   * @param ts 秒级时间戳；非正数视为未知
   */
  static formatTimestamp(ts: number): string {
    if (!ts || ts <= 0) return '未知';
    return ReflectionViewHelper.formatRelativeTime(new Date(ts * 1000).toISOString());
  }
}

// ===========================================================================
// ReflectionPage - 反思记录页组件
//
// 设计：Stack[Column[TopNavMenu + 主体] + 详情弹窗 + 新建弹窗]；
//       数据流：aboutToAppear → api.cognition.listReflections → 按 timestamp 倒序 → 渲染；
//       新建完成后自动刷新列表；后端无删除端点，不提供删除
// ===========================================================================

/** 新建表单数据（ArkTS 禁匿名对象类型，独立声明） */
interface ReflectionFormData {
  reflectionType: string;
  content: string;
  insightsText: string;
}

@Component
export struct ReflectionPage {
  // 反思列表（由 API 加载，按 timestamp 倒序）
  @State reflections: ReflectionDto[] = [];
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 详情弹窗可见性
  @State showDetail: boolean = false;
  // 新建弹窗可见性
  @State showCreate: boolean = false;
  // 当前选中的反思（详情弹窗使用）
  @State selectedReflection: ReflectionDto | null = null;
  // 新建表单数据（嵌套对象，整体重新赋值）
  @State formData: ReflectionFormData = {
    reflectionType: 'performance',
    content: '',
    insightsText: '',
  };
  // 相关记忆输入（逗号分隔，独立 @State 便于 GlassInput 受控）
  @State relatedMemoriesText: string = '';
  // 提交中态
  @State submitting: boolean = false;

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
   * 流程：取 currentAgentId → 调用 api.cognition.listReflections → 按 timestamp 倒序
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadReflections(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.listReflections(agentId, 50);
      if (res.code === 0 && res.data) {
        this.reflections = this.sortByTimestampDesc(res.data);
      }
    } catch (e) {
      this.logger.error(TAG, '加载反思列表失败', e as Error);
      this.msg.error('加载反思列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 按 timestamp 倒序排序（最新的在前）
   */
  private sortByTimestampDesc(items: ReflectionDto[]): ReflectionDto[] {
    return items.slice().sort((a, b) => b.timestamp - a.timestamp);
  }

  /**
   * 打开新建弹窗
   * 重置表单为初始空值
   */
  private openCreateDialog(): void {
    this.formData = {
      reflectionType: 'performance',
      content: '',
      insightsText: '',
    };
    this.relatedMemoriesText = '';
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
   * 流程：组装 ReflectionLogCreate → api.cognition.createReflection → 成功后关闭弹窗 + 刷新
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    const content = this.formData.content.trim();
    if (!content) {
      this.msg.warning('反思内容不能为空');
      return;
    }
    this.submitting = true;
    const insights = this.splitLines(this.formData.insightsText);
    const relatedMemories = this.splitCommaSeparated(this.relatedMemoriesText);
    try {
      const payload: ReflectionCreateRequest = {
        reflection_type: this.formData.reflectionType,
        content: content,
        insights: insights,
        confidence: 0.5,
        related_memories: relatedMemories,
      };
      const res = await this.api.cognition.createReflection(this.agentsStore.currentAgentId || '', payload);
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
    } finally {
      this.submitting = false;
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
   * 将逗号分隔文本拆分为非空字符串数组（自动 trim，过滤空段）
   */
  private splitCommaSeparated(text: string): string[] {
    if (!text) return [];
    return text
      .split(',')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  /**
   * 打开详情弹窗
   */
  private openDetailDialog(reflection: ReflectionDto): void {
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
            btnSize: 'small',
            onTap: () => { this.openCreateDialog(); }
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
              btnSize: 'medium',
              onTap: () => { this.openCreateDialog(); }
            })
              .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.reflections, (reflection: ReflectionDto) => {
              ListItem() {
                this.buildReflectionCard(reflection)
              }
            }, (reflection: ReflectionDto) => reflection.log_id)
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

  /** 单条反思卡片：类型 + 内容摘要 + 洞察数 + 关联数 + 时间 + 查看 */
  @Builder
  buildReflectionCard(reflection: ReflectionDto) {
    Column() {
    GlassCard() {
      Column() {
        // 类型徽章 + 状态
        Row() {
          Text(ReflectionViewHelper.reflectionTypeLabel(reflection.reflection_type))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(reflection.status)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor('primary'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 内容摘要（截断到 150 字符，最多 3 行）
        Text(ReflectionViewHelper.truncateContent(reflection.content))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 底部行：洞察数 + 关联数 + 时间
        Row() {
          Text(ReflectionViewHelper.getInsightCount(reflection.insights.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('info'))

          Text(ReflectionViewHelper.getRelatedCount(reflection.related_memories.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('success'))
            .margin({ left: this.sm.getSpacing('sm') })

          Text(ReflectionViewHelper.formatTimestamp(reflection.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮（右对齐）：后端无删除端点，仅保留查看
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.openDetailDialog(reflection); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 详情弹窗：类型、内容、洞察列表（bullets）、相关记忆列表（bullets）、时间 */
  @Builder
  buildDetailDialog(reflection: ReflectionDto) {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      Column() {
      GlassCard({ title: '反思详情' }) {
        Scroll() {
          Column() {
            // 反思类型
            Text('反思类型')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(ReflectionViewHelper.reflectionTypeLabel(reflection.reflection_type))
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

            // 相关记忆列表（bullets）
            Text(`相关记忆（${reflection.related_memories.length}）`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            if (reflection.related_memories.length === 0) {
              Text('无关联')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .width('100%')
                .margin({ top: 4 })
            } else {
              Column() {
                ForEach(reflection.related_memories, (memory: string, index: number) => {
                  Text(`• ${memory}`)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_primary'))
                    .width('100%')
                    .margin({ top: 2 })
                }, (memory: string, index: number) => `${index}-${memory}`)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
              .margin({ top: 4 })
            }

            // 创建时间
            Text(`创建时间：${ReflectionViewHelper.formatTimestamp(reflection.timestamp)}`)
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
            btnSize: 'medium',
            onTap: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
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

  /** 新建弹窗：类型选择（ReflectionType 六词）、content 文本域、insights 多行 */
  @Builder
  buildCreateDialog() {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      Column() {
      GlassCard({ title: '新建反思' }) {
        Scroll() {
          Column() {
            // 反思类型选择
            Text('反思类型')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Scroll() {
              Row({ space: 8 }) {
                ForEach(REFLECTION_TYPES, (t: string) => {
                  Text(ReflectionViewHelper.reflectionTypeLabel(t))
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.formData.reflectionType === t
                      ? this.sm.getColor('text_on_primary')
                      : this.sm.getColor('text_secondary'))
                    .backgroundColor(this.formData.reflectionType === t
                      ? this.sm.getColor('primary')
                      : this.sm.getColor('surface'))
                    .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                    .borderRadius(12)
                    .onClick(() => {
                      this.formData = { reflectionType: t, content: this.formData.content, insightsText: this.formData.insightsText };
                    })
                }, (t: string) => t)
              }
              .padding({ top: 4, bottom: 4 })
            }
            .scrollable(ScrollDirection.Horizontal)
            .scrollBar(BarState.Off)
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
                this.formData = { reflectionType: this.formData.reflectionType, content: v, insightsText: this.formData.insightsText };
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
                this.formData = { reflectionType: this.formData.reflectionType, content: this.formData.content, insightsText: v };
              })

            // 相关记忆输入（多行，每行一条；ReflectionLogCreate.related_memories）
            Text('相关记忆（每行一条，选填）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('success'))
              .width('100%')
            GlassInput({
              placeholder: '关联的记忆 ID，逗号分隔',
              value: this.relatedMemoriesText,
              onChange: (v: string) => {
                this.relatedMemoriesText = v;
              }
            })
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
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
            btnSize: 'medium',
            onTap: () => { this.closeCreateDialog(); }
          })
          GlassButton({
            text: this.submitting ? '提交中...' : '提交',
            type: 'primary',
            btnSize: 'medium',
            onTap: () => { this.submitCreate(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
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
