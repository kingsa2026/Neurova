/**
 * CollaborationHistoryPage - 协作历史页
 *
 * 职责：展示协作历史记录，按 collaborationId 筛选，按 action 过滤，
 *   时间倒序显示，点击项展开 before/after 对比
 * 设计：
 *   - CollaborationHistoryViewHelper（导出）：纯视图模型，封装动作颜色映射、
 *     动作图标、动作文案、时间戳格式化、元数据格式化、备注截断；
 *     无 UI 运行时依赖，可独立单元测试；
 *   - CollaborationHistoryPage（@Component）：Column [TopNavMenu(标题"协作历史"+返回)] +
 *     [action 筛选 Tab（全部/create/update/complete/archive）] + [加载态/空态/列表]；
 *     列表项 GlassCard：action 徽章、actor、时间戳、备注摘要、展开按钮；
 *     点击项 → AlertDialog 展示 before/after 对比；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 collaboration 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M6 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：CollaborationHistory、Metadata
 *
 * 用法：
 *   由 Router.push(RouteNames.COLLABORATION_HISTORY) 跳转进入；
 *   aboutToAppear 加载 mock 历史列表（TODO M6 接入 api.collaboration.history.list）；
 *   action 筛选 Tab 切换 → 本地 filterByAction 过滤；
 *   点击项 → AlertDialog 展示 before/after 元数据对比。
 *
 * TDD：CollaborationHistoryViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 CollaborationHistoryPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { CollaborationHistory, Metadata } from '../libs/types';

/** 日志标签 */
const TAG = 'CollaborationHistoryPage';

/** 备注截断默认最大长度 */
const DEFAULT_NOTE_MAX_LEN = 50;

// ===========================================================================
// CollaborationHistoryViewHelper - 协作历史视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationHistoryViewHelper {
  /**
   * 获取动作对应的颜色 token 名
   * 映射：create→success，update→info，complete→success，archive→warning
   * @param action 动作字符串
   * @return StyleManager 颜色 token 名
   */
  static getActionColor(action: string): string {
    if (action === 'create') return 'success';
    if (action === 'update') return 'info';
    if (action === 'complete') return 'success';
    if (action === 'archive') return 'warning';
    // 未覆盖的动作抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getActionColor 未实现: ${action}`);
  }

  /**
   * 获取动作对应的图标 emoji
   * 映射：create→✨，update→✏️，complete→✅，archive→📦
   * @param action 动作字符串
   * @return emoji 字符串
   */
  static getActionIcon(action: string): string {
    if (action === 'create') return '✨';
    if (action === 'update') return '✏️';
    if (action === 'complete') return '✅';
    if (action === 'archive') return '📦';
    throw new Error(`getActionIcon 未实现: ${action}`);
  }

  /**
   * 获取动作对应的中文标签
   * 映射：create→创建，update→更新，complete→完成，archive→归档
   * @param action 动作字符串
   * @return 中文文案
   */
  static getActionLabel(action: string): string {
    if (action === 'create') return '创建';
    if (action === 'update') return '更新';
    if (action === 'complete') return '完成';
    if (action === 'archive') return '归档';
    throw new Error(`getActionLabel 未实现: ${action}`);
  }

  /**
   * 格式化时间戳为 "YYYY-MM-DD HH:mm" 展示字符串
   * 规则：无效时间 → "未知"；有效 → 本地时间 YYYY-MM-DD HH:mm
   * @param timestamp ISO 时间字符串
   * @return 格式化后的时间字符串
   */
  static formatTimestamp(timestamp: string): string {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  /**
   * 格式化元数据为展示字符串
   * 规则：空（undefined 或空对象）→ "无变更"；非空 → JSON.stringify
   * @param meta 元数据对象（可选）
   * @return 元数据展示字符串
   */
  static formatMetadata(meta?: Metadata): string {
    if (!meta || Object.keys(meta).length === 0) return '无变更';
    return JSON.stringify(meta);
  }

  /**
   * 截断备注文本，超长时截取 maxLen 字符并追加省略号
   * @param note 原始备注
   * @param maxLen 最大字符数
   * @return 截断后的备注；未超长则原样返回
   */
  static truncateNote(note: string, maxLen: number): string {
    if (note.length <= maxLen) return note;
    return note.substring(0, maxLen) + '...';
  }
}

/** 动作筛选 Tab 配置 */
interface ActionFilterOption {
  value: string;     // 'all' 或具体动作
  label: string;
}

/** 动作筛选 Tab 列表 */
const ACTION_FILTERS: ActionFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'create', label: '创建' },
  { value: 'update', label: '更新' },
  { value: 'complete', label: '完成' },
  { value: 'archive', label: '归档' },
];

/**
 * Mock 协作历史数据
 * TODO M6 阶段：替换为 api.collaboration.history.list() 真实 API
 */
const MOCK_HISTORY: CollaborationHistory[] = [
  {
    id: 'hist_1',
    collaborationId: 'collab_1',
    action: 'create',
    actor: 'user_1',
    after: { name: '协作任务 A', status: 'pending' },
    timestamp: '2025-03-01T10:00:00Z',
    note: '创建协作任务',
  },
  {
    id: 'hist_2',
    collaborationId: 'collab_1',
    action: 'update',
    actor: 'agent_1',
    before: { status: 'pending' },
    after: { status: 'in_progress' },
    timestamp: '2025-03-02T14:30:00Z',
    note: '状态更新为进行中',
  },
  {
    id: 'hist_3',
    collaborationId: 'collab_2',
    action: 'complete',
    actor: 'user_2',
    before: { status: 'in_progress' },
    after: { status: 'done' },
    timestamp: '2025-03-03T09:15:00Z',
  },
  {
    id: 'hist_4',
    collaborationId: 'collab_3',
    action: 'archive',
    actor: 'user_1',
    before: { status: 'done' },
    after: { status: 'archived' },
    timestamp: '2025-03-04T16:45:00Z',
    note: '历史项目归档',
  },
];

@Component
export struct CollaborationHistoryPage {
  // 历史记录列表
  @State history: CollaborationHistory[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的动作筛选值
  @State activeAction: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadHistory();
  }

  /**
   * 加载历史记录
   * TODO M6 阶段：替换为真实 API（api.collaboration.history.list）
   * 当前使用 mock 静态数据，按时间倒序排序
   */
  private async loadHistory(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.collaboration.history.list();
      // if (res.code === 0 && res.data) { this.history = res.data.items; }
      this.history = MOCK_HISTORY.slice().sort((a: CollaborationHistory, b: CollaborationHistory) => {
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      });
    } catch (e) {
      this.logger.error(TAG, '加载历史失败', e as Error);
      this.msg.error('加载协作历史失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换动作筛选 */
  private switchAction(value: string): void {
    this.activeAction = value;
  }

  /**
   * 获取经动作筛选后的列表
   * 规则：activeAction === 'all' 返回全量；否则按 action 字段过滤
   */
  private getFilteredHistory(): CollaborationHistory[] {
    if (this.activeAction === 'all') {
      return this.history;
    }
    return this.history.filter((h: CollaborationHistory) => h.action === this.activeAction);
  }

  /**
   * 查看历史详情
   * AlertDialog 展示 before/after 对比
   */
  private showDetail(h: CollaborationHistory): void {
    AlertDialog.show({
      title: `${CollaborationHistoryViewHelper.getActionLabel(h.action)} - ${h.actor}`,
      message:
        `动作：${CollaborationHistoryViewHelper.getActionLabel(h.action)}\n\n` +
        `执行者：${h.actor}\n\n` +
        `时间：${CollaborationHistoryViewHelper.formatTimestamp(h.timestamp)}\n\n` +
        `变更前：\n${CollaborationHistoryViewHelper.formatMetadata(h.before)}\n\n` +
        `变更后：\n${CollaborationHistoryViewHelper.formatMetadata(h.after)}\n\n` +
        `备注：${h.note ?? '无'}`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  build() {
    Column() {
      // 顶部导航栏：标题"协作历史" + 返回
      TopNavMenu({
        title: '协作历史',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 动作筛选 Tab
      Scroll() {
        Row({ space: 8 }) {
          ForEach(ACTION_FILTERS, (opt: ActionFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeAction === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeAction === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchAction(opt.value); })
          }, (opt: ActionFilterOption) => opt.value)
        }
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .padding({ top: 4, bottom: 4 })

      // 主体内容：加载态 / 空态 / 列表 三选一
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
      } else if (this.getFilteredHistory().length === 0) {
        Column() {
          Text('暂无历史记录')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.getFilteredHistory(), (h: CollaborationHistory) => {
            ListItem() {
              this.buildHistoryCard(h)
            }
          }, (h: CollaborationHistory) => h.id)
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
  }

  // ===========================================================================
  // 历史卡片构建器
  // ===========================================================================

  /** 单个历史卡片：动作徽章 + 执行者 + 时间戳 + 备注摘要 + 操作按钮 */
  @Builder
  buildHistoryCard(h: CollaborationHistory) {
    GlassCard() {
      Column() {
        // 顶部行：动作图标 + 动作徽章 + 执行者
        Row() {
          Text(CollaborationHistoryViewHelper.getActionIcon(h.action))
            .fontSize(20)
          Text(CollaborationHistoryViewHelper.getActionLabel(h.action))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(CollaborationHistoryViewHelper.getActionColor(h.action)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(h.actor)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 时间戳
        Text(CollaborationHistoryViewHelper.formatTimestamp(h.timestamp))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 备注摘要（默认 50 字符截断，无备注显示 "无备注"）
        Text(h.note
          ? CollaborationHistoryViewHelper.truncateNote(h.note, DEFAULT_NOTE_MAX_LEN)
          : '无备注')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 操作按钮：查看详情（右对齐）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(h); }
          })
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
}
