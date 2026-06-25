/**
 * MonitorPage - 实时监控指标页
 *
 * 职责：实时展示 MonitorMetric 列表，按 name 筛选，显示 value+unit+timestamp，
 *       支持自动刷新开关（10s 轮询）
 * 设计：
 *   - MonitorViewHelper（导出）：纯视图模型，封装指标值格式化、时间戳格式化、
 *     标签着色、指标名截断、过期判定，无 UI 运行时依赖，可独立单元测试；
 *   - MonitorPage（@Component）：Stack[Column[TopNavMenu(标题"实时监控"+返回)]
 *     + [工具条（搜索框 + 自动刷新开关 + 手动刷新按钮）] + [加载态/空态/指标列表]]；
 *     指标项 GlassCard 含 name（截断）、value+unit、timestamp（HH:mm:ss）、
 *     tags（按 tagKey 着色，过期指标置灰）；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor.listMetrics，消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor 模块）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MonitorMetric
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listMetrics() 加载列表；
 *   搜索框输入 → 本地 filterByKeyword 过滤；
 *   自动刷新开关 ON → setInterval(loadMetrics, 10000)；OFF → 清除定时器
 *
 * TDD：MonitorViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 MonitorPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MonitorMetric } from '../libs/types';

/** 日志标签 */
const TAG = 'MonitorPage';

/** 默认截断长度 */
const DEFAULT_TRUNCATE_LEN = 16;

/** 自动刷新间隔（毫秒） */
const AUTO_REFRESH_INTERVAL_MS = 10000;

/** 默认过期判定阈值（5 分钟） */
const DEFAULT_STALE_THRESHOLD_MS = 5 * 60 * 1000;

// ===========================================================================
// MonitorViewHelper - 监控指标视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'status_success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MonitorViewHelper {
  /**
   * 格式化指标值（带单位）
   * 规则：value + unit；unit 为空字符串时返回纯数值
   * @param value 数值
   * @param unit 单位（必填，可为空字符串）
   * @return 数值+单位文案
   */
  static formatMetricValue(value: number, unit: string): string {
    return `${value}${unit}`;
  }

  /**
   * 格式化时间戳为 HH:mm:ss（UTC 时区，与 ISO 'Z' 后缀保持一致）
   * 规则：
   *   - 空字符串 → '-'
   *   - 非法时间 → '-'
   *   - 合法 ISO 时间 → 'HH:mm:ss'（不足两位补 0）
   * @param timestamp ISO 时间字符串
   * @return HH:mm:ss 格式或 '-'
   */
  static formatTimestamp(timestamp: string): string {
    if (!timestamp || timestamp.length === 0) return '-';
    const date = new Date(timestamp);
    const ms = date.getTime();
    if (Number.isNaN(ms)) return '-';
    const hh = String(date.getUTCHours()).padStart(2, '0');
    const mm = String(date.getUTCMinutes()).padStart(2, '0');
    const ss = String(date.getUTCSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  }

  /**
   * 获取标签对应的颜色 token 名
   * 设计：基于 switch 的稳定映射，相同 tagKey 始终返回同一 token 名；
   *       未知 tag 返回默认 token 'info'；
   *       返回值为 StyleManager token 名（非颜色值）
   * @param tagKey 标签键
   * @return StyleManager 颜色 token 名
   */
  static getTagColor(tagKey: string): string {
    switch (tagKey) {
      case 'cpu':
        return 'primary';
      case 'memory':
        return 'secondary';
      case 'network':
        return 'success';
      case 'disk':
        return 'warning';
      case 'error':
        return 'status_error';
      case 'warning':
        return 'status_warning';
      default:
        return 'info';
    }
  }

  /**
   * 截断指标名称
   * 规则：
   *   - name 为空 → 返回空字符串
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param name 指标名称
   * @param maxLen 最大长度（必填）
   * @return 截断后的名称
   */
  static truncateMetricName(name: string, maxLen: number): string {
    if (!name || name.length === 0) return '';
    if (name.length <= maxLen) return name;
    return name.substring(0, maxLen) + '...';
  }

  /**
   * 判断指标是否过期
   * 规则：
   *   - 空时间戳 → true（视为过期）
   *   - 非法时间戳 → true（视为过期，避免显示陈旧数据）
   *   - (当前时间 - timestamp) > thresholdMs → true（过期）
   *   - 否则 → false（新鲜）
   * 注：未来时间戳（差值为负）视为新鲜，返回 false
   * @param timestamp ISO 时间字符串
   * @param thresholdMs 过期阈值（毫秒）
   * @return true=过期；false=新鲜
   */
  static isStaleMetric(timestamp: string, thresholdMs: number): boolean {
    if (!timestamp || timestamp.length === 0) return true;
    const tsMs = new Date(timestamp).getTime();
    if (Number.isNaN(tsMs)) return true;
    const diff = Date.now() - tsMs;
    return diff > thresholdMs;
  }
}

@Component
export struct MonitorPage {
  // 监控指标列表（由 API 加载）
  @State metrics: MonitorMetric[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键字（按 name 本地过滤）
  @State keyword: string = '';
  // 自动刷新开关
  @State autoRefresh: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  // 自动刷新定时器句柄
  private refreshTimer: number = -1;

  aboutToAppear() {
    this.loadMetrics();
  }

  aboutToDisappear() {
    this.clearRefreshTimer();
  }

  /**
   * 加载监控指标列表
   * 流程：调用 api.monitor.listMetrics(undefined) → 写入 metrics
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadMetrics(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.monitor.listMetrics(undefined, undefined);
      if (res.code === 0 && res.data) {
        // PageResult 兼容：若 data 为 PageResult 取 items；若 data 为数组直接用
        const data = res.data as Object;
        const items = Array.isArray(data)
          ? (data as MonitorMetric[])
          : ((data as Record<string, Object>)?.['items'] as MonitorMetric[]) ?? [];
        this.metrics = items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载监控指标失败', e as Error);
      this.msg.error('加载监控指标失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换自动刷新开关
   * ON → 启动定时器（10s 轮询）
   * OFF → 清除定时器
   */
  private toggleAutoRefresh(): void {
    this.autoRefresh = !this.autoRefresh;
    if (this.autoRefresh) {
      this.refreshTimer = setInterval(() => { this.loadMetrics(); }, AUTO_REFRESH_INTERVAL_MS);
    } else {
      this.clearRefreshTimer();
    }
  }

  /** 清除自动刷新定时器 */
  private clearRefreshTimer(): void {
    if (this.refreshTimer !== -1) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = -1;
    }
  }

  /**
   * 获取经关键字筛选后的列表
   * 规则：keyword 为空返回全量；否则按 name 包含关键字过滤
   */
  private getFilteredList(): MonitorMetric[] {
    if (!this.keyword || this.keyword.length === 0) {
      return this.metrics;
    }
    const kw = this.keyword.toLowerCase();
    return this.metrics.filter((m: MonitorMetric) => m.name.toLowerCase().includes(kw));
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"实时监控" + 返回按钮
        TopNavMenu({
          title: '实时监控',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 工具条：搜索框 + 自动刷新开关 + 手动刷新按钮
        Row({ space: 8 }) {
          GlassInput({
            placeholder: '搜索指标名称',
            value: this.keyword,
            type: 'text',
            onChange: (v: string) => { this.keyword = v; }
          })
            .layoutWeight(1)

          // 自动刷新开关（文字按钮）
          Text(this.autoRefresh ? '自动刷新：开' : '自动刷新：关')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.autoRefresh
              ? this.sm.getColor('primary')
              : this.sm.getColor('text_secondary'))
            .padding({ left: 8, right: 8, top: 6, bottom: 6 })
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(16)
            .onClick(() => { this.toggleAutoRefresh(); })

          // 手动刷新按钮
          GlassButton({
            label: '刷新',
            onClick: () => { this.loadMetrics(); }
          })
        }
        .width('90%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })

        // 主体内容：加载态 / 空态 / 指标列表 三选一
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
            Text('暂无监控指标')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 指标列表：纵向滚动
          Scroll() {
            Column({ space: this.sm.getSpacing('md') }) {
              ForEach(this.getFilteredList(), (metric: MonitorMetric) => {
                this.buildMetricCard(metric)
              }, (metric: MonitorMetric, index: number) => `${metric.name}_${metric.timestamp}_${index}`)
            }
            .width('100%')
            .padding({
              left: this.sm.getSpacing('md'),
              right: this.sm.getSpacing('md'),
              top: this.sm.getSpacing('sm'),
              bottom: this.sm.getSpacing('sm'),
            })
          }
          .scrollable(ScrollDirection.Vertical)
          .scrollBar(BarState.Auto)
          .layoutWeight(1)
          .width('100%')
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
  // 监控指标卡片构建器
  // ===========================================================================

  /** 单个监控指标卡片：name（截断）+ value+unit + timestamp（HH:mm:ss）+ tags 着色 */
  @Builder
  buildMetricCard(metric: MonitorMetric) {
    GlassCard() {
      Column() {
        // 名称 + 过期标记
        Row() {
          Text(MonitorViewHelper.truncateMetricName(metric.name, DEFAULT_TRUNCATE_LEN))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          // 过期标记
          if (MonitorViewHelper.isStaleMetric(metric.timestamp, DEFAULT_STALE_THRESHOLD_MS)) {
            Text('过期')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('status_warning'))
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .backgroundColor(this.sm.getColor('surface'))
              .borderRadius(8)
              .margin({ left: 8 })
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 数值 + 单位
        Row() {
          Text(MonitorViewHelper.formatMetricValue(metric.value, metric.unit))
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('primary'))
        }
        .alignItems(VerticalAlign.Bottom)
        .margin({ top: 4 })

        // 时间戳
        Row() {
          Text('时间：')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(MonitorViewHelper.formatTimestamp(metric.timestamp))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .alignItems(VerticalAlign.Center)
        .margin({ top: this.sm.getSpacing('sm') })

        // tags 行（如有）：按 tagKey 着色
        if (metric.tags) {
          Row({ space: 6 }) {
            ForEach(this.iterateTagKeys(metric.tags), (tagKey: string) => {
              Text(tagKey)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor(MonitorViewHelper.getTagColor(tagKey)))
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .backgroundColor(this.sm.getColor('surface'))
                .borderRadius(8)
            }, (tagKey: string) => tagKey)
          }
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  /**
   * 辅助方法：将 tags 对象的 key 转为数组（ForEach 需要）
   * 设计：在 Builder 内调用，必须为实例方法（@Builder 不支持调用静态方法时返回数组用于 ForEach）
   */
  private iterateTagKeys(tags: Record<string, Object>): string[] {
    return Object.keys(tags);
  }
}
