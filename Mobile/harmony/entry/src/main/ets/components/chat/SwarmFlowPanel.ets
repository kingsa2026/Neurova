/**
 * SwarmFlowPanel - 蜂群协作过程视图（车道F，对齐 PC 端 SwarmFlowPanel.vue）
 *
 * 职责：拉取当前会话的蜂群协作图投影（GET /console/chat/runs/{sid}/graph）与
 *       候选板投影（GET /console/chat/runs/{sid}/candidates），渲染**简化分层拓扑**：
 *       run 节点按 depth 分层横排（与后端投影同序：depth, started_at, id），
 *       spawn/dependency 边以层间连接区的 Path 命令串（数值坐标）连线表达，
 *       审批/候选卡以徽标卡横排呈现；状态着色对齐 PC 端
 *       RUN_STATUS_TONE / CANDIDATE_STATUS_TONE / APPROVAL_TONE 词汇（语义令牌，无硬编码色值）。
 *
 * 数据纪律（对齐 PC ChatPage.refreshSwarmGraph）：
 *   - 换会话先清旧投影再拉（过期响应不写当前视图）；
 *   - 图读面失败（含 run 台账关闭 503）fail-soft → 错误态 + 重试按钮，不崩页面；
 *   - 候选板为辅，失败静默降级（图为主）。
 *
 * 增量刷新（诚实说明）：移动端 WS（/v1/mobile/ws，mobile_ws_ledger 帧型）**不转发**
 * subagent_started/subagent_completed 事件（那是 PC /sync 通道词汇）；本面板的增量
 * 信号由 ChatPage 借道 chat:done（回合终结 → refreshTick 自增）触发静默重拉，
 * 另有会话切换（sessionId）与手动重试两条路径。
 *
 * 已知坑规避：ForEach 条目 key 带版本号 fetchSeq（对象复用滞留渲染）；
 * Scroll 显式 .scrollable(Horizontal)（缺它横向不可滚）；Line 的 Point 元组过不了
 * ArkTS → 连线一律 Path commands 数值坐标；数组 State 一律归一化兜底 ?? []。
 */

import { ApiFacade } from '../../libs/api/ApiFacade';
import { StyleManager } from '../../libs/style/StyleManager';
import { I18nManager } from '../../libs/i18n/I18nManager';
import { Logger } from '../../libs/logger/Logger';
import { AppIcon } from '../common/AppIcon';
import { swarmHasCollab } from './SwarmFlowGate';
import {
  SwarmGraphResult,
  SwarmGraphNode,
  SwarmGraphEdge,
  CandidateBoardResult,
} from '../../libs/api/modules/ConsoleApi';

/** 日志标签 */
const TAG = 'SwarmFlowPanel';

// ---------------------------------------------------------------------------
// 布局常量（vp；数值坐标供 Path 命令串使用）
// ---------------------------------------------------------------------------
const NODE_W = 132;      // 节点卡宽
const NODE_H = 62;       // 节点卡高
const H_GAP = 30;        // 同层节点水平间距
const CONN_H = 22;       // 层间连接区高
const LAYER_V_GAP = 4;   // 层间额外间距
const TOPO_MAX_H = 300;  // 拓扑区最大高（超出纵向滚动）
const BADGE_W = 196;     // 徽标卡宽

/** 拓扑层：同 depth 的 run 节点横排 + 层上方连接区的边 Path 命令串 */
interface TopoLayer {
  depth: number;
  cells: TopoCell[];
  spawnPath: string;
  depPath: string;
}

/** 层内单元：节点 + 其中心 x（内容坐标系） */
interface TopoCell {
  node: SwarmGraphNode;
  centerX: number;
}

// ===========================================================================
// SwarmFlowLayout - 分层布局纯函数（无 UI 依赖，可独立测试）
// ===========================================================================

export class SwarmFlowLayout {
  /**
   * 投影 → 分层布局。run 节点按 (depth, started_at, id) 排序（与后端
   * buildSwarmGraph 同序：父先于子、布局稳定）；spawn/dependency 边画在
   * 目标层上方的连接区（跨层边也画在该区，简化分层图惯例）。
   */
  static buildLayers(nodes: SwarmGraphNode[], edges: SwarmGraphEdge[]): TopoLayer[] {
    const runs: SwarmGraphNode[] = [];
    for (const n of nodes) {
      if (n.nodeType === 'run') {
        runs.push(n);
      }
    }
    runs.sort((a: SwarmGraphNode, b: SwarmGraphNode): number => {
      if (a.depth !== b.depth) {
        return a.depth - b.depth;
      }
      if (a.started_at !== b.started_at) {
        return a.started_at - b.started_at;
      }
      return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0);
    });

    // 分层（保持排序内的同层次序）
    const depthKeys: number[] = [];
    const byDepth = new Map<number, SwarmGraphNode[]>();
    for (const n of runs) {
      let arr = byDepth.get(n.depth);
      if (arr === undefined) {
        arr = [];
        byDepth.set(n.depth, arr);
        depthKeys.push(n.depth);
      }
      arr.push(n);
    }
    depthKeys.sort((a: number, b: number): number => a - b);

    // 坐标：层内第 j 个节点 centerX = j*(NODE_W+H_GAP) + NODE_W/2（与渲染 Row 对齐）
    const posById = new Map<string, number>();
    const layerIndexById = new Map<string, number>();
    const layers: TopoLayer[] = [];
    for (const depth of depthKeys) {
      const arr = byDepth.get(depth) as SwarmGraphNode[];
      const cells: TopoCell[] = [];
      for (let j = 0; j < arr.length; j++) {
        const cx = j * (NODE_W + H_GAP) + NODE_W / 2;
        posById.set(arr[j].id, cx);
        const cell: TopoCell = { node: arr[j], centerX: cx };
        cells.push(cell);
      }
      const layer: TopoLayer = { depth: depth, cells: cells, spawnPath: '', depPath: '' };
      layers.push(layer);
    }
    for (let i = 0; i < layers.length; i++) {
      for (const c of layers[i].cells) {
        layerIndexById.set(c.node.id, i);
      }
    }

    // 边 → 目标层连接区命令串（M x1 0 L x2 CONN_H；端点缺位=悬空边，投影 meta 已计数，此处不画）
    for (const e of edges) {
      if (e.type !== 'spawn' && e.type !== 'dependency') {
        continue;
      }
      const fromX = posById.get(e.from);
      const toX = posById.get(e.to);
      const fromLayer = layerIndexById.get(e.from);
      const toLayer = layerIndexById.get(e.to);
      if (fromX === undefined || toX === undefined
        || fromLayer === undefined || toLayer === undefined) {
        continue;
      }
      if (toLayer <= fromLayer) {
        continue;
      }
      const target = layers[toLayer];
      const seg = `M ${fromX} 0 L ${toX} ${CONN_H}`;
      if (e.type === 'dependency') {
        target.depPath = target.depPath.length > 0 ? `${target.depPath} ${seg}` : seg;
      } else {
        target.spawnPath = target.spawnPath.length > 0 ? `${target.spawnPath} ${seg}` : seg;
      }
    }
    return layers;
  }

  /** 拓扑内容总宽（各层等宽，保证层间列对齐） */
  static contentWidth(layers: TopoLayer[]): number {
    let maxCols = 1;
    for (const l of layers) {
      maxCols = Math.max(maxCols, l.cells.length);
    }
    return maxCols * (NODE_W + H_GAP);
  }

  /** 拓扑内容总高（首层无连接区） */
  static contentHeight(layers: TopoLayer[]): number {
    if (layers.length === 0) {
      return 0;
    }
    return layers.length * (CONN_H + NODE_H + LAYER_V_GAP) - LAYER_V_GAP;
  }
}

// ===========================================================================
// SwarmFlowTone - 状态着色词汇（对齐 PC SwarmFlowPanel.vue 的三张 tone 表）
// ===========================================================================

export class SwarmFlowTone {
  /** 台账/蜂群 run 状态 → 基调（未知回落 running，与 PC 一致） */
  static runTone(status: string): string {
    if (status === 'completed') {
      return 'completed';
    }
    if (status === 'failed' || status === 'cancelled') {
      return 'failed';
    }
    return 'running'; // queued/pending/parked/running/in_review/未知
  }

  /** 候选状态 → 基调（键集=候选状态域四值） */
  static candidateTone(status: string): string {
    if (status === 'accepted') {
      return 'completed';
    }
    if (status === 'rejected') {
      return 'failed';
    }
    if (status === 'reviseRequired') {
      return 'warning';
    }
    return 'running'; // submitted/未知
  }

  /** 审批裁决态 → 基调 */
  static approvalTone(status: string): string {
    if (status === 'approved') {
      return 'completed';
    }
    if (status === 'rejected') {
      return 'failed';
    }
    return 'running'; // pending/未知
  }

  /** 节点（含卡节点）→ 基调 */
  static nodeTone(node: SwarmGraphNode): string {
    if (node.nodeType === 'approval') {
      return SwarmFlowTone.approvalTone(node.status);
    }
    if (node.nodeType === 'candidate') {
      return SwarmFlowTone.candidateTone(node.status);
    }
    return SwarmFlowTone.runTone(node.status);
  }
}

// ===========================================================================
// SwarmFlowPanel - 组件
// ===========================================================================

@Component
export struct SwarmFlowPanel {
  /** 当前会话 ID（换会话触发清图重拉） */
  @Prop @Watch('onSessionIdChanged') sessionId: string = '';
  /** 结构性刷新信号（ChatPage 在 chat:done 时自增；移动端 WS 无 subagent_* 帧的替代增量） */
  @Prop @Watch('onTickChanged') refreshTick: number = 0;
  /** 有无协作变化回调：驱动 ChatPage 浮动图标显隐（无协作则入口一并不出现） */
  onHasCollabChange: (has: boolean) => void = (_has: boolean) => {};
  /** 折叠回调：面板展开后由头部收起钮触发（回到浮动图标形态） */
  onCollapse: () => void = () => {};

  @State loading: boolean = false;
  @State failed: boolean = false;
  @State errorMessage: string = '';
  @State graph: SwarmGraphResult | null = null;
  @State candidates: CandidateBoardResult | null = null;
  /** 分层布局（每次投影落位整体替换，驱动 ForEach 重建） */
  @State layers: TopoLayer[] = [];
  /** 审批/候选卡节点（整体替换） */
  @State cardNodes: SwarmGraphNode[] = [];
  @State contentW: number = NODE_W;
  /** 拉取版本号：进 ForEach key 强制重建条目（防对象复用滞留渲染） */
  @State fetchSeq: number = 0;

  private api = ApiFacade.getInstance();
  private sm = StyleManager.getInstance();
  private i18n = I18nManager.getInstance();
  private logger = Logger.getInstance();
  /** 上次外发的有无协作值（去重，避免父级 @State 被同值反复置位） */
  private lastEmittedHas: boolean = false;

  aboutToAppear(): void {
    this.refresh(false);
  }

  onSessionIdChanged(): void {
    // 换会话：旧图先清（对齐 PC「过期响应不写当前视图」纪律），再全量拉
    this.graph = null;
    this.candidates = null;
    this.layers = [];
    this.cardNodes = [];
    this.fetchSeq++;
    this.syncHasCollab();
    this.refresh(false);
  }

  onTickChanged(): void {
    // 回合终结等结构性信号：静默重拉，旧图保留到新图落位（不闪空）
    this.refresh(true);
  }

  /** 拉取图 + 候选板；silent=true 不进加载态（增量刷新不闪空） */
  private async refresh(silent: boolean): Promise<void> {
    const sid = this.sessionId;
    if (sid.length === 0) {
      this.graph = null;
      this.candidates = null;
      this.layers = [];
      this.cardNodes = [];
      this.syncHasCollab();
      return;
    }
    if (!silent) {
      this.loading = true;
    }
    this.failed = false;
    this.errorMessage = '';
    try {
      const res = await this.api.console.fetchSwarmRunGraph(sid);
      if (this.sessionId !== sid) {
        return; // 过期响应：会话已切走，不写当前视图
      }
      if (res.code === 0 && res.data) {
        this.graph = res.data;
        this.applyProjection();
      } else {
        this.failed = true;
        this.errorMessage = res.message;
      }
    } catch (e) {
      this.logger.warn(TAG, `协作图拉取失败: sid=${sid}`, e as Error);
      if (this.sessionId !== sid) {
        return;
      }
      this.failed = true;
      this.errorMessage = (e as Error).message;
    } finally {
      if (this.sessionId === sid) {
        this.loading = false;
      }
    }
    // 候选板为辅：失败静默降级（不覆盖图，不进错误态）
    try {
      const cand = await this.api.console.fetchSwarmRunCandidates(sid);
      if (this.sessionId === sid && cand.code === 0 && cand.data) {
        this.candidates = cand.data;
      }
    } catch (e) {
      this.logger.warn(TAG, '候选板拉取失败（降级为仅图）', e as Error);
      if (this.sessionId === sid) {
        this.candidates = null;
      }
    }
  }

  /** 投影落位：重算分层布局与卡节点（数组整体替换驱动渲染） */
  private applyProjection(): void {
    const g = this.graph;
    if (g === null) {
      this.layers = [];
      this.cardNodes = [];
      return;
    }
    const nodes = g.nodes ?? [];
    this.layers = SwarmFlowLayout.buildLayers(nodes, g.edges ?? []);
    const cards: SwarmGraphNode[] = [];
    for (const n of nodes) {
      if (n.nodeType !== 'run') {
        cards.push(n);
      }
    }
    this.cardNodes = cards;
    this.contentW = SwarmFlowLayout.contentWidth(this.layers);
    this.fetchSeq++;
    this.syncHasCollab();
  }

  /** 有无协作外发（去重）：run 节点或审批/候选卡任一存在即有协作 */
  private syncHasCollab(): void {
    const has = swarmHasCollab(this.runCount(), this.cardNodes.length);
    if (has !== this.lastEmittedHas) {
      this.lastEmittedHas = has;
      this.onHasCollabChange(has);
    }
  }

  private retry(): void {
    this.refresh(false);
  }

  /** 基调 → 语义色 token 值（全走 StyleManager，无硬编码色值） */
  private toneColor(tone: string): string {
    if (tone === 'completed') {
      return this.sm.getColor('success');
    }
    if (tone === 'failed') {
      return this.sm.getColor('error');
    }
    if (tone === 'running' || tone === 'warning') {
      return this.sm.getColor('warning');
    }
    return this.sm.getColor('text_secondary');
  }

  private runCount(): number {
    const g = this.graph;
    if (g === null) {
      return 0;
    }
    let c = 0;
    for (const n of (g.nodes ?? [])) {
      if (n.nodeType === 'run') {
        c++;
      }
    }
    return c;
  }

  private edgeCount(): number {
    const g = this.graph;
    if (g === null) {
      return 0;
    }
    const meta = g.meta;
    if (meta && meta.counts && meta.counts['edges'] !== undefined) {
      return meta.counts['edges'] as number;
    }
    return (g.edges ?? []).length;
  }

  private revision(): number {
    const g = this.graph;
    if (g === null) {
      return 0;
    }
    return g.meta ? g.meta.revision : 0;
  }

  build() {
    Column() {
      // 头部：标题 + 摘要（Span 组装本地化摘要行）
      Row() {
        Text(this.i18n.t('swarm_title'))
          .fontSize(this.sm.getFontSize('card_title'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
        Blank()
        Text() {
          Span(`${this.runCount()} `)
          Span(this.i18n.t('swarm_members_unit'))
          Span(` · ${this.edgeCount()} `)
          Span(this.i18n.t('swarm_edges_unit'))
          Span(` · ${this.revision()}`)
        }
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_secondary'))

        // 收起钮：面板由浮动图标展开而来，此处回到图标形态（面板仅展开态可见）
        Row() {
          AppIcon({ name: 'back', iconSize: 12, color: this.sm.getColor('text_secondary') })
            .rotate({ angle: 90 })
        }
        .width(24)
        .height(24)
        .borderRadius(12)
        .border({ width: 1, color: this.sm.getColor('border') })
        .justifyContent(FlexAlign.Center)
        .alignItems(VerticalAlign.Center)
        .margin({ left: 8 })
        .onClick(() => { this.onCollapse(); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      // 诚实标注（P2-4 meta 契约）：截断 / 候选账本缺事件
      if (this.graph !== null && this.graph.meta && this.graph.meta.truncated) {
        Text(this.i18n.t('swarm_truncated_hint'))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('warning'))
          .margin({ top: 4 })
      }
      if (this.graph !== null && this.graph.meta && this.graph.meta.candidates_incomplete) {
        Text(this.i18n.t('swarm_incomplete_hint'))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
      }

      // 图例（spawn/dependency/approval/candidate 四色）
      Row({ space: 14 }) {
        Row() {
          Divider().strokeWidth(2).color(this.sm.getColor('primary')).width(18)
          Text(this.i18n.t('swarm_legend_spawn'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 5 })
        }
        .alignItems(VerticalAlign.Center)
        Row() {
          Divider().strokeWidth(2).color(this.sm.getColor('text_secondary')).width(18)
          Text(this.i18n.t('swarm_legend_dependency'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 5 })
        }
        .alignItems(VerticalAlign.Center)
        Row() {
          Divider().strokeWidth(2).color(this.sm.getColor('warning')).width(18)
          Text(this.i18n.t('swarm_legend_approval'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 5 })
        }
        .alignItems(VerticalAlign.Center)
        Row() {
          Divider().strokeWidth(2).color(this.sm.getColor('accent')).width(18)
          Text(this.i18n.t('swarm_legend_candidate'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 5 })
        }
        .alignItems(VerticalAlign.Center)
      }
      .margin({ top: 8 })

      // 主体：加载 / 失败 / 空态 / 拓扑+徽标卡
      if (this.loading) {
        Row() {
          LoadingProgress()
            .width(16)
            .height(16)
            .color(this.sm.getColor('accent'))
          Text(this.i18n.t('common_loading'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
        }
        .width('100%')
        .justifyContent(FlexAlign.Center)
        .margin({ top: 18, bottom: 18 })
      } else if (this.failed) {
        Column({ space: 6 }) {
          Text(this.i18n.t('swarm_load_failed'))
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('error'))
          if (this.errorMessage.length > 0) {
            Text(this.errorMessage)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_tertiary'))
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          Row() {
            Text(this.i18n.t('common_retry'))
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('primary'))
          }
          .padding({ left: 14, right: 14, top: 7, bottom: 7 })
          .borderRadius(999)
          .border({ width: 1, color: this.sm.getColor('primary') })
          .margin({ top: 4 })
          .onClick(() => { this.retry(); })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Center)
        .margin({ top: 14, bottom: 14 })
      } else if (this.graph !== null && this.runCount() === 0 && this.cardNodes.length === 0) {
        // 诚实空态：本会话无蜂群协作运行
        Text(this.i18n.t('swarm_empty'))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
          .textAlign(TextAlign.Center)
          .margin({ top: 16, bottom: 16 })
      } else if (this.graph !== null) {
        // 拓扑区：外层纵向滚动兜底超高，内层横向滚动保证层间列对齐
        Scroll() {
          Scroll() {
            Column() {
              ForEach(this.layers, (layer: TopoLayer, idx: number) => {
                Column() {
                  // 层间连接区：spawn/dependency 边（Path 数值坐标）
                  if (idx > 0) {
                    Stack({ alignContent: Alignment.TopStart }) {
                      if (layer.spawnPath.length > 0) {
                        Path()
                          .commands(layer.spawnPath)
                          .fillOpacity(0)
                          .stroke(this.sm.getColor('primary'))
                          .strokeWidth(1.5)
                          .width(this.contentW)
                          .height(CONN_H)
                      }
                      if (layer.depPath.length > 0) {
                        Path()
                          .commands(layer.depPath)
                          .fillOpacity(0)
                          .stroke(this.sm.getColor('text_secondary'))
                          .strokeWidth(1.5)
                          .width(this.contentW)
                          .height(CONN_H)
                      }
                    }
                    .width(this.contentW)
                    .height(CONN_H)
                    .margin({ bottom: LAYER_V_GAP })
                  }
                  // 节点行（固定列宽，与布局坐标系一致）
                  Row({ space: H_GAP }) {
                    ForEach(layer.cells, (cell: TopoCell) => {
                      this.buildNodeCard(cell)
                    }, (cell: TopoCell) => `${cell.node.id}#${this.fetchSeq}`)
                  }
                  .width(this.contentW)
                  .height(NODE_H)
                  .alignItems(VerticalAlign.Top)
                }
                .alignItems(HorizontalAlign.Start)
              }, (layer: TopoLayer) => `${layer.depth}#${this.fetchSeq}`)
            }
            .alignItems(HorizontalAlign.Start)
          }
          .scrollable(ScrollDirection.Horizontal) // 坑：缺它横向不可滚
          .width('100%')
        }
        .scrollable(ScrollDirection.Vertical)
        .width('100%')
        .height(Math.min(SwarmFlowLayout.contentHeight(this.layers), TOPO_MAX_H))
        .margin({ top: 8 })

        // 审批/候选徽标卡（挂源 run 的从属信息，横排）
        if (this.cardNodes.length > 0) {
          Scroll() {
            Row({ space: 8 }) {
              ForEach(this.cardNodes, (node: SwarmGraphNode) => {
                this.buildCardBadge(node)
              }, (node: SwarmGraphNode) => `${node.id}#${this.fetchSeq}`)
            }
            .alignItems(VerticalAlign.Center)
          }
          .scrollable(ScrollDirection.Horizontal)
          .width('100%')
          .margin({ top: 8 })
        }
      }
    }
    .width('100%')
    .padding(12)
    .borderRadius(14)
    .backgroundColor(this.sm.getColor('glass'))
    .border({ width: 1, color: this.sm.getColor('border') })
    .alignItems(HorizontalAlign.Start)
  }

  // ===========================================================================
  // 子构建器
  // ===========================================================================

  /** run 节点卡：成员名 + 外部徽标 + 状态（基调色） + 深度 */
  @Builder
  buildNodeCard(cell: TopoCell) {
    Column() {
      Row() {
        Text(cell.node.member_name.length > 0 ? cell.node.member_name : cell.node.id)
          .fontSize(this.sm.getFontSize('caption'))
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        if (cell.node.kind === 'external') {
          Text(this.i18n.t('swarm_external_badge'))
            .fontSize(this.sm.getFontSize('badge'))
            .fontColor(this.sm.getColor('accent'))
            .border({ width: 1, color: this.sm.getColor('accent') })
            .borderRadius(8)
            .padding({ left: 4, right: 4 })
            .margin({ left: 4 })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text(cell.node.status)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.toneColor(SwarmFlowTone.nodeTone(cell.node)))
        .maxLines(1)
        .margin({ top: 3 })

      Text(`D${cell.node.depth}`)
        .fontSize(this.sm.getFontSize('badge'))
        .fontColor(this.sm.getColor('text_tertiary'))
        .margin({ top: 2 })
    }
    .width(NODE_W)
    .height(NODE_H)
    .padding(7)
    .borderRadius(10)
    .border({ width: 1, color: this.toneColor(SwarmFlowTone.nodeTone(cell.node)) })
    .backgroundColor(this.sm.getColor('surface'))
    .alignItems(HorizontalAlign.Start)
  }

  /** 审批/候选徽标卡：类型 + 级别 + 状态 + 摘要（左缘基调色条） */
  @Builder
  buildCardBadge(node: SwarmGraphNode) {
    Row() {
      Text(node.nodeType === 'approval'
        ? this.i18n.t('swarm_legend_approval')
        : this.i18n.t('swarm_legend_candidate'))
        .fontSize(this.sm.getFontSize('badge'))
        .fontWeight(FontWeight.Medium)
        .fontColor(this.toneColor(SwarmFlowTone.nodeTone(node)))
      if (node.level.length > 0) {
        Text(node.level)
          .fontSize(this.sm.getFontSize('badge'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ left: 4 })
      }
      Text(node.status.length > 0 ? node.status : '-')
        .fontSize(this.sm.getFontSize('badge'))
        .fontColor(this.toneColor(SwarmFlowTone.nodeTone(node)))
        .margin({ left: 4 })
      Text(this.badgeSummary(node))
        .fontSize(this.sm.getFontSize('badge'))
        .fontColor(this.sm.getColor('text_secondary'))
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ left: 6 })
        .layoutWeight(1)
    }
    .width(BADGE_W)
    .padding({ left: 8, right: 10, top: 6, bottom: 6 })
    .borderRadius(8)
    .backgroundColor(this.sm.getColor('surface'))
    .border({ width: { left: 3 }, color: this.toneColor(SwarmFlowTone.nodeTone(node)) })
    .alignItems(VerticalAlign.Center)
  }

  /** 徽标摘要：审批=操作摘要；候选=产物键（后端已折叠进 member_name，空则回退 id） */
  private badgeSummary(node: SwarmGraphNode): string {
    if (node.member_name.length > 0) {
      return node.member_name;
    }
    if (node.candidate_id.length > 0) {
      return node.candidate_id;
    }
    return node.request_id;
  }
}
