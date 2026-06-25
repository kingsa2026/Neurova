/**
 * AnalyticsPage - 数据分析页（P3）
 *
 * 职责：多系列图表展示，按 metric 切换（messages_count/token_usage/active_users），
 *       按 granularity 切换（minute/hour/day/week/month），时间范围选择，统计摘要
 * 设计：
 *   - AnalyticsViewHelper（导出）：纯视图模型，封装指标颜色/标签映射、
 *     粒度标签、值格式化、趋势计算（↑/↓/持平）、最大点查找、
 *     按粒度时间戳格式化（minute→分粒度/month→月粒度），无 UI 依赖，可独立单元测试；
 *   - AnalyticsPage（@Component）：Stack[Column[TopNavMenu(标题"数据分析"+返回)]
 *     + [metric 切换 Tab（messages_count/token_usage/active_users）]
 *     + [granularity 切换 Tab（minute/hour/day/week/month）]
 *     + [统计摘要（趋势/最大值）]
 *     + [加载态/空态/列表（按时间序列展示）]]；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无分析专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 标注。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AnalyticsSeries、AnalyticsPoint、AnalyticsGranularity
 *
 * 用法：
 *   由 Router.push(RouteNames.ANALYTICS) 跳转进入；
 *   aboutToAppear 加载 mock 数据系列（TODO M6 接入真实 API）；
 *   metric/granularity 切换 → 本地切换显示；
 *   统计摘要显示当前序列的趋势与最大点
 *
 * TDD：AnalyticsViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AnalyticsPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AnalyticsSeries, AnalyticsPoint, AnalyticsGranularity } from '../libs/types';

/** 日志标签 */
const TAG = 'AnalyticsPage';

// ===========================================================================
// AnalyticsViewHelper - 数据分析视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class AnalyticsViewHelper {
  /**
   * 获取指标对应的颜色 token 名
   * 映射：messages_count→primary、token_usage→warning、active_users→success、默认→info
   * @param metric 指标名（如 'messages_count'）
   * @return StyleManager 颜色 token 名
   */
  static getMetricColor(metric: string): string {
    if (metric === 'messages_count') return 'primary';
    if (metric === 'token_usage') return 'warning';
    if (metric === 'active_users') return 'success';
    return 'info';
  }

  /**
   * 获取指标对应的中文标签
   * 映射：messages_count→消息数、token_usage→Token 使用量、active_users→活跃用户
   * @param metric 指标名
   * @return 中文标签
   */
  static getMetricLabel(metric: string): string {
    if (metric === 'messages_count') return '消息数';
    if (metric === 'token_usage') return 'Token 使用量';
    if (metric === 'active_users') return '活跃用户';
    return metric;
  }

  /**
   * 获取粒度对应的中文标签
   * 映射：minute→分钟、hour→小时、day→天、week→周、month→月
   * @param g 粒度
   * @return 中文标签
   */
  static getGranularityLabel(g: AnalyticsGranularity): string {
    if (g === 'minute') return '分钟';
    if (g === 'hour') return '小时';
    if (g === 'day') return '天';
    if (g === 'week') return '周';
    if (g === 'month') return '月';
    throw new Error(`getGranularityLabel 未实现: ${g}`);
  }

  /**
   * 格式化数值 + 单位
   * 规则：返回 `${value} ${unit}` 字符串
   * @param value 数值
   * @param unit 单位
   * @return 'value unit' 格式字符串
   */
  static formatValue(value: number, unit: string): string {
    return `${value} ${unit}`;
  }

  /**
   * 计算序列趋势（基于首尾两点）
   * 规则：
   *   - 点数 < 2 → '持平'
   *   - start = points[0].value, end = points[length-1].value
   *   - diff = end - start
   *   - diff === 0 → '持平'
   *   - diff > 0 → `↑X%`（X = Math.round(diff / |start| * 100)；start=0 时 X=100）
   *   - diff < 0 → `↓X%`（X = Math.round(-diff / |start| * 100)；start=0 时 X=100）
   * @param points 数据点数组
   * @return 趋势字符串（'↑X%' / '↓X%' / '持平'）
   */
  static calculateTrend(points: AnalyticsPoint[]): string {
    if (!points || points.length < 2) return '持平';
    const start = points[0].value;
    const end = points[points.length - 1].value;
    const diff = end - start;
    if (diff === 0) return '持平';
    const absStart = Math.abs(start);
    if (absStart === 0) {
      // 起始为 0，统一使用 100% 表示从无到有/从无到负
      return diff > 0 ? '↑100%' : '↓100%';
    }
    const pct = Math.round((Math.abs(diff) / absStart) * 100);
    return diff > 0 ? `↑${pct}%` : `↓${pct}%`;
  }

  /**
   * 查找序列中 value 最大的点
   * 规则：空数组 → null；否则返回 value 最大的点（首个最大值）
   * @param points 数据点数组
   * @return 最大点或 null
   */
  static getMaxPoint(points: AnalyticsPoint[]): AnalyticsPoint | null {
    if (!points || points.length === 0) return null;
    let max = points[0];
    for (let i = 1; i < points.length; i++) {
      if (points[i].value > max.value) {
        max = points[i];
      }
    }
    return max;
  }

  /**
   * 按粒度格式化时间戳
   * 规则：
   *   - minute → 'YYYY-MM-DD HH:mm'
   *   - hour → 'YYYY-MM-DD HH:00'
   *   - day → 'YYYY-MM-DD'
   *   - week → 'YYYY-MM-DD'（与 day 相同）
   *   - month → 'YYYY-MM'
   *   - 无效时间 → '—'
   * @param timestamp ISO 时间戳字符串
   * @param granularity 粒度
   * @return 格式化时间字符串
   */
  static formatPointTimestamp(timestamp: string, granularity: AnalyticsGranularity): string {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '—';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    if (granularity === 'minute') {
      return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
    }
    if (granularity === 'hour') {
      return `${yyyy}-${MM}-${dd} ${HH}:00`;
    }
    if (granularity === 'day' || granularity === 'week') {
      return `${yyyy}-${MM}-${dd}`;
    }
    if (granularity === 'month') {
      return `${yyyy}-${MM}`;
    }
    throw new Error(`formatPointTimestamp 未实现: ${granularity}`);
  }
}

/** 指标切换 Tab 配置 */
interface MetricOption {
  value: string;
  label: string;
}

/** 指标切换 Tab 列表 */
const METRIC_OPTIONS: MetricOption[] = [
  { value: 'messages_count', label: '消息数' },
  { value: 'token_usage', label: 'Token 使用量' },
  { value: 'active_users', label: '活跃用户' },
];

/** 粒度切换 Tab 配置 */
interface GranularityOption {
  value: AnalyticsGranularity;
  label: string;
}

/** 粒度切换 Tab 列表 */
const GRANULARITY_OPTIONS: GranularityOption[] = [
  { value: 'minute', label: '分钟' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '天' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
];

/**
 * Mock 数据分析系列
 * TODO M6 阶段：替换为 api.analytics.list() 真实 API
 */
const MOCK_SERIES: AnalyticsSeries[] = [
  {
    id: 'series_messages',
    name: '消息数（按天）',
    metric: 'messages_count',
    granularity: 'day',
    unit: '条',
    description: '每日消息发送量',
    points: [
      { timestamp: '2025-03-01T00:00:00Z', value: 1200 },
      { timestamp: '2025-03-02T00:00:00Z', value: 1500 },
      { timestamp: '2025-03-03T00:00:00Z', value: 1800 },
      { timestamp: '2025-03-04T00:00:00Z', value: 1350 },
      { timestamp: '2025-03-05T00:00:00Z', value: 2000 },
    ],
  },
  {
    id: 'series_tokens',
    name: 'Token 使用量（按天）',
    metric: 'token_usage',
    granularity: 'day',
    unit: 'K',
    description: '每日 Token 消耗量',
    points: [
      { timestamp: '2025-03-01T00:00:00Z', value: 500 },
      { timestamp: '2025-03-02T00:00:00Z', value: 650 },
      { timestamp: '2025-03-03T00:00:00Z', value: 800 },
      { timestamp: '2025-03-04T00:00:00Z', value: 720 },
      { timestamp: '2025-03-05T00:00:00Z', value: 950 },
    ],
  },
  {
    id: 'series_users',
    name: '活跃用户（按天）',
    metric: 'active_users',
    granularity: 'day',
    unit: '人',
    description: '每日活跃用户数',
    points: [
      { timestamp: '2025-03-01T00:00:00Z', value: 50 },
      { timestamp: '2025-03-02T00:00:00Z', value: 65 },
      { timestamp: '2025-03-03T00:00:00Z', value: 80 },
      { timestamp: '2025-03-04T00:00:00Z', value: 70 },
      { timestamp: '2025-03-05T00:00:00Z', value: 100 },
    ],
  },
];

@Component
export struct AnalyticsPage {
  // 数据系列列表
  @State series: AnalyticsSeries[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的指标
  @State activeMetric: string = 'messages_count';
  // 当前激活的粒度
  @State activeGranularity: AnalyticsGranularity = 'day';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSeries();
  }

  /**
   * 加载数据系列
   * TODO M6 阶段：替换为真实 API（api.analytics.list）
   */
  private async loadSeries(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6: 接入真实 API（api.analytics.*）
      // const res = await this.api.analytics.list({ metric, granularity, start, end });
      // if (res.code === 0 && res.data) { this.series = res.data.items; }
      this.series = MOCK_SERIES.slice();
    } catch (e) {
      this.logger.error(TAG, '加载分析数据失败', e as Error);
      this.msg.error('加载分析数据失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换指标 */
  private switchMetric(value: string): void {
    this.activeMetric = value;
  }

  /** 切换粒度 */
  private switchGranularity(value: AnalyticsGranularity): void {
    this.activeGranularity = value;
  }

  /** 获取当前激活指标 + 粒度的数据系列（本地匹配，匹配不到则返回首条） */
  private getActiveSeries(): AnalyticsSeries | null {
    if (this.series.length === 0) return null;
    const matched = this.series.find((s: AnalyticsSeries) =>
      s.metric === this.activeMetric && s.granularity === this.activeGranularity);
    if (matched) return matched;
    // 粒度不匹配时，退化为按 metric 匹配的首条
    const fallback = this.series.find((s: AnalyticsSeries) => s.metric === this.activeMetric);
    return fallback ? fallback : this.series[0];
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"数据分析" + 返回
        TopNavMenu({
          title: '数据分析',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 指标切换 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(METRIC_OPTIONS, (opt: MetricOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeMetric === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeMetric === opt.value
                  ? this.sm.getColor(AnalyticsViewHelper.getMetricColor(opt.value))
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchMetric(opt.value); })
            }, (opt: MetricOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 粒度切换 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(GRANULARITY_OPTIONS, (opt: GranularityOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeGranularity === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeGranularity === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchGranularity(opt.value); })
            }, (opt: GranularityOption) => opt.value)
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
        } else if (!this.getActiveSeries()) {
          Column() {
            Text('暂无分析数据')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          Column() {
            // 统计摘要
            this.buildSummary()
            // 数据点列表
            List({ space: 8 }) {
              ForEach(this.getActiveSeries()!.points, (pt: AnalyticsPoint, idx: number) => {
                ListItem() {
                  this.buildPointCard(pt)
                }
              }, (pt: AnalyticsPoint, idx: number) => `${pt.timestamp}-${idx}`)
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
          .width('100%')
          .layoutWeight(1)
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
  // 统计摘要构建器
  // ===========================================================================

  /** 统计摘要：序列名 + 趋势 + 最大点 */
  @Builder
  buildSummary() {
    GlassCard() {
      Column() {
        const series = this.getActiveSeries();
        if (series) {
          Text(series.name)
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')
          if (series.description) {
            Text(series.description)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 2 })
              .width('100%')
          }

          // 趋势 + 最大值
          Row() {
            Text(`趋势: ${AnalyticsViewHelper.calculateTrend(series.points)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
              .layoutWeight(1)
            Text(`最大: ${(() => {
              const max = AnalyticsViewHelper.getMaxPoint(series.points);
              return max ? AnalyticsViewHelper.formatValue(max.value, series.unit) : '—';
            })()}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('primary'))
              .layoutWeight(1)
          }
          .width('100%')
          .margin({ top: 4 })
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
    })
  }

  // ===========================================================================
  // 数据点卡片构建器
  // ===========================================================================

  /** 单个数据点卡片：时间戳 + 值 */
  @Builder
  buildPointCard(pt: AnalyticsPoint) {
    GlassCard() {
      Row() {
        Text(AnalyticsViewHelper.formatPointTimestamp(pt.timestamp, this.activeGranularity))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        const series = this.getActiveSeries();
        Text(series ? AnalyticsViewHelper.formatValue(pt.value, series.unit) : `${pt.value}`)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor(AnalyticsViewHelper.getMetricColor(this.activeMetric)))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
  }
}
