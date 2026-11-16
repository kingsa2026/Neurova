/**
 * KnowledgeGraphPage - 知识图谱页（knowledge_graph_api 真实契约版）
 *
 * 数据：GET /v1/knowledge-graph/{agent_id}/knowledge-graph?limit=
 *       （data 投影：nodes[{id,label,type,description,weight,created_at}]/
 *        edges[{source,target,relation,weight}]/total_nodes/total_edges/
 *        truncated/hint）
 * 契约说明：节点类型真实词汇为 concept/entity/event/memory（NodeType 枚举）；
 *       后端无节点删除端点，本页不提供删除；概览卡展示裁剪子图与真总量
 *       （truncated 提示"仅展示前 N 节点子图"）。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { KnowledgeGraphDto, GraphNodeDto, GraphEdgeDto } from '../libs/api/modules/CognitionApi';

/** 日志标签 */
const TAG = 'KnowledgeGraphPage';

// ===========================================================================
// KnowledgeGraphViewHelper - 知识图谱视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class KnowledgeGraphViewHelper {
  /**
   * 获取节点类型对应的颜色 token 名
   * 映射：concept→info，entity→success，event→warning，memory→primary
   * @param type 节点类型（NodeType 枚举词汇）
   * @return StyleManager 颜色 token 名
   */
  static getNodeTypeColor(type: string): string {
    if (type === 'concept') return 'info';
    if (type === 'entity') return 'success';
    if (type === 'event') return 'warning';
    if (type === 'memory') return 'primary';
    return 'text_disabled';
  }

  /**
   * 获取节点类型对应的图标 emoji
   * 映射：concept→💡，entity→🎯，event→⚡，memory→🧠
   * @param type 节点类型
   * @return emoji 字符串
   */
  static getNodeTypeIcon(type: string): string {
    if (type === 'concept') return '💡';
    if (type === 'entity') return '🎯';
    if (type === 'event') return '⚡';
    if (type === 'memory') return '🧠';
    return '📄';
  }

  /**
   * 获取节点类型的中文标签
   * 映射：concept→概念，entity→实体，event→事件，memory→记忆
   * @param type 节点类型
   * @return 中文标签字符串
   */
  static getNodeTypeLabel(type: string): string {
    if (type === 'concept') return '概念';
    if (type === 'entity') return '实体';
    if (type === 'event') return '事件';
    if (type === 'memory') return '记忆';
    return '未知';
  }

  /**
   * 关系类型 → 中文标签（RelationType 枚举；未知原样）
   */
  static relationLabel(relation: string): string {
    if (relation === 'is_a') return '是一种';
    if (relation === 'has_a') return '拥有';
    if (relation === 'part_of') return '属于';
    if (relation === 'related_to') return '相关';
    if (relation === 'causes') return '导致';
    if (relation === 'similar_to') return '相似';
    if (relation === 'opposite_of') return '相反';
    if (relation === 'temporal') return '时间关系';
    return relation;
  }

  /**
   * 计算节点列表的平均权重（无权重视为 0）
   * @param nodes 节点列表
   * @return 平均权重；空列表返回 0
   */
  static calculateAvgWeight(nodes: GraphNodeDto[]): number {
    if (nodes.length === 0) return 0;
    const sum = nodes.reduce((acc: number, n: GraphNodeDto) => acc + (n.weight ?? 0), 0);
    return sum / nodes.length;
  }

  /**
   * 查找与指定节点关联的所有边（source 或 target 任一匹配）
   * @param nodeId 节点 ID
   * @param edges 边列表
   * @return 关联边列表（保持原顺序）
   */
  static findRelatedEdges(nodeId: string, edges: GraphEdgeDto[]): GraphEdgeDto[] {
    return edges.filter((e: GraphEdgeDto) => e.source === nodeId || e.target === nodeId);
  }
}

// ===========================================================================
// 节点类型筛选 Tab 配置
// ===========================================================================

/** 节点类型筛选项：value 为 'all' 或具体节点类型 */
interface NodeTypeFilterOption {
  value: string;
  label: string;
}

/** 节点类型筛选 Tab 列表（顺序即展示顺序，词汇与后端 NodeType 枚举同源） */
const NODE_TYPE_FILTERS: NodeTypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'concept', label: '概念' },
  { value: 'entity', label: '实体' },
  { value: 'event', label: '事件' },
  { value: 'memory', label: '记忆' },
];

@Component
export struct KnowledgeGraphPage {
  // 知识图谱数据（节点+边+真总量）
  @State graph: KnowledgeGraphDto | null = null;
  // 加载态
  @State loading: boolean = true;
  // 当前激活的节点类型筛选值：'all' 或具体类型
  @State activeType: string = 'all';
  // 详情弹窗控制：showDetail 控制显隐，detailNode 持有当前查看的节点
  @State showDetail: boolean = false;
  @State detailNode: GraphNodeDto | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadGraph();
  }

  /**
   * 加载当前 Agent 的知识图谱
   * 流程：取 currentAgentId → 调用 api.cognition.getKnowledgeGraph → 写入 graph
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadGraph(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || '';
      const res = await this.api.cognition.getKnowledgeGraph(agentId);
      if (res.code === 0 && res.data) {
        this.graph = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '加载知识图谱失败', e as Error);
      this.msg.error('加载知识图谱失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换节点类型筛选 Tab（本地过滤）
   */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /**
   * 获取经当前类型筛选后的节点列表
   * 规则：activeType === 'all' 返回全量；否则按 type 字段过滤
   */
  private getFilteredNodes(): GraphNodeDto[] {
    const nodes = this.graph !== null ? this.graph.nodes : [];
    if (this.activeType === 'all') {
      return nodes;
    }
    return nodes.filter((n: GraphNodeDto) => n.type === this.activeType);
  }

  /**
   * 打开节点详情弹窗
   */
  private openDetail(node: GraphNodeDto): void {
    this.detailNode = node;
    this.showDetail = true;
  }

  /** 关闭节点详情弹窗 */
  private closeDetail(): void {
    this.showDetail = false;
    this.detailNode = null;
  }

  /**
   * 获取节点关联边列表（直接复用 ViewHelper 纯函数）
   */
  private getRelatedEdges(nodeId: string): GraphEdgeDto[] {
    const edges = this.graph !== null ? this.graph.edges : [];
    return KnowledgeGraphViewHelper.findRelatedEdges(nodeId, edges);
  }

  /**
   * 格式化权重为百分比字符串
   */
  private formatWeight(weight: number): string {
    return (weight * 100).toFixed(1) + '%';
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"知识图谱" + 返回 + 刷新
        TopNavMenu({
          title: '知识图谱',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '刷新',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.loadGraph(); }
          })
        }

        // 节点类型筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(NODE_TYPE_FILTERS, (opt: NodeTypeFilterOption) => {
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
            }, (opt: NodeTypeFilterOption) => opt.value)
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

        // 主体：加载态 / 空态 / 概览卡 + 节点列表
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
        } else if (this.graph === null || this.graph.nodes.length === 0) {
          Column() {
            Text('暂无图谱数据')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            if (this.graph !== null && this.graph.hint.length > 0) {
              Text(this.graph.hint)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_disabled'))
                .margin({ bottom: this.sm.getSpacing('md') })
                .textAlign(TextAlign.Center)
            }
            GlassButton({
              text: '重新加载',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.loadGraph(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            // 概览卡（仅一项，置顶）
            ListItem() {
              this.buildOverviewCard()
            }
            // 节点列表
            ForEach(this.getFilteredNodes(), (node: GraphNodeDto) => {
              ListItem() {
                this.buildNodeCard(node)
              }
            }, (node: GraphNodeDto) => node.id)
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

      // 节点详情弹窗：showDetail 为 true 时覆盖在主体之上
      if (this.showDetail && this.detailNode) {
        this.buildDetailDialog(this.detailNode)
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 概览卡构建器
  // ===========================================================================

  /** 图谱概览卡：子图节点/边 + 真总量（truncated 提示裁剪）+ 平均权重 */
  @Builder
  buildOverviewCard() {
    GlassCard() {
      Column() {
        Row() {
          // 子图节点数 / 真总量
          Column() {
            Text(this.graph !== null ? `${this.graph.nodes.length}/${this.graph.total_nodes}` : '-')
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('primary'))
            Text('节点（子图/总量）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Center)

          // 子图边数 / 真总量
          Column() {
            Text(this.graph !== null ? `${this.graph.edges.length}/${this.graph.total_edges}` : '-')
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('info'))
            Text('边（子图/总量）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Center)

          // 平均权重
          Column() {
            Text(this.graph !== null
              ? this.formatWeight(KnowledgeGraphViewHelper.calculateAvgWeight(this.graph.nodes))
              : '-')
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('success'))
            Text('平均权重')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Center)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 截断提示（后端 truncated：给出的是裁剪后的子图）
        if (this.graph !== null && this.graph.truncated) {
          Text('图谱较大，当前仅展示裁剪子图')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('warning'))
            .margin({ top: this.sm.getSpacing('sm') })
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 节点卡片构建器
  // ===========================================================================

  /** 单个节点卡片：图标 + label + type 徽章 + weight + 描述 + 关联边数 + 查看 */
  @Builder
  buildNodeCard(node: GraphNodeDto) {
    GlassCard() {
      Column() {
        // 第一行：图标 + label
        Row() {
          Text(KnowledgeGraphViewHelper.getNodeTypeIcon(node.type))
            .fontSize(18)
          Text(node.label)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: 6 })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // type 徽章 + 权重
        Row() {
          Text(KnowledgeGraphViewHelper.getNodeTypeLabel(node.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(KnowledgeGraphViewHelper.getNodeTypeColor(node.type)))
          Text(`权重: ${this.formatWeight(node.weight)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 12 })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: this.sm.getSpacing('sm') })

        // 描述摘要
        if (node.description.length > 0) {
          Text(node.description)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: this.sm.getSpacing('sm') })
            .width('100%')
        }

        // 底部行：关联边数
        Row() {
          Text(`关联边: ${this.getRelatedEdges(node.id).length}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看详情（后端无节点删除端点，不提供删除）
        Row() {
          GlassButton({
            text: '查看详情',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.openDetail(node); }
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

  // ===========================================================================
  // 节点详情弹窗构建器（Stack 覆盖层，内嵌实现，不创建单独 CustomDialog 文件）
  // ===========================================================================

  /** 详情弹窗：描述 + 关联边列表（关系中文标签） */
  @Builder
  buildDetailDialog(node: GraphNodeDto) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Column() {
          // 标题行：图标 + label
          Row() {
            Text(KnowledgeGraphViewHelper.getNodeTypeIcon(node.type))
              .fontSize(20)
            Text(node.label)
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .layoutWeight(1)
              .margin({ left: 6 })
              .maxLines(2)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // type 徽章 + weight
          Row() {
            Text(KnowledgeGraphViewHelper.getNodeTypeLabel(node.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .padding({ left: 8, right: 8, top: 2, bottom: 2 })
              .borderRadius(10)
              .backgroundColor(this.sm.getColor(KnowledgeGraphViewHelper.getNodeTypeColor(node.type)))
            Text(`权重: ${this.formatWeight(node.weight)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 12 })
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)

          // 描述
          Text('描述')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('md') })
          Scroll() {
            Column() {
              if (node.description.length === 0) {
                Text('暂无描述')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              } else {
                Text(node.description)
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_primary'))
                  .width('100%')
              }
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)

          // 关联边列表
          Text(`关联边 (${this.getRelatedEdges(node.id).length})`)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('sm') })
          Scroll() {
            Column() {
              if (this.getRelatedEdges(node.id).length === 0) {
                Text('暂无关联边')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              } else {
                ForEach(this.getRelatedEdges(node.id), (edge: GraphEdgeDto) => {
                  Row() {
                    Text(`${edge.source} → ${edge.target}`)
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_primary'))
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                    Text(KnowledgeGraphViewHelper.relationLabel(edge.relation))
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_secondary'))
                      .margin({ left: 8 })
                  }
                  .width('100%')
                  .margin({ top: 4 })
                  .alignItems(VerticalAlign.Center)
                }, (edge: GraphEdgeDto) => `${edge.source}-${edge.target}-${edge.relation}`)
              }
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            btnSize: 'medium',
            block: true,
            onTap: () => { this.closeDetail(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .height('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }
}
