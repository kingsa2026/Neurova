/**
 * MetacognitionPage - 元认知页（metacognition_api 真实契约版）
 *
 * 数据：GET /v1/metacognition/{agent_id}/metacognition?type=&page=&size=
 *       （thought 条目投影：id/kind/type/content/context/confidence/
 *        metadata/created_at）
 * 操作：POST /v1/metacognition/{agent_id}/metacognition
 *       （MetacognitionRecordCreate：type/content/context/confidence）。
 * 契约说明：后端无删除端点，本页不提供删除；旧 thoughtId 关联字段后端不存在，
 *       展示位改为真实字段 context（上下文）。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MetacognitionDto } from '../libs/api/modules/CognitionApi';

/** 日志标签 */
const TAG = 'MetacognitionPage';

// ===========================================================================
// MetacognitionViewHelper - 元认知视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MetacognitionViewHelper {
  /**
   * 获取元认知 type 对应的颜色 token 名
   * 映射：monitoring→info，control→primary，evaluation→warning
   * @param type 元认知类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: string): string {
    if (type === 'monitoring') return 'info';
    if (type === 'control') return 'primary';
    if (type === 'evaluation') return 'warning';
    return 'text_disabled';
  }

  /**
   * 获取元认知 type 对应的图标 emoji
   * 映射：monitoring→👁️，control→🎛️，evaluation→📊
   * @param type 元认知类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: string): string {
    if (type === 'monitoring') return '👁️';
    if (type === 'control') return '🎛️';
    if (type === 'evaluation') return '📊';
    return '📄';
  }

  /**
   * 获取元认知 type 的中文标签
   * 映射：monitoring→监控，control→控制，evaluation→评估
   * @param type 元认知类型
   * @return 中文标签字符串
   */
  static getTypeLabel(type: string): string {
    if (type === 'monitoring') return '监控';
    if (type === 'control') return '控制';
    if (type === 'evaluation') return '评估';
    return '未知';
  }

  /**
   * 格式化 confidence 为百分比字符串
   * @param value 置信度 0-1
   * @return 百分比字符串，如 0.5 → "50%"，1 → "100%"
   */
  static formatConfidence(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  /**
   * 截断内容，超长时截取 maxLen 字符并追加省略号
   * @param content 原始内容
   * @param maxLen 最大字符数，默认 120
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateContent(content: string, maxLen: number = 120): string {
    if (content.length <= maxLen) return content;
    return content.substring(0, maxLen) + '...';
  }
}

// ===========================================================================
// type 筛选 Tab 配置
// ===========================================================================

/** type 筛选项：value 为 'all' 或具体 type 词汇 */
interface TypeFilterOption {
  value: string;
  label: string;
}

/** type 筛选 Tab 列表（顺序即展示顺序；词汇与后端 MetacognitionRecordCreate 默认体系同源） */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'monitoring', label: '监控' },
  { value: 'control', label: '控制' },
  { value: 'evaluation', label: '评估' },
];

/** 新建可选类型（MetacognitionRecordCreate.type 词域） */
const CREATE_TYPES: string[] = ['monitoring', 'control', 'evaluation'];

/** 新建表单数据（ArkTS 禁匿名对象类型，独立声明） */
interface MetacognitionFormData {
  type: string;
  content: string;
  context: string;
}

@Component
export struct MetacognitionPage {
  // 元认知记录列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State records: MetacognitionDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的 type 筛选值：'all' 或具体 type
  @State activeType: string = 'all';
  // 详情弹窗控制：showDetail 控制显隐，detailRecord 持有当前查看的记录
  @State showDetail: boolean = false;
  @State detailRecord: MetacognitionDto | null = null;
  // 新建弹窗显隐
  @State showCreate: boolean = false;
  // 新建表单数据
  @State formData: MetacognitionFormData = {
    type: 'monitoring',
    content: '',
    context: '',
  };
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
    this.loadRecords();
  }

  /**
   * 加载元认知记录列表
   * 流程：取 currentAgentId → 调用 api.cognition.listMetacognitions → 写入 records
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadRecords(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.listMetacognitions(agentId, 1, 50);
      if (res.code === 0 && res.data) {
        this.records = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载元认知失败', e as Error);
      this.msg.error('加载元认知列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换 type 筛选 Tab（本地过滤）
   */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /**
   * 获取经当前 type 筛选后的列表
   * 规则：activeType === 'all' 返回全量；否则按 type 字段过滤
   */
  private getFilteredList(): MetacognitionDto[] {
    if (this.activeType === 'all') {
      return this.records;
    }
    return this.records.filter((r: MetacognitionDto) => r.type === this.activeType);
  }

  /**
   * 打开新建弹窗（重置表单）
   */
  private openCreateDialog(): void {
    this.formData = {
      type: 'monitoring',
      content: '',
      context: '',
    };
    this.showCreate = true;
  }

  /** 关闭新建弹窗 */
  private closeCreateDialog(): void {
    this.showCreate = false;
  }

  /**
   * 提交新建（POST /metacognition/{agent_id}/metacognition，MetacognitionRecordCreate 契约）
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.content.trim()) {
      this.msg.warning('内容不能为空');
      return;
    }
    this.submitting = true;
    try {
      const payload: Record<string, Object> = {
        'type': this.formData.type,
        'content': this.formData.content.trim(),
        'context': this.formData.context.trim(),
        'confidence': 0.5,
      };
      const res = await this.api.cognition.createMetacognition(this.agentsStore.currentAgentId || '', payload);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.closeCreateDialog();
        this.loadRecords();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建元认知失败', e as Error);
      this.msg.error('创建元认知失败');
    } finally {
      this.submitting = false;
    }
  }

  /**
   * 打开详情弹窗
   */
  private openDetail(record: MetacognitionDto): void {
    this.detailRecord = record;
    this.showDetail = true;
  }

  /** 关闭详情弹窗 */
  private closeDetail(): void {
    this.showDetail = false;
    this.detailRecord = null;
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(timeStr?: string): string {
    if (!timeStr) return '未知';
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"元认知" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '元认知',
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

        // type 筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(TYPE_FILTERS, (opt: TypeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeType === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeType === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchType(opt.value); })
            }, (opt: TypeFilterOption) => opt.value)
          }
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('sm'),
          })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')

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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无元认知记录')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (record: MetacognitionDto) => {
              ListItem() {
                this.buildRecordCard(record)
              }
            }, (record: MetacognitionDto) => `${record.id}`)
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

      // 详情弹窗：showDetail 为 true 时覆盖在主体之上
      if (this.showDetail && this.detailRecord) {
        this.buildDetailDialog(this.detailRecord)
      }

      // 新建弹窗（Stack 条件渲染）
      if (this.showCreate) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 元认知卡片构建器
  // ===========================================================================

  /** 单条元认知卡片：type 徽章 + 内容摘要 + confidence 进度条 + 上下文 + 创建时间 + 查看 */
  @Builder
  buildRecordCard(record: MetacognitionDto) {
    Column() {
    GlassCard() {
      Column() {
        // type 徽章行：图标 + 标签
        Row() {
          Text(MetacognitionViewHelper.getTypeIcon(record.type))
            .fontSize(16)
          Text(MetacognitionViewHelper.getTypeLabel(record.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(MetacognitionViewHelper.getTypeColor(record.type)))
            .margin({ left: 6 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 内容摘要（截断到 120 字符，最多 3 行）
        Text(MetacognitionViewHelper.truncateContent(record.content))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // confidence 进度条 + 百分比
        Row() {
          Row() {
            Row()
              .width(`${Math.round(record.confidence * 100)}%`)
              .height(4)
              .borderRadius(2)
              .backgroundColor(this.sm.getColor('primary'))
          }
          .width(80)
          .height(4)
          .borderRadius(2)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Top)

          Text(`置信度 ${MetacognitionViewHelper.formatConfidence(record.confidence)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 底部行：上下文 + 创建时间
        Row() {
          Text(record.context.length > 0 ? `上下文: ${record.context}` : '无上下文')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
          Text(this.formatTime(record.created_at))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 8 })
            .maxLines(1)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看（后端无删除端点，不提供删除）
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.openDetail(record); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 覆盖层，内嵌实现，不创建单独 CustomDialog 文件）
  // ===========================================================================

  /** 详情弹窗：完整 content + confidence 百分比 + 上下文 + 创建时间 */
  @Builder
  buildDetailDialog(record: MetacognitionDto) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          // 标题行：图标 + type 标签
          Row() {
            Text(MetacognitionViewHelper.getTypeIcon(record.type))
              .fontSize(20)
            Text(MetacognitionViewHelper.getTypeLabel(record.type))
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 6 })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // type 徽章（颜色映射）
          Row() {
            Text(MetacognitionViewHelper.getTypeLabel(record.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .padding({ left: 8, right: 8, top: 2, bottom: 2 })
              .borderRadius(10)
              .backgroundColor(this.sm.getColor(MetacognitionViewHelper.getTypeColor(record.type)))
          }
          .width('100%')
          .justifyContent(FlexAlign.Start)
          .margin({ top: this.sm.getSpacing('sm') })

          // confidence 进度条 + 百分比
          Row() {
            Row() {
              Row()
                .width(`${Math.round(record.confidence * 100)}%`)
                .height(6)
                .borderRadius(3)
                .backgroundColor(this.sm.getColor('primary'))
            }
            .width(120)
            .height(6)
            .borderRadius(3)
            .backgroundColor(this.sm.getColor('divider'))
            .alignItems(VerticalAlign.Top)

            Text(MetacognitionViewHelper.formatConfidence(record.confidence))
              .fontSize(this.sm.getFontSize('body'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 12 })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)

          // 上下文
          Text(`上下文: ${record.context.length > 0 ? record.context : '无'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')

          // 创建时间
          Text(`创建时间: ${this.formatTime(record.created_at)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: 4 })
            .width('100%')

          // 完整内容（可滚动）
          Text('内容')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('md') })
          Scroll() {
            Text(record.content)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
          }
          .layoutWeight(1)
          .width('100%')
          .margin({ top: 8 })
          .scrollBar(BarState.Off)

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            btnSize: 'medium',
            block: true,
            onTap: () => { this.closeDetail(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .height('100%')
        .alignItems(HorizontalAlign.Start)
      }
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 新建弹窗构建器（MetacognitionRecordCreate 契约字段）
  // ===========================================================================

  /** 新建弹窗：type 三选 chips + content 文本域 + context 输入 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeCreateDialog(); })

      // 面板层：居中展示
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          Text('新建元认知')
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 类型选择
          Text('类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('md') })
          Row({ space: 8 }) {
            ForEach(CREATE_TYPES, (t: string) => {
              Text(MetacognitionViewHelper.getTypeLabel(t))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.formData.type === t
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.formData.type === t
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 10, right: 10, top: 4, bottom: 4 })
                .borderRadius(12)
                .onClick(() => {
                  this.formData = { type: t, content: this.formData.content, context: this.formData.context };
                })
            }, (t: string) => t)
          }
          .width('100%')
          .margin({ top: 4 })

          // 内容
          Text('内容')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          TextArea({
            placeholder: '记录这次元认知的内容...',
            text: this.formData.content,
          })
            .width('100%')
            .height(110)
            .fontSize(this.sm.getFontSize('body'))
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor('surface'))
            .onChange((v: string) => {
              this.formData = { type: this.formData.type, content: v, context: this.formData.context };
            })

          // 上下文
          Text('上下文（选填）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '触发这次元认知的场景',
            value: this.formData.context,
            type: 'text',
            onChange: (v: string) => {
              this.formData = { type: this.formData.type, content: this.formData.content, context: v };
            },
          })

          // 底部按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              btnSize: 'medium',
              onTap: () => { this.closeCreateDialog(); }
            })
            GlassButton({
              text: this.submitting ? '提交中...' : '创建',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.submitCreate(); }
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
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
