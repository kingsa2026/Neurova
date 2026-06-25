/**
 * GrowthPage - 成长记录页
 *
 * 职责：展示当前 Agent 在 5 个维度（知识/技能/情绪/社交/元认知）的成长记录，
 *       含维度概览卡（雷达图概览）和详细列表，支持按维度筛选、查看详情、编辑里程碑
 * 设计：
 *   - GrowthViewHelper（导出）：纯视图模型，封装维度颜色映射、维度图标映射、维度中文标签、
 *     等级格式化、经验进度计算、里程碑数文案，无 UI 运行时依赖，可独立单元测试；
 *   - GrowthPage（@Component）：Stack[Column[TopNavMenu(标题"成长记录"+返回+刷新)]
 *     + [维度概览卡（5 维度横向进度条）] + [维度筛选 Tab] + [加载态/空态/列表]
 *     + [详情弹窗] + [编辑里程碑弹窗]]；
 *     列表项 GlassCard 含维度徽章、等级（Lv.n）、经验值进度条、里程碑数量、
 *     最后更新时间、查看详情/编辑里程碑操作；
 *     详情弹窗内嵌 Stack 条件渲染（不单独建 CustomDialog 文件），
 *     展示维度、等级、经验、里程碑列表（bullets）；
 *     编辑里程碑弹窗含 milestones 多行文本域，保存调用 api.cognition.updateGrowth；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.cognition，状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（cognition.listGrowths/getGrowth/updateGrowth）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：GrowthRecord
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 加载当前 Agent 的成长记录；
 *   维度概览卡按 5 维度展示最新记录的等级与经验进度条；
 *   维度筛选 Tab 切换 → 本地 filterByDimension 过滤；
 *   查看详情按钮 → 弹出 Dialog 展示维度/等级/经验/里程碑列表；
 *   编辑里程碑按钮 → 弹出编辑 Dialog → 调用 api.cognition.updateGrowth → 刷新列表
 *
 * TDD：GrowthViewHelper 各方法按红绿灯垂直切片逐步实现，详见 GrowthPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { GrowthRecord } from '../libs/types';

/** 日志标签 */
const TAG = 'GrowthPage';

/** GrowthRecord 的 dimension 联合类型别名（简化方法签名） */
type GrowthDimension = GrowthRecord['dimension'];

/** 下一等级经验阈值（每级 100 经验值，线性增长） */
const NEXT_LEVEL_THRESHOLD = 100;

/** 全部维度（用于概览卡和筛选 Tab 顺序） */
const ALL_DIMENSIONS: GrowthDimension[] = ['knowledge', 'skill', 'emotion', 'social', 'meta'];

// ===========================================================================
// GrowthViewHelper - 成长视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class GrowthViewHelper {
  /**
   * 获取维度对应的颜色 token 名
   * 映射：knowledge→info, skill→primary, emotion→warning, social→success, meta→text_secondary
   * @param dimension 成长维度
   * @return StyleManager 颜色 token 名
   */
  static getDimensionColor(dimension: GrowthDimension): string {
    if (dimension === 'knowledge') return 'info';
    if (dimension === 'skill') return 'primary';
    if (dimension === 'emotion') return 'warning';
    if (dimension === 'social') return 'success';
    return 'text_secondary';
  }

  /**
   * 获取维度对应的图标 emoji
   * 映射：knowledge→📚, skill→🛠️, emotion→😊, social→🤝, meta→🧠
   * @param dimension 成长维度
   * @return emoji 字符串
   */
  static getDimensionIcon(dimension: GrowthDimension): string {
    if (dimension === 'knowledge') return '📚';
    if (dimension === 'skill') return '🛠️';
    if (dimension === 'emotion') return '😊';
    if (dimension === 'social') return '🤝';
    return '🧠';
  }

  /**
   * 获取维度对应的中文标签
   * 映射：knowledge→知识, skill→技能, emotion→情绪, social→社交, meta→元认知
   * @param dimension 成长维度
   * @return 中文标签
   */
  static getDimensionLabel(dimension: GrowthDimension): string {
    if (dimension === 'knowledge') return '知识';
    if (dimension === 'skill') return '技能';
    if (dimension === 'emotion') return '情绪';
    if (dimension === 'social') return '社交';
    return '元认知';
  }

  /**
   * 格式化等级为 "Lv.n"
   * @param level 等级数值
   * @return "Lv.n" 字符串
   */
  static formatLevel(level: number): string {
    return `Lv.${level}`;
  }

  /**
   * 计算到下一级的经验进度（0-1 百分比）
   * @param experience 当前经验值
   * @param threshold 下一级经验阈值
   * @return 0-1 之间的分数；阈值 ≤0 返回 0；超过阈值封顶 1
   */
  static calculateProgressToNext(experience: number, threshold: number): number {
    if (threshold <= 0) return 0;
    if (experience <= 0) return 0;
    const progress = experience / threshold;
    return Math.min(progress, 1);
  }

  /**
   * 获取里程碑数文案
   * @param count 里程碑数量
   * @return 0 → "无里程碑"，n → "里程碑 n 项"
   */
  static getMilestoneCount(count: number): string {
    if (count <= 0) return '无里程碑';
    return `里程碑 ${count} 项`;
  }
}

// ===========================================================================
// GrowthPage - 成长记录页组件
//
// 设计：Stack[Column[TopNavMenu + 概览卡 + 筛选 Tab + 主体] + 详情弹窗 + 编辑弹窗]；
//       数据流：aboutToAppear → api.cognition.listGrowths → 渲染；
//       概览卡按 5 维度取最新记录展示等级与经验进度条；
//       筛选 Tab 切换 → 本地 filterByDimension；
//       详情/编辑弹窗内嵌 Stack 条件渲染
// ===========================================================================

@Component
export struct GrowthPage {
  // 成长记录列表（由 API 加载）
  @State growths: GrowthRecord[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前筛选维度（null = 全部）
  @State activeDimension: GrowthDimension | null = null;
  // 详情弹窗可见性
  @State showDetail: boolean = false;
  // 编辑里程碑弹窗可见性
  @State showEdit: boolean = false;
  // 当前选中的成长记录（详情/编辑弹窗使用）
  @State selectedGrowth: GrowthRecord | null = null;
  // 编辑里程碑的多行文本（每行一条）
  @State editMilestonesText: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadGrowths();
  }

  /**
   * 加载当前 Agent 的成长记录
   * 流程：取 currentAgentId → 调用 api.cognition.listGrowths → 写入 growths
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadGrowths(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      if (!agentId) {
        this.growths = [];
        return;
      }
      const res = await this.api.cognition.listGrowths(agentId);
      if (res.code === 0 && res.data) {
        this.growths = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载成长记录失败', e as Error);
      this.msg.error('加载成长记录失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 刷新按钮回调：重新调用 loadGrowths
   */
  private handleRefresh(): void {
    this.loadGrowths();
  }

  /**
   * 切换维度筛选
   * 同一维度再次点击 → 取消筛选（null）
   */
  private handleDimensionFilter(dimension: GrowthDimension): void {
    this.activeDimension = this.activeDimension === dimension ? null : dimension;
  }

  /**
   * 获取经当前维度筛选后的列表
   */
  private getFilteredGrowths(): GrowthRecord[] {
    if (!this.activeDimension) return this.growths;
    return this.growths.filter(g => g.dimension === this.activeDimension);
  }

  /**
   * 获取指定维度的最新记录（按 updatedAt 降序取第一条）
   * 用于概览卡展示
   */
  private getLatestByDimension(dimension: GrowthDimension): GrowthRecord | null {
    const records = this.growths.filter(g => g.dimension === dimension);
    if (records.length === 0) return null;
    return records.slice().sort((a, b) => {
      const ta = new Date(a.updatedAt).getTime();
      const tb = new Date(b.updatedAt).getTime();
      return tb - ta;
    })[0];
  }

  /**
   * 打开详情弹窗
   */
  private openDetailDialog(growth: GrowthRecord): void {
    this.selectedGrowth = growth;
    this.showDetail = true;
  }

  /**
   * 关闭详情弹窗
   */
  private closeDetailDialog(): void {
    this.showDetail = false;
    this.selectedGrowth = null;
  }

  /**
   * 打开编辑里程碑弹窗
   * 将现有里程碑数组转为多行文本（每行一条）
   */
  private openEditDialog(growth: GrowthRecord): void {
    this.selectedGrowth = growth;
    this.editMilestonesText = growth.milestones.join('\n');
    this.showEdit = true;
  }

  /**
   * 关闭编辑里程碑弹窗
   */
  private closeEditDialog(): void {
    this.showEdit = false;
    this.selectedGrowth = null;
    this.editMilestonesText = '';
  }

  /**
   * 提交里程碑编辑
   * 流程：将多行文本拆分为数组 → 调用 api.cognition.updateGrowth → 成功后关闭弹窗 + 刷新
   * 异常：记录日志并提示用户
   */
  private async submitEditMilestones(): Promise<void> {
    if (!this.selectedGrowth) return;
    const milestones = this.splitLines(this.editMilestonesText);
    try {
      const res = await this.api.cognition.updateGrowth(this.selectedGrowth.id, { milestones });
      if (res.code === 0) {
        this.msg.success('更新成功');
        this.closeEditDialog();
        this.loadGrowths();
      } else {
        this.msg.error(res.message || '更新失败');
      }
    } catch (e) {
      this.logger.error(TAG, '更新成长记录失败', e as Error);
      this.msg.error('更新成长记录失败');
    }
  }

  /**
   * 将多行文本拆分为非空字符串数组（每行一条，自动 trim，过滤空行）
   */
  private splitLines(text: string): string[] {
    if (!text) return [];
    return text
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  /**
   * 格式化时间（YYYY-MM-DD HH:mm），无效值回退 '未知'
   */
  private formatTime(iso: string): string {
    if (!iso) return '未知';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack() {
      // ========== 主页面 ==========
      Column() {
        // 顶部导航栏：标题"成长记录" + 返回 + 刷新按钮（右侧插槽）
        TopNavMenu({
          title: '成长记录',
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
          // 加载态
          Column() {
            Text('加载中...')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.growths.length === 0) {
          // 空态
          Column() {
            Text('暂无成长记录')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
            GlassButton({
              text: '重新加载',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.handleRefresh(); }
            })
              .margin({ top: this.sm.getSpacing('md') })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 维度概览卡（5 维度横向进度条）
          this.buildOverviewCard()

          // 维度筛选 Tab（横向滚动胶囊：全部 + 5 维度）
          this.buildDimensionFilter()

          // 列表
          List({ space: 12 }) {
            ForEach(this.getFilteredGrowths(), (growth: GrowthRecord) => {
              ListItem() {
                this.buildGrowthCard(growth)
              }
            }, (growth: GrowthRecord) => growth.id)
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

      // ========== 详情弹窗 ==========
      if (this.showDetail && this.selectedGrowth !== null) {
        this.buildDetailDialog(this.selectedGrowth)
      }

      // ========== 编辑里程碑弹窗 ==========
      if (this.showEdit && this.selectedGrowth !== null) {
        this.buildEditDialog(this.selectedGrowth)
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 区块构建器
  // ===========================================================================

  /** 维度概览卡：5 维度横向进度条（每条显示等级和经验值） */
  @Builder
  buildOverviewCard() {
    GlassCard({ title: '维度概览' }) {
      Column() {
        ForEach(ALL_DIMENSIONS, (dim: GrowthDimension) => {
          this.buildDimensionBar(dim)
        }, (dim: GrowthDimension) => dim)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .padding({
      left: this.sm.getSpacing('md'),
      right: this.sm.getSpacing('md'),
      top: this.sm.getSpacing('sm'),
    })
  }

  /** 单个维度进度条行：图标 + 标签 + 等级 + 进度条 + 经验值 */
  @Builder
  buildDimensionBar(dim: GrowthDimension) {
    Row() {
      // 维度图标 + 中文标签
      Text(`${GrowthViewHelper.getDimensionIcon(dim)} ${GrowthViewHelper.getDimensionLabel(dim)}`)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_primary'))
        .width(80)

      // 等级
      Text(this.getLatestByDimension(dim) !== null
        ? GrowthViewHelper.formatLevel(this.getLatestByDimension(dim)!.level)
        : '-')
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(dim)))
        .width(50)

      // 进度条
      Row() {
        Row()
          .width(`${GrowthViewHelper.calculateProgressToNext(
            this.getLatestByDimension(dim)?.experience ?? 0,
            NEXT_LEVEL_THRESHOLD,
          ) * 100}%`)
          .height(6)
          .borderRadius(3)
          .backgroundColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(dim)))
      }
      .width('40%')
      .height(6)
      .borderRadius(3)
      .backgroundColor(this.sm.getColor('divider'))
      .alignItems(VerticalAlign.Start)
      .margin({ left: 8, right: 8 })

      // 经验值
      Text(this.getLatestByDimension(dim) !== null
        ? `${this.getLatestByDimension(dim)!.experience}/${NEXT_LEVEL_THRESHOLD}`
        : '-')
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_disabled'))
        .layoutWeight(1)
        .textAlign(TextAlign.End)
    }
    .width('100%')
    .padding({ top: 4, bottom: 4 })
    .alignItems(VerticalAlign.Center)
  }

  /** 维度筛选 Tab：横向滚动胶囊（全部 + 5 维度） */
  @Builder
  buildDimensionFilter() {
    Scroll() {
      Row({ space: 8 }) {
        // 全部
        Text('全部')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.activeDimension === null
            ? this.sm.getColor('text_on_primary')
            : this.sm.getColor('text_primary'))
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .borderRadius(16)
          .backgroundColor(this.activeDimension === null
            ? this.sm.getColor('primary')
            : Color.Transparent)
          .onClick(() => { this.activeDimension = null; })

        // 5 维度
        ForEach(ALL_DIMENSIONS, (dim: GrowthDimension) => {
          Text(GrowthViewHelper.getDimensionLabel(dim))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.activeDimension === dim
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.activeDimension === dim
              ? this.sm.getColor(GrowthViewHelper.getDimensionColor(dim))
              : Color.Transparent)
            .onClick(() => { this.handleDimensionFilter(dim); })
        }, (dim: GrowthDimension) => dim)
      }
      .padding({
        left: this.sm.getSpacing('md'),
        right: this.sm.getSpacing('md'),
        top: this.sm.getSpacing('sm'),
        bottom: this.sm.getSpacing('sm'),
      })
    }
    .scrollable(ScrollDirection.Horizontal)
    .scrollBar(BarState.Off)
    .width('100%')
  }

  /** 单条成长卡片：维度徽章 + 等级 + 经验进度条 + 里程碑数 + 更新时间 + 操作 */
  @Builder
  buildGrowthCard(growth: GrowthRecord) {
    GlassCard() {
      Column() {
        // 上部：维度徽章（emoji + 中文标签）+ 等级
        Row() {
          Text(`${GrowthViewHelper.getDimensionIcon(growth.dimension)} ${GrowthViewHelper.getDimensionLabel(growth.dimension)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(growth.dimension)))

          Text(GrowthViewHelper.formatLevel(growth.level))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(growth.dimension)))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 经验值进度条
        Row() {
          Row() {
            Row()
              .width(`${GrowthViewHelper.calculateProgressToNext(
                growth.experience,
                NEXT_LEVEL_THRESHOLD,
              ) * 100}%`)
              .height(6)
              .borderRadius(3)
              .backgroundColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(growth.dimension)))
          }
          .width('60%')
          .height(6)
          .borderRadius(3)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`${growth.experience}/${NEXT_LEVEL_THRESHOLD} EXP`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 底部行：里程碑数 + 更新时间
        Row() {
          Text(GrowthViewHelper.getMilestoneCount(growth.milestones.length))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))

          Text(this.formatTime(growth.updatedAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: this.sm.getSpacing('sm') })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '查看详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetailDialog(growth); }
          })
          GlassButton({
            text: '编辑里程碑',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openEditDialog(growth); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 条件渲染，不单独建文件）
  // ===========================================================================

  /** 详情弹窗：维度、等级、经验、里程碑列表（bullets） */
  @Builder
  buildDetailDialog(growth: GrowthRecord) {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      GlassCard({ title: '成长详情' }) {
        Scroll() {
          Column() {
            // 维度
            Text('维度')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`${GrowthViewHelper.getDimensionIcon(growth.dimension)} ${GrowthViewHelper.getDimensionLabel(growth.dimension)}`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 等级
            Text('等级')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(GrowthViewHelper.formatLevel(growth.level))
              .fontSize(this.sm.getFontSize('body'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor(GrowthViewHelper.getDimensionColor(growth.dimension)))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 经验值
            Text('经验值')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`${growth.experience}/${NEXT_LEVEL_THRESHOLD} (${Math.round(
              GrowthViewHelper.calculateProgressToNext(growth.experience, NEXT_LEVEL_THRESHOLD) * 100,
            )}%)`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 里程碑列表（bullets）
            Text(`里程碑（${growth.milestones.length}）`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('xs') })
            if (growth.milestones.length === 0) {
              Text('无里程碑')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .width('100%')
                .margin({ top: 4 })
            } else {
              Column() {
                ForEach(growth.milestones, (milestone: string, index: number) => {
                  Text(`• ${milestone}`)
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_primary'))
                    .width('100%')
                    .margin({ top: 2 })
                }, (milestone: string, index: number) => `${index}-${milestone}`)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
              .margin({ top: 4 })
            }

            // 更新时间
            Text(`更新时间：${this.formatTime(growth.updatedAt)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Off)

        // 底部按钮
        Row() {
          GlassButton({
            text: '关闭',
            type: 'default',
            size: 'medium',
            onClick: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('90%')
      .height('70%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('overlay_mask'))
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .onClick(() => { this.closeDetailDialog(); })
  }

  // ===========================================================================
  // 编辑里程碑弹窗构建器
  // ===========================================================================

  /** 编辑里程碑弹窗：milestones 多行文本域 + 保存按钮 */
  @Builder
  buildEditDialog(growth: GrowthRecord) {
    // 遮罩层：点击空白处关闭
    Column() {
      // 弹窗主体
      GlassCard({ title: '编辑里程碑' }) {
        Scroll() {
          Column() {
            // 维度信息
            Text(`${GrowthViewHelper.getDimensionIcon(growth.dimension)} ${GrowthViewHelper.getDimensionLabel(growth.dimension)} · ${GrowthViewHelper.formatLevel(growth.level)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ bottom: this.sm.getSpacing('sm') })

            // 里程碑多行文本域
            Text('里程碑（每行一条）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('info'))
              .width('100%')
            TextArea({
              placeholder: '每行一条里程碑...',
              text: this.editMilestonesText,
            })
              .width('100%')
              .height(200)
              .fontSize(this.sm.getFontSize('body'))
              .margin({ top: 4 })
              .onChange((v: string) => {
                this.editMilestonesText = v;
              })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Off)

        // 底部按钮：取消 + 保存
        Row() {
          GlassButton({
            text: '取消',
            type: 'default',
            size: 'medium',
            onClick: () => { this.closeEditDialog(); }
          })
          GlassButton({
            text: '保存',
            type: 'primary',
            size: 'medium',
            onClick: () => { this.submitEditMilestones(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('90%')
      .height('60%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('overlay_mask'))
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .onClick(() => { this.closeEditDialog(); })
  }
}
