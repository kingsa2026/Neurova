/**
 * LogPage - 日志页
 *
 * 职责：展示日志列表，按 level/source 筛选，支持导出/清空
 * 设计：
 *   - LogViewHelper（导出）：纯视图模型，封装日志级别颜色/图标/标签映射、
 *     时间戳格式化、消息截断、上下文格式化，无 UI 运行时依赖，可独立单元测试；
 *   - LogPage（@Component）：Stack[Column[TopNavMenu(标题"日志"+返回+导出/清空)]
 *     + [level 筛选 Tab（全部/debug/info/warn/error/fatal）]
 *     + [source 筛选输入]
 *     + [加载态/空态/列表] + [详情弹窗]]；
 *     列表项 GlassCard 含 level 徽章（颜色按级别区分）、时间戳、source、
 *     消息摘要、展开 context 详情；
 *     清空走 AlertDialog 二次确认；导出走 api.monitor.clearLogs（占位为导出）；
 *     详情弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor.listLogs/getLog/clearLogs）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：LogEntry、LogLevel、Metadata
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listLogs 加载列表；
 *   level/source 筛选 → 切换筛选 Tab/输入 → 本地 filterLogs 过滤；
 *   点击列表项 → 展开折叠 context 详情；
 *   导出按钮 → 调用 api.monitor.clearLogs（暂用清空接口占位）；
 *   清空按钮 → AlertDialog 二次确认 → 调用 api.monitor.clearLogs → 刷新列表
 *
 * TDD：LogViewHelper 各方法按红绿灯垂直切片逐步实现，详见 LogPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { LogEntry, LogLevel, Metadata } from '../libs/types';

/** 日志标签 */
const TAG = 'LogPage';

/** 默认消息截断长度（日志页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

// ===========================================================================
// LogViewHelper - 日志视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'warning'/'error'/
//   'text_secondary'），不加 'status_' 前缀。StyleManager 的 ColorToken 类型仅包含
//   'info'/'warning'/'error'/'success' 等未加前缀的 token，'status_info' 不在其列，
//   调用 getColor('status_info') 会回退到 '#000000'（黑色）。为避免此 bug，
//   统一使用未加前缀的 token，与 TaskPage/ProjectPage 现有模式一致。
// ===========================================================================

export class LogViewHelper {
  /**
   * 获取日志级别对应的颜色 token 名
   * 映射：debug→text_secondary, info→info, warn→warning,
   *       error→error, fatal→error（深红复用 error token，StyleManager 无独立深红 token）
   * @param level 日志级别
   * @return StyleManager 颜色 token 名
   */
  static getLevelColor(level: LogLevel): string {
    if (level === 'debug') return 'text_secondary';
    if (level === 'info') return 'info';
    if (level === 'warn') return 'warning';
    if (level === 'error') return 'error';
    return 'error';
  }

  /**
   * 获取日志级别对应的图标 emoji
   * 映射：debug→🔍, info→ℹ️, warn→⚠️, error→❌, fatal→💀
   * @param level 日志级别
   * @return emoji 字符串
   */
  static getLevelIcon(level: LogLevel): string {
    if (level === 'debug') return '🔍';
    if (level === 'info') return 'ℹ️';
    if (level === 'warn') return '⚠️';
    if (level === 'error') return '❌';
    return '💀';
  }

  /**
   * 获取日志级别对应的中文标签
   * 映射：debug→调试, info→信息, warn→警告, error→错误, fatal→致命
   * @param level 日志级别
   * @return 中文标签
   */
  static getLevelLabel(level: LogLevel): string {
    if (level === 'debug') return '调试';
    if (level === 'info') return '信息';
    if (level === 'warn') return '警告';
    if (level === 'error') return '错误';
    return '致命';
  }

  /**
   * 格式化 ISO 时间戳为 YYYY-MM-DD HH:mm:ss
   * 规则：无值或无效 → "-"
   * @param timestamp ISO 时间戳字符串
   * @return 格式化时间或 "-"
   */
  static formatTimestamp(timestamp?: string): string {
    if (!timestamp || timestamp.length === 0) return '-';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '-';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    const ss = d.getSeconds().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${HH}:${mm}:${ss}`;
  }

  /**
   * 截断日志消息文本
   * 规则：
   *   - msg 为空或长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param msg 日志消息
   * @param maxLen 最大长度，默认 100
   * @return 截断后的消息
   */
  static truncateMessage(msg: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!msg || msg.length === 0) return msg;
    if (msg.length <= len) return msg;
    return msg.substring(0, len) + '...';
  }

  /**
   * 格式化日志上下文为 JSON 字符串
   * 规则：context 为空、undefined 或空对象 → "无"，否则返回 JSON.stringify 结果
   * @param context 上下文元数据
   * @return JSON 字符串或 "无"
   */
  static formatContext(context?: Metadata): string {
    if (!context) return '无';
    const keys = Object.keys(context);
    if (keys.length === 0) return '无';
    return JSON.stringify(context);
  }
}

/** 筛选 Tab 配置 */
interface LevelFilterOption {
  value: string;
  label: string;
}

/** 级别筛选 Tab 列表（全部/debug/info/warn/error/fatal） */
const LEVEL_FILTERS: LevelFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'debug', label: '调试' },
  { value: 'info', label: '信息' },
  { value: 'warn', label: '警告' },
  { value: 'error', label: '错误' },
  { value: 'fatal', label: '致命' },
];

@Component
export struct LogPage {
  // 日志列表
  @State logs: LogEntry[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的级别筛选值
  @State activeLevel: string = 'all';
  // source 筛选输入值
  @State sourceFilter: string = '';
  // 展开详情的日志 id
  @State expandedId: string = '';
  // 清空中态
  @State clearing: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadLogs();
  }

  /**
   * 加载日志列表
   * 流程：调用 api.monitor.listLogs → 写入 logs
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadLogs(): Promise<void> {
    this.loading = true;
    try {
      const level = this.activeLevel !== 'all' ? (this.activeLevel as LogLevel) : undefined;
      const source = this.sourceFilter.length > 0 ? this.sourceFilter : undefined;
      const res = await this.api.monitor.listLogs({ page: 1, size: 100 }, level, source);
      if (res.code === 0 && res.data) {
        this.logs = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载日志失败', e as Error);
      this.msg.error('加载日志列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换级别筛选 Tab */
  private switchLevel(value: string): void {
    this.activeLevel = value;
  }

  /** source 筛选输入变更 */
  private onSourceChange(v: string): void {
    this.sourceFilter = v;
  }

  /** 触发筛选（重新加载） */
  private applyFilter(): void {
    this.loadLogs();
  }

  /** 获取经级别+source 双重筛选后的列表（本地兜底过滤） */
  private getFilteredList(): LogEntry[] {
    let result = this.logs;
    if (this.activeLevel !== 'all') {
      result = result.filter((l: LogEntry) => l.level === this.activeLevel);
    }
    if (this.sourceFilter.length > 0) {
      const kw = this.sourceFilter;
      result = result.filter((l: LogEntry) => l.source.indexOf(kw) >= 0);
    }
    return result;
  }

  /** 切换某条日志的展开状态 */
  private toggleExpand(id: string): void {
    this.expandedId = this.expandedId === id ? '' : id;
  }

  /**
   * 导出日志（占位实现）
   * 流程：调用 api.monitor.listLogs 拉全量 → 提示已导出
   * 异常：记录日志并提示用户
   */
  private async exportLogs(): Promise<void> {
    try {
      const res = await this.api.monitor.listLogs({ page: 1, size: 10000 });
      if (res.code === 0 && res.data) {
        this.msg.success(`已导出 ${res.data.items.length} 条日志`);
      } else {
        this.msg.error(res.message || '导出失败');
      }
    } catch (e) {
      this.logger.error(TAG, '导出日志失败', e as Error);
      this.msg.error('导出日志失败');
    }
  }

  /**
   * 清空日志前二次确认（AlertDialog）
   */
  private confirmClear(): void {
    AlertDialog.show({
      title: '确认清空',
      message: '确定要清空所有日志吗？此操作不可撤销。',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '清空',
        fontColor: this.sm.getColor('error'),
        action: () => { this.clearLogs(); }
      }
    });
  }

  /**
   * 执行清空
   * 流程：调用 api.monitor.clearLogs → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async clearLogs(): Promise<void> {
    this.clearing = true;
    try {
      const res = await this.api.monitor.clearLogs();
      if (res.code === 0) {
        this.msg.success('清空成功');
        this.loadLogs();
      } else {
        this.msg.error(res.message || '清空失败');
      }
    } catch (e) {
      this.logger.error(TAG, '清空日志失败', e as Error);
      this.msg.error('清空日志失败');
    } finally {
      this.clearing = false;
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"日志" + 返回按钮 + 导出/清空按钮
        TopNavMenu({
          title: '日志',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '导出',
            type: 'default',
            size: 'small',
            onClick: () => { this.exportLogs(); }
          })
          GlassButton({
            text: '清空',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmClear(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }

        // 级别筛选 Tab：横向滚动胶囊
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
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // source 筛选输入 + 搜索按钮
        Row({ space: 8 }) {
          GlassInput({
            placeholder: '按模块名筛选',
            value: this.sourceFilter,
            type: 'text',
            onChange: (v: string) => { this.onSourceChange(v); }
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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无日志')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (log: LogEntry) => {
              ListItem() {
                this.buildLogCard(log)
              }
            }, (log: LogEntry) => log.id)
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
  // 日志卡片构建器
  // ===========================================================================

  /** 单条日志卡片：级别徽章 + 时间戳 + source + 消息 + 可展开 context 详情 */
  @Builder
  buildLogCard(log: LogEntry) {
    GlassCard() {
      Column() {
        // 上部：级别徽章 + 时间戳
        Row() {
          // 级别徽章
          Row() {
            Text(LogViewHelper.getLevelIcon(log.level))
              .fontSize(14)
            Text(LogViewHelper.getLevelLabel(log.level))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(LogViewHelper.getLevelColor(log.level)))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor('surface'))

          // 时间戳
          Text(LogViewHelper.formatTimestamp(log.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .alignItems(VerticalAlign.Center)

        // source
        Text(`模块：${log.source}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })

        // 消息摘要（截断 100 字符）
        Text(LogViewHelper.truncateMessage(log.message, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 展开详情按钮
        Text(this.expandedId === log.id ? '收起 ▲' : '展开 ▼')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .margin({ top: 4 })
          .onClick(() => { this.toggleExpand(log.id); })

        // 展开后显示 context 详情
        if (this.expandedId === log.id) {
          Column() {
            Text('上下文')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(LogViewHelper.formatContext(log.context))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .padding({ top: 4, bottom: 4, left: 8, right: 8 })
              .backgroundColor(this.sm.getColor('surface'))
              .borderRadius(this.sm.getRadius('sm'))
              .width('100%')
              .margin({ top: 4 })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: 8 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .onClick(() => { this.toggleExpand(log.id); })
  }
}
