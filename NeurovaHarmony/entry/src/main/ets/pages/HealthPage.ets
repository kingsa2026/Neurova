/**
 * HealthPage - 系统健康页
 *
 * 职责：展示系统整体健康分数、各服务状态、关键指标，支持手动刷新
 * 设计：
 *   - HealthViewHelper（导出）：纯视图模型，封装状态颜色映射、分数颜色映射、延迟颜色映射、
 *     相对时间格式化，无 UI 运行时依赖，可独立单元测试；
 *   - HealthPage（@Component）：Column [TopNavMenu(标题+返回+刷新)] + [整体健康大卡片]
 *     + [服务列表 List + GlassCard] + [关键指标 Grid 2列]；加载态/空态切换；
 *     aboutToAppear 调用 api.health.check 写入 HealthStore 渲染；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.health，状态走 HealthStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassStatCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（health.check）
 *   - ../libs/state/stores/HealthStore：健康状态（setHealth/health/lastCheckAt）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SystemHealth、ServiceHealth
 *
 * 用法：
 *   由 Router.push(RouteNames.HEALTH) 跳转进入；
 *   aboutToAppear 加载系统健康数据；
 *   刷新按钮重新调用 api.health.check；
 *   失败时 MessageManager.error 提示并显示 HealthStore 缓存
 *
 * TDD：HealthViewHelper 各方法按红绿灯垂直切片逐步实现，详见 HealthPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassStatCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { HealthStore, HealthData } from '../libs/state/stores/HealthStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SystemHealth, ServiceHealth } from '../libs/types';

/** 日志标签 */
const TAG = 'HealthPage';

// ===========================================================================
// HealthViewHelper - 健康视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class HealthViewHelper {
  /**
   * 获取整体状态对应的颜色 token 名
   * 映射：healthy→success，degraded→warning，down→error，unknown→text_disabled
   * @param status 系统或服务状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: 'healthy' | 'degraded' | 'down' | 'unknown'): string {
    if (status === 'healthy') return 'success';
    if (status === 'degraded') return 'warning';
    if (status === 'down') return 'error';
    return 'text_disabled';
  }

  /**
   * 获取健康分数对应的颜色 token 名
   * 映射：≥80→success，50-79→warning，<50→error
   * @param score 健康分数 0-100
   * @return StyleManager 颜色 token 名
   */
  static getScoreColor(score: number): string {
    if (score >= 80) return 'success';
    if (score >= 50) return 'warning';
    return 'error';
  }

  /**
   * 获取延迟对应的颜色 token 名
   * 映射：<100ms→success，100-500ms→warning，>500ms→error，undefined→text_disabled
   * @param latency 延迟毫秒数；undefined 表示未测量
   * @return StyleManager 颜色 token 名
   */
  static getLatencyColor(latency: number | undefined): string {
    if (latency === undefined) return 'text_disabled';
    if (latency < 100) return 'success';
    if (latency <= 500) return 'warning';
    return 'error';
  }

  /**
   * 格式化相对时间
   * 映射：<60s→"刚刚"，<60min→"X 分钟前"，<24h→"X 小时前"，其他→"X 天前"
   * @param timestampMs 目标时间戳（毫秒）
   * @return 相对时间文案
   */
  static formatRelativeTime(timestampMs: number): string {
    const diff = Date.now() - timestampMs;
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return '刚刚';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 小时前`;
    const days = Math.floor(hours / 24);
    return `${days} 天前`;
  }
}

// ===========================================================================
// HealthPage - 系统健康页组件
//
// 设计：Column [TopNavMenu] + [加载态/空态/Scroll(整体卡片 + 服务列表 + 指标网格)]；
//       数据流：aboutToAppear → api.health.check → 写入 HealthStore → 渲染；
//       失败时 MessageManager.error 提示，并尝试从 HealthStore 还原缓存；
//       刷新按钮触发重新 check；aboutToDisappear 预留 M5 定时刷新清理
// ===========================================================================

@Component
export struct HealthPage {
  // 系统健康数据（API 返回的完整结构，驱动页面渲染）
  @State health: SystemHealth | null = null;
  // 加载态（控制"加载中..."占位与内容的切换）
  @State loading: boolean = true;
  // 检查时间戳（毫秒），用于相对时间显示；优先用 API 返回的 checkedAt，回退 lastCheckAt
  @State checkedAtMs: number = 0;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private healthStore = new HealthStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadHealth();
  }

  /**
   * aboutToDisappear 清理钩子
   * M5 阶段在此释放定时刷新句柄；当前阶段无定时器，留空占位
   */
  aboutToDisappear() {
    // M5: 清理 setInterval 定时刷新句柄
  }

  /**
   * 加载系统健康数据
   * 流程：调用 api.health.check → 写入 HealthStore → 渲染
   * 异常：记录日志 + MessageManager.error；尝试从 HealthStore 还原缓存以保证可用性
   */
  private async loadHealth(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.health.check();
      if (res.code === 0 && res.data) {
        this.health = res.data;
        this.checkedAtMs = this.parseCheckedAt(res.data.checkedAt);
        this.healthStore.setHealth(this.toHealthData(res.data));
      } else {
        this.msg.error(res.message || '加载健康数据失败');
        this.restoreFromStore();
      }
    } catch (e) {
      this.logger.error(TAG, '加载健康数据失败', e as Error);
      this.msg.error('加载健康数据失败');
      this.restoreFromStore();
    } finally {
      this.loading = false;
    }
  }

  /**
   * 刷新按钮回调：重新调用 loadHealth
   */
  private handleRefresh(): void {
    this.loadHealth();
  }

  /**
   * 将 SystemHealth 转换为 HealthStore 持久化结构
   * 说明：HealthStore 只保存精简的 status + services 字典，丢弃 score/version 等
   */
  private toHealthData(sys: SystemHealth): HealthData {
    const services: Record<string, { status: string; latency?: number }> = {};
    for (const s of sys.services) {
      services[s.name] = { status: s.status, latency: s.latency };
    }
    return { status: sys.status, services };
  }

  /**
   * 从 HealthStore 还原缓存到 @State
   * 说明：缓存结构精简，score/services 详情不可恢复，仅恢复 status 与 lastCheckAt
   */
  private restoreFromStore(): void {
    const cached = this.healthStore.health;
    const lastCheck = this.healthStore.lastCheckAt;
    if (cached) {
      const services: ServiceHealth[] = [];
      const entries = Object.entries(cached.services);
      for (let i = 0; i < entries.length; i++) {
        const [name, info] = entries[i];
        services.push({
          name: name,
          status: info.status as 'healthy' | 'degraded' | 'down' | 'unknown',
          latency: info.latency,
        });
      }
      this.health = {
        status: cached.status,
        score: 0,
        services: services,
        checkedAt: lastCheck > 0 ? new Date(lastCheck).toISOString() : '',
      };
      this.checkedAtMs = lastCheck;
    }
  }

  /**
   * 将 checkedAt 字符串解析为毫秒时间戳
   * 支持 ISO 字符串与已有毫秒数值；解析失败回退 0
   */
  private parseCheckedAt(checkedAt: string): number {
    if (!checkedAt) return 0;
    const d = new Date(checkedAt);
    return isNaN(d.getTime()) ? 0 : d.getTime();
  }

  /** 获取状态文案徽章：healthy→健康，degraded→降级，down→宕机，unknown→未知 */
  private getStatusLabel(status: 'healthy' | 'degraded' | 'down' | 'unknown'): string {
    switch (status) {
      case 'healthy': return '健康';
      case 'degraded': return '降级';
      case 'down': return '宕机';
      default: return '未知';
    }
  }

  /** 格式化 uptime（秒）为简短人类可读：<60s→Xs，<3600s→Xm，<86400s→Xh，其他→Xd */
  private formatUptime(uptimeSec: number | undefined): string {
    if (uptimeSec === undefined) return '-';
    if (uptimeSec < 60) return `${uptimeSec}s`;
    if (uptimeSec < 3600) return `${Math.floor(uptimeSec / 60)}m`;
    if (uptimeSec < 86400) return `${Math.floor(uptimeSec / 3600)}h`;
    return `${Math.floor(uptimeSec / 86400)}d`;
  }

  /** 计算平均延迟（ms），无服务或全部无延迟时回退 undefined */
  private calcAvgLatency(services: ServiceHealth[]): number | undefined {
    const latencies = services.filter(s => s.latency !== undefined).map(s => s.latency as number);
    if (latencies.length === 0) return undefined;
    const sum = latencies.reduce((acc, v) => acc + v, 0);
    return Math.round(sum / latencies.length);
  }

  /** 计算指定状态的服务数量 */
  private countByStatus(services: ServiceHealth[], status: 'healthy' | 'degraded' | 'down'): number {
    return services.filter(s => s.status === status).length;
  }

  build() {
    Column() {
      // 顶部导航栏：标题"系统健康" + 返回按钮 + 刷新按钮（右侧插槽）
      TopNavMenu({
        title: '系统健康',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '刷新',
          type: 'primary',
          size: 'small',
          onClick: () => { this.handleRefresh(); }
        })
      }

      if (this.loading) {
        // 加载态：居中显示"加载中..."
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.health === null) {
        // 空态：无数据且无缓存，居中显示"暂无数据" + 刷新按钮
        Column() {
          Text('暂无数据')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ bottom: this.sm.getSpacing('md') })
          GlassButton({
            text: '重新加载',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.handleRefresh(); }
          })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 内容滚动区：整体健康卡 + 服务列表 + 关键指标网格
        Scroll() {
          Column() {
            // ========== 区块1：整体健康大卡片 ==========
            this.buildOverallCard()

            // ========== 区块2：服务列表 ==========
            this.buildServicesSection()

            // ========== 区块3：关键指标网格 ==========
            this.buildMetricsGrid()
          }
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.TopStart)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 区块构建器
  // ===========================================================================

  /** 区块1：整体健康大卡片 - 大号分数 + 状态徽章 + 检查时间 */
  @Builder
  buildOverallCard() {
    GlassCard({ title: '系统健康' }) {
      Column() {
        // 大号健康分数（颜色按分数：≥80 success / 50-79 warning / <50 error）
        Row() {
          Text(String(this.health!.score))
            .fontSize(this.sm.getFontSize('display'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(HealthViewHelper.getScoreColor(this.health!.score)))
          Text(' / 100')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
            .alignSelf(ItemAlign.Bottom)
            .margin({ bottom: 6, left: 4 })
        }
        .alignItems(VerticalAlign.Bottom)
        .margin({ top: this.sm.getSpacing('sm') })

        // 整体状态徽章（圆点 + 文案）
        Row() {
          Row()
            .width(10)
            .height(10)
            .borderRadius(5)
            .backgroundColor(this.sm.getColor(HealthViewHelper.getStatusColor(this.health!.status)))
          Text(this.getStatusLabel(this.health!.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(HealthViewHelper.getStatusColor(this.health!.status)))
            .margin({ left: 6 })
        }
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 检查时间（相对时间，无值回退"未知"）
        Text(this.checkedAtMs > 0
          ? `检查于 ${HealthViewHelper.formatRelativeTime(this.checkedAtMs)}`
          : '检查时间未知')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 区块2：服务列表 - 每项 GlassCard 含名称/状态/延迟/版本/uptime/消息/延迟进度条 */
  @Builder
  buildServicesSection() {
    GlassCard({ title: '服务状态' }) {
      if (this.health!.services.length === 0) {
        // 空服务列表占位
        Text('暂无服务')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .padding(this.sm.getSpacing('lg'))
      } else {
        // 服务列表（纵向排列，每项之间留 12 间距）
        Column() {
          ForEach(this.health!.services, (svc: ServiceHealth) => {
            this.buildServiceItem(svc)
          }, (svc: ServiceHealth) => svc.name)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
    }
    .width('100%')
    .margin({ bottom: this.sm.getSpacing('md') })
  }

  /** 单个服务条目：名称+状态徽章 / 延迟+版本+uptime / 消息 / 延迟进度条 */
  @Builder
  buildServiceItem(svc: ServiceHealth) {
    Column() {
      // 行1：服务名（左）+ 状态徽章（右）
      Row() {
        Text(svc.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        // 状态徽章
        Row() {
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(HealthViewHelper.getStatusColor(svc.status)))
          Text(this.getStatusLabel(svc.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(HealthViewHelper.getStatusColor(svc.status)))
            .margin({ left: 4 })
        }
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 行2：延迟 + 版本 + uptime（次级信息行）
      Row() {
        Text(`延迟: ${svc.latency !== undefined ? svc.latency + 'ms' : '-'}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor(HealthViewHelper.getLatencyColor(svc.latency)))
        Text(`版本: ${svc.version ?? '-'}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ left: this.sm.getSpacing('md') })
        Text(`运行: ${this.formatUptime(svc.uptime)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ left: this.sm.getSpacing('md') })
      }
      .width('100%')
      .margin({ top: 6 })
      .alignItems(VerticalAlign.Center)

      // 行3：健康消息（仅在存在时渲染）
      if (svc.message) {
        Text(svc.message)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
      }

      // 行4：延迟进度条（颜色按延迟：绿/黄/红；无延迟时不渲染）
      if (svc.latency !== undefined) {
        Progress({ value: Math.min(svc.latency, 1000), total: 1000, type: ProgressType.Linear })
          .color(this.sm.getColor(HealthViewHelper.getLatencyColor(svc.latency)))
          .backgroundColor(this.sm.getColor('divider'))
          .width('100%')
          .margin({ top: 8 })
          .borderRadius(2)
      }
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ top: 8, bottom: 8 })
  }

  /** 区块3：关键指标网格 - 2列 GlassStatCard（服务总数/健康数/异常数/平均延迟） */
  @Builder
  buildMetricsGrid() {
    Column() {
      Text('关键指标')
        .fontSize(this.sm.getFontSize('subtitle'))
        .fontWeight(FontWeight.Bold)
        .fontColor(this.sm.getColor('text_primary'))
        .margin({ bottom: this.sm.getSpacing('sm') })

      Flex({ wrap: FlexWrap.Wrap, justifyContent: FlexAlign.SpaceBetween }) {
        GlassStatCard({
          label: '服务总数',
          value: String(this.health!.services.length),
          unit: '个'
        })
          .width('48%')
          .margin({ bottom: this.sm.getSpacing('md') })

        GlassStatCard({
          label: '健康服务',
          value: String(this.countByStatus(this.health!.services, 'healthy')),
          unit: '个'
        })
          .width('48%')
          .margin({ bottom: this.sm.getSpacing('md') })

        GlassStatCard({
          label: '异常服务',
          value: String(
            this.countByStatus(this.health!.services, 'degraded') +
            this.countByStatus(this.health!.services, 'down')
          ),
          unit: '个'
        })
          .width('48%')
          .margin({ bottom: this.sm.getSpacing('md') })

        GlassStatCard({
          label: '平均延迟',
          value: this.calcAvgLatency(this.health!.services) !== undefined
            ? String(this.calcAvgLatency(this.health!.services))
            : '-',
          unit: 'ms'
        })
          .width('48%')
          .margin({ bottom: this.sm.getSpacing('md') })
      }
      .width('100%')
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
