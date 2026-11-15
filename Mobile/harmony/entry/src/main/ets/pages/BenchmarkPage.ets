/**
 * BenchmarkPage - 性能基准测试页（P3）
 *
 * 职责：展示基准测试项列表，按 type 筛选，状态徽章颜色区分，
 *       运行按钮，显示 latency/throughput/score，对比历史
 * 设计：
 *   - BenchmarkViewHelper（导出）：纯视图模型，封装基准类型颜色/图标/标签映射、
 *     状态颜色/图标映射、延迟格式化（ms/s 转换）、吞吐量格式化（ops/s → K ops/s），
 *     无 UI 依赖，可独立单元测试；
 *   - BenchmarkPage（@Component）：Stack[Column[TopNavMenu(标题"性能基准"+返回+运行)]
 *     + [type 筛选 Tab（全部/cpu/memory/disk/network/llm_inference/embedding）]
 *     + [加载态/空态/列表]]；
 *     列表项 GlassCard：类型徽章、名称、状态徽章、avg/p95/p99 延迟、吞吐量、score；
 *     颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无基准专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 标注。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Benchmark、BenchmarkType
 *
 * 用法：
 *   由 Router.push(RouteNames.BENCHMARK) 跳转进入；
 *   aboutToAppear 加载 mock 基准列表（TODO M6 接入真实 API）；
 *   type 筛选 Tab 切换 → 本地按 type 过滤；
 *   运行按钮 → TODO M6 接入 api.benchmark.run
 *
 * TDD：BenchmarkViewHelper 各方法按红绿灯垂直切片逐步实现，详见 BenchmarkPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Benchmark, BenchmarkType } from '../libs/types';

/** 日志标签 */
const TAG = 'BenchmarkPage';

/** 秒级阈值：≥1000ms 切换为秒格式 */
const SECONDS_THRESHOLD_MS = 1000;

/** K 级阈值：≥1000 ops/s 切换为 K ops/s 格式 */
const K_THRESHOLD_OPS = 1000;

// ===========================================================================
// BenchmarkViewHelper - 性能基准视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class BenchmarkViewHelper {
  /**
   * 获取基准类型对应的颜色 token 名
   * 映射：cpu→primary、memory→info、disk→warning、network→success、
   *       llm_inference→error、embedding→text_secondary
   * @param type 基准类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: BenchmarkType): string {
    if (type === 'cpu') return 'primary';
    if (type === 'memory') return 'info';
    if (type === 'disk') return 'warning';
    if (type === 'network') return 'success';
    if (type === 'llm_inference') return 'error';
    if (type === 'embedding') return 'text_secondary';
    throw new Error(`getTypeColor 未实现: ${type}`);
  }

  /**
   * 获取基准类型对应的图标 emoji
   * 映射：cpu→💻、memory→🧠、disk→💾、network→🌐、llm_inference→🤖、embedding→🔢
   * @param type 基准类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: BenchmarkType): string {
    if (type === 'cpu') return '💻';
    if (type === 'memory') return '🧠';
    if (type === 'disk') return '💾';
    if (type === 'network') return '🌐';
    if (type === 'llm_inference') return '🤖';
    if (type === 'embedding') return '🔢';
    throw new Error(`getTypeIcon 未实现: ${type}`);
  }

  /**
   * 获取基准类型对应的中文标签
   * 映射：cpu→CPU、memory→内存、disk→磁盘、network→网络、
   *       llm_inference→LLM 推理、embedding→向量嵌入
   * @param type 基准类型
   * @return 中文标签
   */
  static getTypeLabel(type: BenchmarkType): string {
    if (type === 'cpu') return 'CPU';
    if (type === 'memory') return '内存';
    if (type === 'disk') return '磁盘';
    if (type === 'network') return '网络';
    if (type === 'llm_inference') return 'LLM 推理';
    if (type === 'embedding') return '向量嵌入';
    throw new Error(`getTypeLabel 未实现: ${type}`);
  }

  /**
   * 获取基准状态对应的颜色 token 名
   * 映射：pending→text_secondary、running→info、completed→success、failed→error
   * @param status 基准状态（'pending' | 'running' | 'completed' | 'failed'）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: string): string {
    if (status === 'pending') return 'text_secondary';
    if (status === 'running') return 'info';
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'error';
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取基准状态对应的图标 emoji
   * 映射：pending→⏳、running→⚡、completed→✅、failed→❌
   * @param status 基准状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: string): string {
    if (status === 'pending') return '⏳';
    if (status === 'running') return '⚡';
    if (status === 'completed') return '✅';
    if (status === 'failed') return '❌';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 格式化延迟时间
   * 规则：
   *   - < 1000ms → 'X.Xms'（保留 1 位小数）
   *   - ≥ 1000ms → 'X.Xs'（秒，保留 1 位小数）
   * @param ms 延迟毫秒数
   * @return 格式化延迟字符串
   */
  static formatLatency(ms: number): string {
    if (ms < SECONDS_THRESHOLD_MS) {
      return `${ms.toFixed(1)}ms`;
    }
    const seconds = ms / SECONDS_THRESHOLD_MS;
    return `${seconds.toFixed(1)}s`;
  }

  /**
   * 格式化吞吐量
   * 规则：
   *   - undefined → '—'
   *   - < 1000 → 'X ops/s'（原值）
   *   - ≥ 1000 → 'X.XK ops/s'（保留 1 位小数）
   * @param ops 吞吐量 ops/s（可选）
   * @return 格式化吞吐量字符串
   */
  static formatThroughput(ops?: number): string {
    if (ops === undefined || ops === null) return '—';
    if (ops < K_THRESHOLD_OPS) {
      return `${ops} ops/s`;
    }
    const k = ops / K_THRESHOLD_OPS;
    return `${k.toFixed(1)}K ops/s`;
  }
}

/** 类型筛选 Tab 配置 */
interface TypeFilterOption {
  value: string;
  label: string;
}

/** 类型筛选 Tab 列表 */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'cpu', label: 'CPU' },
  { value: 'memory', label: '内存' },
  { value: 'disk', label: '磁盘' },
  { value: 'network', label: '网络' },
  { value: 'llm_inference', label: 'LLM 推理' },
  { value: 'embedding', label: '向量嵌入' },
];

/**
 * Mock 基准测试数据
 * TODO M6 阶段：替换为 api.benchmark.list() 真实 API
 */
const MOCK_BENCHMARKS: Benchmark[] = [
  {
    id: 'bench_1',
    type: 'cpu',
    name: 'CPU 矩阵乘法基准',
    durationMs: 5000,
    iterations: 1000,
    avgLatencyMs: 5.2,
    p95LatencyMs: 8.5,
    p99LatencyMs: 12.3,
    throughputOps: 5000,
    score: 8800,
    status: 'completed',
    startedAt: '2025-03-01T10:00:00Z',
    completedAt: '2025-03-01T10:00:05Z',
  },
  {
    id: 'bench_2',
    type: 'memory',
    name: '内存读写吞吐',
    durationMs: 3000,
    iterations: 500,
    avgLatencyMs: 2.1,
    p95LatencyMs: 3.5,
    p99LatencyMs: 5.0,
    throughputOps: 12000,
    score: 7500,
    status: 'completed',
    startedAt: '2025-03-01T11:00:00Z',
    completedAt: '2025-03-01T11:00:03Z',
  },
  {
    id: 'bench_3',
    type: 'llm_inference',
    name: 'GPT-4 推理基准',
    durationMs: 60000,
    iterations: 100,
    avgLatencyMs: 1500,
    p95LatencyMs: 2000,
    p99LatencyMs: 2500,
    throughputOps: 60,
    score: 9200,
    status: 'completed',
    startedAt: '2025-03-01T12:00:00Z',
    completedAt: '2025-03-01T12:01:00Z',
  },
  {
    id: 'bench_4',
    type: 'embedding',
    name: '向量嵌入吞吐测试',
    durationMs: 10000,
    iterations: 200,
    avgLatencyMs: 50,
    p95LatencyMs: 80,
    p99LatencyMs: 120,
    throughputOps: 980,
    status: 'running',
    startedAt: '2025-03-01T13:00:00Z',
  },
  {
    id: 'bench_5',
    type: 'network',
    name: '网络延迟基准',
    durationMs: 0,
    iterations: 0,
    avgLatencyMs: 0,
    p95LatencyMs: 0,
    p99LatencyMs: 0,
    status: 'pending',
  },
  {
    id: 'bench_6',
    type: 'disk',
    name: '磁盘 IOPS 基准',
    durationMs: 2000,
    iterations: 100,
    avgLatencyMs: 0,
    p95LatencyMs: 0,
    p99LatencyMs: 0,
    status: 'failed',
    startedAt: '2025-03-01T09:00:00Z',
  },
];

@Component
export struct BenchmarkPage {
  // 基准测试列表
  @State benchmarks: Benchmark[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的类型筛选
  @State activeType: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadBenchmarks();
  }

  /**
   * 加载基准列表
   * TODO M6 阶段：替换为真实 API（api.benchmark.list）
   */
  private async loadBenchmarks(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6: 接入真实 API（api.benchmark.*）
      // const res = await this.api.benchmark.list();
      // if (res.code === 0 && res.data) { this.benchmarks = res.data.items; }
      this.benchmarks = MOCK_BENCHMARKS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载基准列表失败', e as Error);
      this.msg.error('加载基准列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换类型筛选 */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /** 获取经类型筛选后的列表 */
  private getFilteredBenchmarks(): Benchmark[] {
    if (this.activeType === 'all') {
      return this.benchmarks;
    }
    return this.benchmarks.filter((b: Benchmark) => b.type === this.activeType);
  }

  /**
   * 触发运行基准
   * TODO M6 阶段：调用真实 API（api.benchmark.run）
   */
  private async runBenchmark(bench: Benchmark): Promise<void> {
    try {
      // TODO M6: const res = await this.api.benchmark.run(bench.id);
      this.msg.success(`已触发: ${bench.name}`);
    } catch (e) {
      this.logger.error(TAG, '运行基准失败', e as Error);
      this.msg.error('运行基准失败');
    }
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"性能基准" + 返回
        TopNavMenu({
          title: '性能基准',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 类型筛选 Tab
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
        } else if (this.getFilteredBenchmarks().length === 0) {
          Column() {
            Text('暂无基准数据')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredBenchmarks(), (bench: Benchmark) => {
              ListItem() {
                this.buildBenchmarkCard(bench)
              }
            }, (bench: Benchmark) => bench.id)
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
  // 基准卡片构建器
  // ===========================================================================

  /** 单条基准卡片：类型徽章 + 名称 + 状态徽章 + 延迟 + 吞吐量 + score + 运行按钮 */
  @Builder
  buildBenchmarkCard(bench: Benchmark) {
    GlassCard() {
      Column() {
        // 上部：类型徽章 + 状态徽章
        Row() {
          // 类型徽章
          Row() {
            Text(BenchmarkViewHelper.getTypeIcon(bench.type))
              .fontSize(14)
            Text(BenchmarkViewHelper.getTypeLabel(bench.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(BenchmarkViewHelper.getTypeColor(bench.type)))

          // 状态徽章
          Row() {
            Text(BenchmarkViewHelper.getStatusIcon(bench.status))
              .fontSize(14)
              .margin({ left: 8 })
            Text(bench.status)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(BenchmarkViewHelper.getStatusColor(bench.status)))
              .margin({ left: 4 })
          }
          .layoutWeight(1)
          .justifyContent(FlexAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 基准名称
        Text(bench.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 延迟信息：avg / p95 / p99
        if (bench.status === 'completed' || bench.status === 'running') {
          Row() {
            Text(`avg: ${BenchmarkViewHelper.formatLatency(bench.avgLatencyMs)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .layoutWeight(1)
            Text(`p95: ${BenchmarkViewHelper.formatLatency(bench.p95LatencyMs)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .layoutWeight(1)
            Text(`p99: ${BenchmarkViewHelper.formatLatency(bench.p99LatencyMs)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .layoutWeight(1)
          }
          .width('100%')
          .margin({ top: 4 })
          .alignItems(VerticalAlign.Center)

          // 吞吐量
          Text(`吞吐量: ${BenchmarkViewHelper.formatThroughput(bench.throughputOps)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 4 })
        }

        // score（如果有）
        if (bench.score !== undefined) {
          Text(`评分: ${bench.score}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('primary'))
            .margin({ top: 4 })
        }

        // 运行按钮
        Row() {
          GlassButton({
            text: bench.status === 'running' ? '运行中' : '运行',
            type: bench.status === 'running' ? 'default' : 'primary',
            size: 'small',
            onClick: () => { this.runBenchmark(bench); }
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
