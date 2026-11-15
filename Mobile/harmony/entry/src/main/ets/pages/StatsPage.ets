/**
 * StatsPage - 统计指标页
 *
 * 职责：按时间范围（day/week/month/year）展示 Stat 列表，GlassCard 网格布局，
 *       趋势箭头（正↑绿/负↓红/零→灰），支持搜索
 * 设计：
 *   - StatsViewHelper（导出）：纯视图模型，封装周期标签映射、趋势颜色映射、
 *     趋势图标映射、趋势文案格式化、数值格式化、标签截断，无 UI 运行时依赖，可独立单元测试；
 *   - StatsPage（@Component）：Stack[Column[TopNavMenu(标题"统计指标"+返回)]
 *     + [周期筛选 Tab（day/week/month/year）] + [搜索框] + [加载态/空态/统计网格]]；
 *     网格项 GlassCard 含标签（截断）、数值+单位、趋势行（图标+文案，按趋势着色）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor.listStats，消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor 模块）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Stat
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listStats(period) 加载列表；
 *   周期 Tab 切换 → 重新请求后端；
 *   搜索框输入 → 本地 filterByKeyword 过滤；
 *
 * TDD：StatsViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 StatsPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Stat } from '../libs/types';

/** 日志标签 */
const TAG = 'StatsPage';

/** 周期类型别名 */
type Period = 'day' | 'week' | 'month' | 'year';

/** 默认截断长度 */
const DEFAULT_TRUNCATE_LEN = 16;

// ===========================================================================
// StatsViewHelper - 统计指标视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'status_success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class StatsViewHelper {
  /**
   * 获取周期对应的中文标签
   * 映射：day→今日, week→本周, month→本月, year→全年
   * @param period 周期
   * @return 中文标签
   */
  static getPeriodLabel(period: Period): string {
    if (period === 'day') return '今日';
    if (period === 'week') return '本周';
    if (period === 'month') return '本月';
    return '全年';
  }

  /**
   * 获取趋势对应的颜色 token 名
   * 映射：正数→status_success, 负数→status_error, 零→text_secondary
   * @param trend 趋势值（百分比）
   * @return StyleManager 颜色 token 名
   */
  static getTrendColor(trend: number): string {
    if (trend > 0) return 'status_success';
    if (trend < 0) return 'status_error';
    return 'text_secondary';
  }

  /**
   * 获取趋势对应的箭头图标
   * 映射：正数→↑, 负数→↓, 零→→
   * @param trend 趋势值
   * @return 箭头字符
   */
  static getTrendIcon(trend: number): string {
    if (trend > 0) return '↑';
    if (trend < 0) return '↓';
    return '→';
  }

  /**
   * 格式化趋势为文案
   * 规则：
   *   - 正数 → "+{trend}%"
   *   - 负数 → "{trend}%"（自带负号）
   *   - 零 → "0%"
   * @param trend 趋势值
   * @return 趋势文案
   */
  static formatTrend(trend: number): string {
    if (trend === 0) return '0%';
    if (trend > 0) return `+${trend}%`;
    return `${trend}%`;
  }

  /**
   * 格式化数值（带可选单位）
   * 规则：value + (unit ?? '')；unit 为 undefined/null 时返回纯数值
   * @param value 数值
   * @param unit 单位（可选）
   * @return 数值+单位文案
   */
  static formatValue(value: number, unit?: string): string {
    return `${value}${unit ?? ''}`;
  }

  /**
   * 截断统计标签
   * 规则：
   *   - label 为空 → 返回空字符串
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param label 标签文本
   * @param maxLen 最大长度（必填）
   * @return 截断后的标签
   */
  static truncateLabel(label: string, maxLen: number): string {
    if (!label || label.length === 0) return '';
    if (label.length <= maxLen) return label;
    return label.substring(0, maxLen) + '...';
  }
}

/** 周期筛选 Tab 配置 */
interface PeriodFilterOption {
  value: Period;
  label: string;
}

/** 周期筛选 Tab 列表（顺序：day/week/month/year） */
const PERIOD_FILTERS: PeriodFilterOption[] = [
  { value: 'day', label: '今日' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: 'year', label: '全年' },
];

@Component
export struct StatsPage {
  // 统计指标列表（由 API 加载）
  @State stats: Stat[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的周期
  @State activePeriod: Period = 'day';
  // 搜索关键字（按 label 本地过滤）
  @State keyword: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadStats();
  }

  /**
   * 加载统计指标列表
   * 流程：调用 api.monitor.listStats(period) → 写入 stats
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadStats(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.monitor.listStats(this.activePeriod);
      if (res.code === 0 && res.data) {
        this.stats = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '加载统计指标失败', e as Error);
      this.msg.error('加载统计指标失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换周期 Tab → 重新请求后端
   */
  private switchPeriod(value: Period): void {
    if (this.activePeriod === value) return;
    this.activePeriod = value;
    this.loadStats();
  }

  /**
   * 获取经关键字筛选后的列表
   * 规则：keyword 为空返回全量；否则按 label 包含关键字过滤
   */
  private getFilteredList(): Stat[] {
    if (!this.keyword || this.keyword.length === 0) {
      return this.stats;
    }
    const kw = this.keyword.toLowerCase();
    return this.stats.filter((s: Stat) => s.label.toLowerCase().includes(kw));
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"统计指标" + 返回按钮
        TopNavMenu({
          title: '统计指标',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 周期筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(PERIOD_FILTERS, (opt: PeriodFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activePeriod === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activePeriod === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchPeriod(opt.value); })
            }, (opt: PeriodFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 搜索框：按 label 过滤
        GlassInput({
          placeholder: '搜索指标名称',
          value: this.keyword,
          type: 'text',
          onChange: (v: string) => { this.keyword = v; }
        })
          .width('90%')
          .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })

        // 主体内容：加载态 / 空态 / 统计网格 三选一
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
            Text('暂无统计指标')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 统计网格：两列布局
          Grid() {
            ForEach(this.getFilteredList(), (stat: Stat) => {
              GridItem() {
                this.buildStatCard(stat)
              }
            }, (stat: Stat) => stat.key)
          }
          .columnsTemplate('1fr 1fr')
          .columnsGap(this.sm.getSpacing('md'))
          .rowsGap(this.sm.getSpacing('md'))
          .layoutWeight(1)
          .width('100%')
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
  // 统计卡片构建器
  // ===========================================================================

  /** 单个统计卡片：标签（截断）+ 数值+单位 + 趋势行（图标+文案，按趋势着色） */
  @Builder
  buildStatCard(stat: Stat) {
    GlassCard() {
      Column() {
        // 标签（截断 16 字符）
        Text(StatsViewHelper.truncateLabel(stat.label, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')

        // 数值 + 单位
        Row() {
          Text(StatsViewHelper.formatValue(stat.value, stat.unit))
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
        }
        .alignItems(VerticalAlign.Bottom)
        .margin({ top: 4 })

        // 趋势行：图标 + 文案（按趋势着色）
        if (stat.trend !== undefined && stat.trend !== null) {
          Row() {
            Text(StatsViewHelper.getTrendIcon(stat.trend))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(StatsViewHelper.getTrendColor(stat.trend)))
            Text(StatsViewHelper.formatTrend(stat.trend))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(StatsViewHelper.getTrendColor(stat.trend)))
              .margin({ left: 4 })
          }
          .alignItems(VerticalAlign.Center)
          .margin({ top: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
