/**
 * BenchmarkPage - 基准评测页（R6 接真实 API）
 *
 * 职责：展示评测套件列表（/v1/benchmark/suites），按分类筛选，触发运行，
 *       展示运行历史（/v1/benchmark/runs，诚实标注 simulated）
 * 设计：
 *   - BenchmarkViewHelper（导出）：纯视图模型，封装难度颜色/标签映射、
 *     运行状态颜色/图标/标签映射、延迟格式化（ms/s 转换，null → 未测量），
 *     无 UI 依赖，可独立单元测试；
 *   - BenchmarkPage（@Component）：Column [TopNavMenu(标题"基准评测"+返回)] +
 *     [category 筛选 Tab] + [套件列表（含运行按钮）] + [运行历史列表]；
 *   - 颜色统一走 StyleManager，路由走 Router，已接线 PageMap（P1-33）；
 *     数据源 BenchmarkApi（R6：替换 mock）。
 *
 * 契约说明（诚实缺省）：
 *   - 后端 benchmark.py 是 LLM 评测套件域（suite/run），不是旧 mock 的
 *     cpu/memory/disk 系统基准——页面契约随 BenchmarkApi 切换；
 *   - 评测执行器未接线（P6 诚实化）：/run 返回 status='simulated'、score/
 *     avg_latency_ms 恒 null，运行记录不编造分数——历史卡片如实渲染
 *     "模拟运行"，message 透传后端说明。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（api.benchmark.*）
 *   - ../libs/api/modules/BenchmarkApi：BenchmarkSuiteDto/BenchmarkRunDto 契约
 *   - ../routing/Router、../libs/style/StyleManager、../libs/logger/Logger、
 *     ../libs/message/MessageManager
 *
 * 用法：
 *   由 Router.push(RouteNames.BENCHMARK) 跳转进入；
 *   aboutToAppear 经 api.benchmark.suites()+runs() 加载；
 *   category 筛选 Tab 切换 → 本地过滤；
 *   运行按钮 → api.benchmark.run() → 透传后端 message（含"未接线"说明）→ 刷新历史。
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { BenchmarkSuiteDto, BenchmarkRunDto } from '../libs/api/modules/BenchmarkApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'BenchmarkPage';

/** 秒级阈值：≥1000ms 切换为秒格式 */
const SECONDS_THRESHOLD_MS = 1000;

// ===========================================================================
// BenchmarkViewHelper - 基准评测视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class BenchmarkViewHelper {
  /**
   * 获取套件难度对应的颜色 token 名（未知兜 'info'——后端 difficulty 开放集合）
   * 映射：easy→success、medium→warning、hard→error
   * @param difficulty 难度
   * @return StyleManager 颜色 token 名
   */
  static getDifficultyColor(difficulty: string): string {
    if (difficulty === 'easy') return 'success';
    if (difficulty === 'medium') return 'warning';
    if (difficulty === 'hard') return 'error';
    return 'info';
  }

  /**
   * 获取套件难度对应的中文标签（未知原样返回）
   * 映射：easy→简单、medium→中等、hard→困难
   * @param difficulty 难度
   * @return 中文文案
   */
  static getDifficultyLabel(difficulty: string): string {
    if (difficulty === 'easy') return '简单';
    if (difficulty === 'medium') return '中等';
    if (difficulty === 'hard') return '困难';
    return difficulty;
  }

  /**
   * 获取运行状态对应的颜色 token 名（未知兜 'text_secondary'）
   * 映射：simulated→warning、running→info、completed→success、failed→error
   * @param status 运行状态（后端 'simulated' = 评测执行器未接线的诚实标记）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: string): string {
    if (status === 'simulated') return 'warning';
    if (status === 'running') return 'info';
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'error';
    return 'text_secondary';
  }

  /**
   * 获取运行状态对应的图标 emoji（未知兜 '⏳'）
   * @param status 运行状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: string): string {
    if (status === 'simulated') return '🧪';
    if (status === 'running') return '⚡';
    if (status === 'completed') return '✅';
    if (status === 'failed') return '❌';
    return '⏳';
  }

  /**
   * 获取运行状态对应的中文标签（未知原样返回）
   * @param status 运行状态
   * @return 中文文案
   */
  static getStatusLabel(status: string): string {
    if (status === 'simulated') return '模拟运行';
    if (status === 'running') return '运行中';
    if (status === 'completed') return '已完成';
    if (status === 'failed') return '失败';
    return status;
  }

  /**
   * 格式化延迟时间（null/undefined = 后端未接线未测量 → '未测量'）
   * 规则：< 1000ms → 'X.Xms'；≥ 1000ms → 'X.Xs'
   * @param ms 延迟毫秒数（可为 null）
   * @return 格式化延迟字符串
   */
  static formatLatency(ms: number | null): string {
    if (ms === null || ms === undefined) return '未测量';
    if (ms < SECONDS_THRESHOLD_MS) {
      return `${ms.toFixed(1)}ms`;
    }
    const seconds = ms / SECONDS_THRESHOLD_MS;
    return `${seconds.toFixed(1)}s`;
  }

  /**
   * 格式化得分（null = 未接线未测量 → '未测量'）
   * @param score 得分（可为 null）
   * @return 得分展示字符串
   */
  static formatScore(score: number | null): string {
    if (score === null || score === undefined) return '未测量';
    return `${score}`;
  }

  /**
   * 格式化 ISO 时间戳为短格式 YYYY-MM-DD HH:mm（历史卡片右上角用）
   * 规则：无值/无效 → '—'
   * @param timestamp ISO 时间戳字符串
   * @return 格式化时间或 '—'
   */
  static formatTimestampShort(timestamp: string): string {
    if (!timestamp || timestamp.length === 0) return '—';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '—';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const HH = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
  }
}

/** 分类筛选 Tab 配置 */
interface CategoryFilterOption {
  value: string;
  label: string;
}

/** 分类筛选 Tab 列表（后端 _SUITES category 值域） */
const CATEGORY_FILTERS: CategoryFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'memory', label: '记忆' },
  { value: 'creative', label: '创作' },
  { value: 'multimodal', label: '多模态' },
];

@Component
export struct BenchmarkPage {
  // 评测套件列表（api.benchmark.suites()）
  @State suites: BenchmarkSuiteDto[] = [];
  // 运行历史（api.benchmark.runs()）
  @State runs: BenchmarkRunDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的分类筛选
  @State activeCategory: string = 'all';
  // 运行中的套件 id（防重复触发）
  @State runningSuiteId: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadAll();
  }

  /**
   * 加载套件与运行历史
   */
  private async loadAll(): Promise<void> {
    this.loading = true;
    try {
      const suitesRes = await this.api.benchmark.suites();
      if (suitesRes.code === 0 && suitesRes.data) {
        this.suites = suitesRes.data;
      } else {
        this.suites = [];
      }
      await this.loadRuns();
    } catch (e) {
      this.logger.error(TAG, '加载基准数据失败', e as Error);
      this.msg.error('加载基准评测数据失败');
      this.suites = [];
      this.runs = [];
    } finally {
      this.loading = false;
    }
  }

  /** 加载运行历史（失败不打断套件展示） */
  private async loadRuns(): Promise<void> {
    try {
      const runsRes = await this.api.benchmark.runs();
      if (runsRes.code === 0 && runsRes.data) {
        this.runs = runsRes.data.items;
      } else {
        this.runs = [];
      }
    } catch (e) {
      this.logger.warn(TAG, '加载运行历史失败');
      this.runs = [];
    }
  }

  /** 切换分类筛选 */
  private switchCategory(value: string): void {
    this.activeCategory = value;
  }

  /** 获取经分类筛选后的套件列表 */
  private getFilteredSuites(): BenchmarkSuiteDto[] {
    if (this.activeCategory === 'all') {
      return this.suites;
    }
    return this.suites.filter((s: BenchmarkSuiteDto) => s.category === this.activeCategory);
  }

  /**
   * 触发运行评测套件（POST /v1/benchmark/run）
   * 后端 P6 诚实化：执行器未接线，返回 simulated 运行记录——message 透传
   */
  private async runSuite(suite: BenchmarkSuiteDto): Promise<void> {
    if (this.runningSuiteId.length > 0) {
      return;
    }
    this.runningSuiteId = suite.id;
    try {
      const res = await this.api.benchmark.run({ suite_id: suite.id });
      if (res.code === 0) {
        this.msg.info(res.message && res.message.length > 0 ? res.message : `已触发: ${suite.name}`);
        await this.loadRuns();
        // N3 真执行器：run 返回 status=running（后台执行+GET /runs/{run_id} 状态
        // 查询）——延迟刷新两次历史以透出终态与真实分数（3s/8s 覆盖轻量 suite）。
        if (res.data !== null && res.data !== undefined && res.data.status === 'running') {
          setTimeout(() => { this.loadRuns(); }, 3000);
          setTimeout(() => { this.loadRuns(); }, 8000);
        }
      } else {
        this.msg.error(res.message && res.message.length > 0 ? res.message : '运行评测失败');
      }
    } catch (e) {
      this.logger.error(TAG, '运行评测失败', e as Error);
      this.msg.error('运行评测失败');
    } finally {
      this.runningSuiteId = '';
    }
  }

  build() {
    Column() {
      // 顶部导航栏：标题"基准评测" + 返回
      TopNavMenu({
        title: '基准评测',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 分类筛选 Tab
      Scroll() {
        Row({ space: 8 }) {
          ForEach(CATEGORY_FILTERS, (opt: CategoryFilterOption) => {
            Text(opt.label)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeCategory === opt.value
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_secondary'))
              .backgroundColor(this.activeCategory === opt.value
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .onClick(() => { this.switchCategory(opt.value); })
          }, (opt: CategoryFilterOption) => opt.value)
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
      } else if (this.getFilteredSuites().length === 0 && this.runs.length === 0) {
        Column() {
          Text('暂无评测数据')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          // 套件段
          ForEach(this.getFilteredSuites(), (suite: BenchmarkSuiteDto) => {
            ListItem() {
              this.buildSuiteCard(suite)
            }
          }, (suite: BenchmarkSuiteDto) => suite.id)
          // 运行历史段
          ForEach(this.runs, (run: BenchmarkRunDto) => {
            ListItem() {
              this.buildRunCard(run)
            }
          }, (run: BenchmarkRunDto) => run.run_id)
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
  // 卡片构建器
  // ===========================================================================

  /** 套件卡片：难度徽章 + 名称 + 描述 + 任务数/分类 + 运行按钮 */
  @Builder
  buildSuiteCard(suite: BenchmarkSuiteDto) {
    GlassCard() {
      Column() {
        // 上部：难度徽章 + 任务数
        Row() {
          Row() {
            Text(BenchmarkViewHelper.getDifficultyLabel(suite.difficulty))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor(BenchmarkViewHelper.getDifficultyColor(suite.difficulty)))

          Text(`${suite.tasks} 个任务 · ${suite.category}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 套件名
        Text(suite.name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 描述
        Text(suite.description)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 运行按钮
        Row() {
          GlassButton({
            text: this.runningSuiteId === suite.id ? '运行中' : '运行',
            type: this.runningSuiteId === suite.id ? 'default' : 'primary',
            btnSize: 'small',
            onTap: () => { this.runSuite(suite); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('md') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }

  /** 运行历史卡片：状态徽章 + 套件名 + 得分/延迟（未接线如实标注）+ 时间 */
  @Builder
  buildRunCard(run: BenchmarkRunDto) {
    GlassCard() {
      Column() {
        // 上部：状态徽章 + 开始时间
        Row() {
          Row() {
            Text(BenchmarkViewHelper.getStatusIcon(run.status))
              .fontSize(14)
            Text(BenchmarkViewHelper.getStatusLabel(run.status))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(BenchmarkViewHelper.getStatusColor(run.status)))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(this.sm.getRadius('sm'))
          .backgroundColor(this.sm.getColor('surface'))

          Text(BenchmarkViewHelper.formatTimestampShort(run.started_at))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .margin({ left: 8 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 套件名
        Text(run.suite_name)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 得分 + 延迟（执行器未接线时如实显示"未测量"）
        Row() {
          Text(`得分: ${BenchmarkViewHelper.formatScore(run.score)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('primary'))
            .layoutWeight(1)
          Text(`延迟: ${BenchmarkViewHelper.formatLatency(run.avg_latency_ms)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
  }
}
