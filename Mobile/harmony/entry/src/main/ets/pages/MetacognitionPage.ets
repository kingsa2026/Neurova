/**
 * MetacognitionPage - 元认知页
 *
 * 职责：展示元认知记录列表，按类型筛选、查看详情、新建
 * 设计：
 *   - MetacognitionViewHelper（导出）：纯视图模型，封装 type 颜色映射、type 图标映射、
 *     type 中文标签、confidence 格式化、内容截断；无 UI 运行时依赖，可独立单元测试；
 *   - MetacognitionPage（@Component）：Column [TopNavMenu(标题"元认知"+返回+新建)]
 *     + [type 筛选 Tab（全部/监控/控制/评估）] + [加载态/空态/列表]；
 *     列表项 GlassCard 含 type 徽章、内容摘要、confidence 进度条、关联 thoughtId、
 *     创建时间、操作按钮（查看/删除）；详情通过 Stack 条件渲染弹窗展示完整 content、
 *     confidence 百分比、thoughtId；删除走 AlertDialog 二次确认；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.cognition，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（cognition.listMetacognitions/getMetacognition/
 *     createMetacognition/removeMetacognition）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MetacognitionRecord
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.cognition.listMetacognitions 加载列表；
 *   type 筛选 Tab 切换 → 本地 filterByType 过滤；
 *   新建按钮 → 当前提示"功能开发中"（M5 接入完整表单流程）；
 *   查看按钮 → 弹出 Stack 弹窗展示完整 content + confidence + thoughtId；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.cognition.removeMetacognition → 刷新列表
 *
 * TDD：MetacognitionViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 MetacognitionPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MetacognitionRecord } from '../libs/types';

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
  static getTypeColor(type: MetacognitionRecord['type']): string {
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
  static getTypeIcon(type: MetacognitionRecord['type']): string {
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
  static getTypeLabel(type: MetacognitionRecord['type']): string {
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

/** type 筛选项：value 为 'all' 或具体 MetacognitionRecord['type'] */
interface TypeFilterOption {
  value: string;
  label: string;
}

/** type 筛选 Tab 列表（顺序即展示顺序） */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'monitoring', label: '监控' },
  { value: 'control', label: '控制' },
  { value: 'evaluation', label: '评估' },
];

@Component
export struct MetacognitionPage {
  // 元认知记录列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State records: MetacognitionRecord[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的 type 筛选值：'all' 或具体 type
  @State activeType: string = 'all';
  // 详情弹窗控制：showDetail 控制显隐，detailRecord 持有当前查看的记录
  @State showDetail: boolean = false;
  @State detailRecord: MetacognitionRecord | null = null;

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
      const res = await this.api.cognition.listMetacognitions(agentId);
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
  private getFilteredList(): MetacognitionRecord[] {
    if (this.activeType === 'all') {
      return this.records;
    }
    return this.records.filter((r: MetacognitionRecord) => r.type === this.activeType);
  }

  /**
   * 新建元认知记录（M5 接入完整表单流程，当前提示"功能开发中"）
   */
  private handleCreate(): void {
    this.msg.info('功能开发中');
  }

  /**
   * 打开详情弹窗
   */
  private openDetail(record: MetacognitionRecord): void {
    this.detailRecord = record;
    this.showDetail = true;
  }

  /** 关闭详情弹窗 */
  private closeDetail(): void {
    this.showDetail = false;
    this.detailRecord = null;
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(record: MetacognitionRecord): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除这条${MetacognitionViewHelper.getTypeLabel(record.type)}记录吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteRecord(record.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.cognition.removeMetacognition → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteRecord(recordId: string): Promise<void> {
    try {
      const res = await this.api.cognition.removeMetacognition(recordId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadRecords();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除元认知失败', e as Error);
      this.msg.error('删除元认知失败');
    }
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
            size: 'small',
            onClick: () => { this.handleCreate(); }
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
            ForEach(this.getFilteredList(), (record: MetacognitionRecord) => {
              ListItem() {
                this.buildRecordCard(record)
              }
            }, (record: MetacognitionRecord) => record.id)
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
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 元认知卡片构建器
  // ===========================================================================

  /** 单条元认知卡片：type 徽章 + 内容摘要 + confidence 进度条 + thoughtId + 创建时间 + 操作按钮 */
  @Builder
  buildRecordCard(record: MetacognitionRecord) {
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
          .alignItems(VerticalAlign.Start)

          Text(`置信度 ${MetacognitionViewHelper.formatConfidence(record.confidence)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 底部行：thoughtId + 创建时间
        Row() {
          Text(`关联: ${record.thoughtId}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)
          Text(this.formatTime(record.createdAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 8 })
            .maxLines(1)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '查看',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetail(record); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(record); }
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
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 覆盖层，内嵌实现，不创建单独 CustomDialog 文件）
  // ===========================================================================

  /** 详情弹窗：完整 content + confidence 百分比 + thoughtId */
  @Builder
  buildDetailDialog(record: MetacognitionRecord) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', padding: 20 }) {
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
          .alignItems(HorizontalAlign.Start)
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
            .alignItems(VerticalAlign.Start)

            Text(MetacognitionViewHelper.formatConfidence(record.confidence))
              .fontSize(this.sm.getFontSize('body'))
              .fontWeight(FontWeight.Medium)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 12 })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)

          // 关联 thoughtId
          Text(`关联 Thought: ${record.thoughtId}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')

          // 创建时间
          Text(`创建时间: ${this.formatTime(record.createdAt)}`)
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
            size: 'medium',
            block: true,
            onClick: () => { this.closeDetail(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .height('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }
}
