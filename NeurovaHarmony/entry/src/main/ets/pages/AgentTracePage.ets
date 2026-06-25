/**
 * AgentTracePage - 追踪条目页
 *
 * 职责：展示 Trace 追踪日志列表，按 level 和 source（event 字段）筛选，支持删除
 * 设计：
 *   - AgentTraceViewHelper（导出）：纯视图模型，封装 level 颜色映射、level 图标映射、
 *     level 中文标签、payload 格式化、duration 格式化、timestamp 格式化；
 *     无 UI 运行时依赖，可独立单元测试；
 *   - AgentTracePage（@Component）：Column [TopNavMenu(标题"追踪条目"+返回)]
 *     + [level 筛选 Tab（全部/debug/info/warn/error）]
 *     + [source 筛选 Tab（全部 + 动态从已加载列表的 distinct event 生成）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含 level 徽章、event、timestamp、
 *     durationMs、payload 摘要、操作（删除）；
 *     删除走 AlertDialog 二次确认；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.runtime，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime.listTraces/getTrace/removeTrace）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：TraceEntry、TraceLevel、Metadata
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.runtime.listTraces 加载列表；
 *   level 筛选 Tab 切换 → 本地 filterByLevel 过滤；
 *   source 筛选 Tab 切换 → 本地 filterBySource 过滤（源 = event 字段值）；
 *   删除 → AlertDialog 二次确认 → api.runtime.removeTrace → 刷新列表
 *
 * TDD：AgentTraceViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 AgentTracePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { TraceEntry, TraceLevel, Metadata } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentTracePage';

// ===========================================================================
// AgentTraceViewHelper - 追踪条目视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentTraceViewHelper {
  /**
   * 获取追踪条目 level 对应的颜色 token 名
   * 映射：debug→text_disabled，info→info，warn→warning，error→error
   * @param level 追踪级别
   * @return StyleManager 颜色 token 名
   */
  static getLevelColor(level: TraceLevel): string {
    if (level === 'debug') return 'text_disabled';
    if (level === 'info') return 'info';
    if (level === 'warn') return 'warning';
    return 'error';
  }

  /**
   * 获取追踪条目 level 对应的图标 emoji
   * 映射：debug→🔍，info→ℹ️，warn→⚠️，error→🔴
   * @param level 追踪级别
   * @return emoji 字符串
   */
  static getLevelIcon(level: TraceLevel): string {
    if (level === 'debug') return '🔍';
    if (level === 'info') return 'ℹ️';
    if (level === 'warn') return '⚠️';
    return '🔴';
  }

  /**
   * 获取追踪条目 level 的中文标签
   * 映射：debug→调试，info→信息，warn→警告，error→错误
   * @param level 追踪级别
   * @return 中文标签字符串
   */
  static getLevelLabel(level: TraceLevel): string {
    if (level === 'debug') return '调试';
    if (level === 'info') return '信息';
    if (level === 'warn') return '警告';
    return '错误';
  }

  /**
   * 格式化 payload 对象为 JSON 字符串，超 200 字符截断
   * @param payload 元数据对象，可选
   * @return 无值→"—"；有值→JSON.stringify，超 200 字符截断并追加省略号
   */
  static formatPayload(payload?: Metadata): string {
    if (payload === undefined || payload === null) return '—';
    const json = JSON.stringify(payload);
    if (json.length <= 200) return json;
    return json.substring(0, 200) + '...';
  }

  /**
   * 格式化耗时
   * 规则：
   *   - undefined → "—"
   *   - <1000ms  → "n ms"（整数毫秒）
   *   - <60000ms → "n.nn s"（秒，保留 2 位小数）
   *   - >=60000ms → "M:SS"（分:秒，秒补零至 2 位）
   * @param durationMs 毫秒数，可选
   * @return 格式化后的字符串
   */
  static formatDuration(durationMs?: number): string {
    if (durationMs === undefined || durationMs === null) return '—';
    if (durationMs < 1000) return `${durationMs} ms`;
    if (durationMs < 60000) return `${(durationMs / 1000).toFixed(2)} s`;
    const totalSec = Math.floor(durationMs / 1000);
    const minutes = Math.floor(totalSec / 60);
    const seconds = totalSec % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }

  /**
   * 格式化时间戳：将 ISO 字符串中的 'T' 替换为空格，截取前 19 位（YYYY-MM-DD HH:mm:ss）
   * @param timestamp ISO 时间字符串，如 "2024-01-15T10:30:45"
   * @return 格式化后的字符串，如 "2024-01-15 10:30:45"
   */
  static formatTimestamp(timestamp: string): string {
    return timestamp.replace('T', ' ').substring(0, 19);
  }
}

// ===========================================================================
// level 筛选 Tab 配置
// ===========================================================================

interface LevelFilterOption {
  value: string;             // 'all' 或具体 TraceLevel
  label: string;
}

/** level 筛选 Tab 列表（顺序即展示顺序） */
const LEVEL_FILTERS: LevelFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'debug', label: '调试' },
  { value: 'info', label: '信息' },
  { value: 'warn', label: '警告' },
  { value: 'error', label: '错误' },
];

/** source 筛选项数据结构 */
interface SourceFilterOption {
  value: string;             // 'all' 或具体 event 值
  label: string;
}

@Component
export struct AgentTracePage {
  // 追踪条目列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State traces: TraceEntry[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的 level 筛选值：'all' 或具体 level
  @State activeLevel: string = 'all';
  // 当前激活的 source 筛选值：'all' 或具体 event
  @State activeSource: string = 'all';
  // source 筛选 Tab 列表（首项固定"全部"，其余从已加载列表的 distinct event 动态填充）
  @State sourceFilters: SourceFilterOption[] = [{ value: 'all', label: '全部' }];

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTraces();
  }

  /**
   * 加载追踪条目列表
   * 流程：取 currentAgentId → 调用 api.runtime.listTraces → 写入 traces
   *       → 重新计算 source 筛选 Tab 列表（基于已加载 distinct event）
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadTraces(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.runtime.listTraces(agentId);
      if (res.code === 0 && res.data) {
        this.traces = res.data.items;
        this.refreshSourceFilters();
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载追踪条目失败', e as Error);
      this.msg.error('加载追踪条目失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 刷新 source 筛选 Tab 列表
   * 规则：保留首项"全部"，其余由已加载 traces 的 distinct event 升序填充
   * 设计：source 即 event 字段值，作为来源分类
   */
  private refreshSourceFilters(): void {
    const events = new Set<string>();
    for (const t of this.traces) {
      if (t.event) events.add(t.event);
    }
    const sorted = Array.from(events).sort();
    const options: SourceFilterOption[] = [{ value: 'all', label: '全部' }];
    for (const ev of sorted) {
      options.push({ value: ev, label: ev });
    }
    // 若当前 activeSource 不在新列表中，回退到 'all'
    if (!sorted.includes(this.activeSource)) {
      this.activeSource = 'all';
    }
    this.sourceFilters = options;
  }

  /**
   * 切换 level 筛选 Tab（本地过滤）
   */
  private switchLevel(value: string): void {
    this.activeLevel = value;
  }

  /**
   * 切换 source 筛选 Tab（本地过滤）
   */
  private switchSource(value: string): void {
    this.activeSource = value;
  }

  /**
   * 获取经 level + source 双重筛选后的列表
   */
  private getFilteredTraces(): TraceEntry[] {
    let list = this.traces;
    if (this.activeLevel !== 'all') {
      list = list.filter((t: TraceEntry) => t.level === this.activeLevel);
    }
    if (this.activeSource !== 'all') {
      list = list.filter((t: TraceEntry) => t.event === this.activeSource);
    }
    return list;
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(trace: TraceEntry): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除追踪条目"${trace.event}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteTrace(trace.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.runtime.removeTrace → 成功后重新加载列表
   */
  private async deleteTrace(traceId: string): Promise<void> {
    try {
      const res = await this.api.runtime.removeTrace(traceId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadTraces();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除追踪条目失败', e as Error);
      this.msg.error('删除失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"追踪条目" + 返回（无新建按钮，追踪只读）
        TopNavMenu({
          title: '追踪条目',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // level 筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(LEVEL_FILTERS, (opt: LevelFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeLevel === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeLevel === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchLevel(opt.value); })
            }, (opt: LevelFilterOption) => opt.value)
          }
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('sm'),
            bottom: this.sm.getSpacing('xs'),
          })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')

        // source 筛选 Tab：横向滚动胶囊（基于已加载列表的 distinct event）
        Scroll() {
          Row({ space: 8 }) {
            ForEach(this.sourceFilters, (opt: SourceFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeSource === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeSource === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchSource(opt.value); })
            }, (opt: SourceFilterOption) => opt.value)
          }
          .padding({
            left: this.sm.getSpacing('md'),
            right: this.sm.getSpacing('md'),
            top: this.sm.getSpacing('xs'),
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
        } else if (this.getFilteredTraces().length === 0) {
          Column() {
            Text('暂无追踪条目')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredTraces(), (trace: TraceEntry) => {
              ListItem() {
                this.buildTraceCard(trace)
              }
            }, (trace: TraceEntry) => trace.id)
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
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 追踪条目卡片构建器
  // ===========================================================================

  /** 单条追踪条目卡片：level 徽章 + event + timestamp + duration + payload 摘要 + 删除 */
  @Builder
  buildTraceCard(trace: TraceEntry) {
    GlassCard() {
      Column() {
        // 上部：level 徽章 + event
        Row() {
          // level 徽章：图标 + 标签
          Row() {
            Text(AgentTraceViewHelper.getLevelIcon(trace.level))
              .fontSize(14)
            Text(AgentTraceViewHelper.getLevelLabel(trace.level))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(AgentTraceViewHelper.getLevelColor(trace.level)))
          .alignItems(VerticalAlign.Center)

          // event（source）
          Text(trace.event)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          // 删除按钮（卡片内直接操作）
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(trace); }
          })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // timestamp
        Text(AgentTraceViewHelper.formatTimestamp(trace.timestamp))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')

        // durationMs（如有）
        if (trace.durationMs !== undefined) {
          Text(`耗时：${AgentTraceViewHelper.formatDuration(trace.durationMs)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: 2 })
            .width('100%')
        }

        // payload 摘要
        Text(`payload：${AgentTraceViewHelper.formatPayload(trace.payload)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .fontFamily('monospace')
          .margin({ top: 4 })
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
