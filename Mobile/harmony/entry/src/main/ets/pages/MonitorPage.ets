/**
 * MonitorPage - 实时监控页（M9.2 监控域契约迁移）
 *
 * 职责：展示后端 /v1/monitor 真实监控面——系统状态、资源使用（psutil 真值）、
 *       连接状态汇总（providers/agents/db/执行监控）、告警列表（可 resolve）。
 *       全部端点要求管理员（非管理员如实展示 403 原因）。
 * 设计：
 *   - MonitorViewHelper（导出）：纯视图模型（保留既有时间戳/截断/着色纯函数，
 *     供 ohosTest 回归），无 UI 运行时依赖；
 *   - MonitorPage（@Component）：Stack[Column[TopNavMenu(标题"实时监控"+返回)]
 *     + [加载态/错误态/四段监控卡]]；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor（getSystemStatus/getResources/listConnections/
 *     listAlerts/resolveAlert），消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor 模块）
 *   - ../libs/api/modules/MonitorApi：监控域真实 DTO
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 顺序拉取 status/resources/connections/alerts；
 *   告警"解决"按钮 → api.monitor.resolveAlert → 刷新告警列表
 *
 * TDD：MonitorViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 MonitorPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SystemStatusDto, ResourceUsageDto, ConnectionStatusDto, AlertDto } from '../libs/api/modules/MonitorApi';

/** 日志标签 */
const TAG = 'MonitorPage';

/** 默认截断长度 */
const DEFAULT_TRUNCATE_LEN = 16;

/** 自动刷新间隔（毫秒） */
const AUTO_REFRESH_INTERVAL_MS = 10000;

/** 默认过期判定阈值（5 分钟） */
const DEFAULT_STALE_THRESHOLD_MS = 5 * 60 * 1000;

// ===========================================================================
// MonitorViewHelper - 监控视图模型（纯函数，无 UI 依赖，可独立单元测试）
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
  // 加载态
  @State loading: boolean = true;
  // 错误文案（非空时显示错误态；含非管理员的 403 原因）
  @State errorMsg: string = '';
  // 系统状态
  @State status: SystemStatusDto | undefined = undefined;
  // 资源使用
  @State resources: ResourceUsageDto | undefined = undefined;
  // 连接状态汇总
  @State connections: ConnectionStatusDto[] = [];
  // 告警列表
  @State alerts: AlertDto[] = [];

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  // 自动刷新定时器句柄
  private refreshTimer: number = -1;
  // 自动刷新开关
  @State autoRefresh: boolean = false;

  aboutToAppear() {
    this.loadAll();
  }

  aboutToDisappear() {
    this.clearRefreshTimer();
  }

  /**
   * 拉取全部监控数据（真实端点，admin 门控）
   * 流程：status → resources → connections → alerts 顺序拉取
   * 异常：记录日志并把后端原因透出到错误态（如非管理员 403）
   */
  private async loadAll(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      const s = await this.api.monitor.getSystemStatus();
      this.status = s.data;
      const r = await this.api.monitor.getResources();
      this.resources = r.data;
      const c = await this.api.monitor.listConnections();
      this.connections = c.data ?? [];
      const a = await this.api.monitor.listAlerts(undefined, undefined, 50);
      this.alerts = a.data ?? [];
    } catch (e) {
      this.logger.error(TAG, '加载监控数据失败', e as Error);
      this.errorMsg = (e as Error).message.length > 0 ? (e as Error).message : '加载监控数据失败';
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
      this.refreshTimer = setInterval(() => { this.loadAll(); }, AUTO_REFRESH_INTERVAL_MS);
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

  /** 解决告警（acknowledge）后刷新告警列表 */
  private async resolveAlert(alert: AlertDto): Promise<void> {
    try {
      await this.api.monitor.resolveAlert(alert.id);
      this.msg.success('告警已解决');
      const a = await this.api.monitor.listAlerts(undefined, undefined, 50);
      this.alerts = a.data ?? [];
    } catch (e) {
      this.logger.error(TAG, '解决告警失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '解决告警失败');
    }
  }

  /** 格式化运行时长（秒 → x天x小时x分） */
  private formatUptime(seconds: number): string {
    if (seconds <= 0) return '-';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}天${hours}小时${minutes}分`;
    if (hours > 0) return `${hours}小时${minutes}分`;
    return `${minutes}分`;
  }

  /** 格式化字节数（GB/MB 自适应） */
  private formatBytes(bytes: number): string {
    if (bytes <= 0) return '-';
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)}GB`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(0)}MB`;
  }

  /** 格式化百分比（usage 0-100） */
  private formatPercent(usage: number): string {
    return `${usage.toFixed(1)}%`;
  }

  /** 资源行名 → 颜色 token（复用既有 tag 着色映射） */
  private resourceColor(key: string): string {
    return MonitorViewHelper.getTagColor(key);
  }

  /** 连接状态 → 颜色 token */
  private connectionColor(status: string): string {
    if (status === 'connected') return 'status_success';
    if (status === 'degraded') return 'status_warning';
    return 'status_error';
  }

  /** 告警严重级 → 颜色 token */
  private severityColor(severity: string): string {
    if (severity === 'critical' || severity === 'error') return 'status_error';
    if (severity === 'warning') return 'status_warning';
    return 'info';
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

        // 工具条：自动刷新开关 + 手动刷新按钮
        Row({ space: 8 }) {
          Text(this.autoRefresh ? '自动刷新：开' : '自动刷新：关')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.autoRefresh
              ? this.sm.getColor('primary')
              : this.sm.getColor('text_secondary'))
            .padding({ left: 8, right: 8, top: 6, bottom: 6 })
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(16)
            .onClick(() => { this.toggleAutoRefresh(); })

          GlassButton({
            text: '刷新',
            onTap: () => { this.loadAll(); }
          })
        }
        .width('90%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })

        // 主体内容：加载态 / 错误态 / 监控数据
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
        } else if (this.errorMsg.length > 0) {
          Column() {
            Text('监控数据加载失败')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('status_error'))
            Text(this.errorMsg)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
            GlassButton({
              text: '重试',
              onTap: () => { this.loadAll(); }
            })
              .margin({ top: 12 })
          }
          .width('90%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          Scroll() {
            Column({ space: this.sm.getSpacing('md') }) {
              this.buildStatusCard()
              this.buildResourcesCard()
              this.buildConnectionsCard()
              this.buildAlertsCard()
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
  // 监控数据卡构建器（真实 /v1/monitor 面）
  // ===========================================================================

  /** 系统状态卡：status/version/python/uptime */
  @Builder
  buildStatusCard() {
    Column() {
    GlassCard() {
      Column() {
        Text('系统状态')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')
        if (this.status !== undefined) {
          Text(`运行状态：${this.status.status}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('status_success'))
            .margin({ top: 6 })
          Text(`版本：${this.status.version} · Python ${this.status.python_version}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 4 })
          Text(`已运行：${this.formatUptime(this.status.uptime)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 4 })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  /** 资源使用卡：cpu / memory / disk 三行（usage+trend，memory/disk 附 used/total） */
  @Builder
  buildResourcesCard() {
    Column() {
    GlassCard() {
      Column() {
        Text('资源使用')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')
        if (this.resources !== undefined) {
          this.buildResourceRow('cpu', this.resources.cpu.usage,
            `${this.formatPercent(this.resources.cpu.usage)}（趋势 ${this.resources.cpu.trend >= 0 ? '+' : ''}${this.resources.cpu.trend}）`)
          this.buildResourceRow('memory', this.resources.memory.usage,
            `${this.formatPercent(this.resources.memory.usage)} · ${this.formatBytes(this.resources.memory.used)}/${this.formatBytes(this.resources.memory.total)}`)
          this.buildResourceRow('disk', this.resources.disk.usage,
            `${this.formatPercent(this.resources.disk.usage)} · ${this.formatBytes(this.resources.disk.used)}/${this.formatBytes(this.resources.disk.total)}`)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  /** 单资源行：名称徽章 + 读数 */
  @Builder
  buildResourceRow(key: string, usage: number, detail: string) {
    Row() {
      Text(key)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor(this.resourceColor(key)))
        .padding({ left: 6, right: 6, top: 2, bottom: 2 })
        .backgroundColor(this.sm.getColor('surface'))
        .borderRadius(8)
      Text(detail)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_secondary'))
        .margin({ left: 8 })
        .layoutWeight(1)
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
    .margin({ top: 6 })
  }

  /** 连接状态卡：providers/db/agents/执行监控 汇总行 */
  @Builder
  buildConnectionsCard() {
    Column() {
    GlassCard() {
      Column() {
        Text('连接状态')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')
        if (this.connections.length === 0) {
          Text('暂无连接状态读数')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 6 })
        } else {
          ForEach(this.connections, (c: ConnectionStatusDto) => {
            Row() {
              Row()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor(this.sm.getColor(this.connectionColor(c.status)))
              Text(c.name)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 6 })
                .layoutWeight(1)
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
              Text(c.detail)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .maxLines(1)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
            .margin({ top: 6 })
          }, (c: ConnectionStatusDto) => `${c.name}_${c.status}`)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }

  /** 告警卡：severity 徽章 + 标题/消息/时间 + 解决按钮 */
  @Builder
  buildAlertsCard() {
    Column() {
    GlassCard() {
      Column() {
        Text('告警')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')
        if (this.alerts.length === 0) {
          Text('当前无告警')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 6 })
        } else {
          ForEach(this.alerts, (a: AlertDto) => {
            Column() {
              Row() {
                Text(a.severity)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor(this.severityColor(a.severity)))
                  .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                  .backgroundColor(this.sm.getColor('surface'))
                  .borderRadius(8)
                Text(MonitorViewHelper.truncateMetricName(a.title, DEFAULT_TRUNCATE_LEN))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_primary'))
                  .margin({ left: 8 })
                  .layoutWeight(1)
                  .maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                if (!a.resolved) {
                  GlassButton({
                    text: '解决',
                    btnSize: 'small',
                    onTap: () => { this.resolveAlert(a); }
                  })
                }
              }
              .width('100%')
              .alignItems(VerticalAlign.Center)

              Text(a.message)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
                .maxLines(2)
                .textOverflow({ overflow: TextOverflow.Ellipsis })
                .margin({ top: 4 })

              Text(`来源：${a.source} · ${MonitorViewHelper.formatTimestamp(new Date(a.timestamp * 1000).toISOString())}${a.resolved ? ' · 已解决' : ''}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .width('100%')
                .margin({ top: 4 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .padding({ top: 6, bottom: 6 })
          }, (a: AlertDto) => a.id)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    }
    .width('100%')
  }
}
