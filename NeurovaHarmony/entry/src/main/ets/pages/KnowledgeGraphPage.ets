/**
 * KnowledgeGraphPage - 知识图谱页
 *
 * 职责：展示当前 Agent 的知识图谱节点+边，支持节点筛选、节点详情、节点删除
 * 设计：
 *   - KnowledgeGraphViewHelper（导出）：纯视图模型，封装节点类型颜色映射、节点类型图标、
 *     节点类型中文标签、平均权重计算、关联边查找；无 UI 运行时依赖，可独立单元测试；
 *   - KnowledgeGraphPage（@Component）：Column [TopNavMenu(标题"知识图谱"+返回+刷新)]
 *     + [节点类型筛选 Tab（全部/概念/实体/事件/事实）]
 *     + [加载态/空态/概览卡 + 节点列表]；概览卡展示节点数、边数、平均权重；
 *     节点列表项 GlassCard 含 label、type 徽章、weight、属性数、操作按钮（查看/删除）；
 *     节点详情通过 Stack 条件渲染的弹窗展示完整属性 + 关联边列表；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.cognition.getKnowledgeGraph，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（cognition.getKnowledgeGraph）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：KnowledgeNode、KnowledgeEdge、KnowledgeGraph
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.cognition.getKnowledgeGraph 加载节点+边；
 *   节点类型筛选 Tab 切换 → 本地 filterByType 过滤；
 *   查看按钮 → 弹出 Stack 弹窗展示完整属性 + 关联边列表；
 *   删除按钮 → 当前提示"功能开发中"（后端 removeKnowledgeNode 待 M5 实现）
 *
 * TDD：KnowledgeGraphViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 KnowledgeGraphPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { KnowledgeNode, KnowledgeEdge, KnowledgeGraph } from '../libs/types';

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
   * 映射：concept→info，entity→success，event→warning，fact→primary
   * @param type 节点类型
   * @return StyleManager 颜色 token 名
   */
  static getNodeTypeColor(type: KnowledgeNode['type']): string {
    if (type === 'concept') return 'info';
    if (type === 'entity') return 'success';
    if (type === 'event') return 'warning';
    if (type === 'fact') return 'primary';
    return 'text_disabled';
  }

  /**
   * 获取节点类型对应的图标 emoji
   * 映射：concept→💡，entity→🎯，event→⚡，fact→📌
   * @param type 节点类型
   * @return emoji 字符串
   */
  static getNodeTypeIcon(type: KnowledgeNode['type']): string {
    if (type === 'concept') return '💡';
    if (type === 'entity') return '🎯';
    if (type === 'event') return '⚡';
    if (type === 'fact') return '📌';
    return '📄';
  }

  /**
   * 获取节点类型的中文标签
   * 映射：concept→概念，entity→实体，event→事件，fact→事实
   * @param type 节点类型
   * @return 中文标签字符串
   */
  static getNodeTypeLabel(type: KnowledgeNode['type']): string {
    if (type === 'concept') return '概念';
    if (type === 'entity') return '实体';
    if (type === 'event') return '事件';
    if (type === 'fact') return '事实';
    return '未知';
  }

  /**
   * 计算节点列表的平均权重（无权重视为 0）
   * @param nodes 节点列表
   * @return 平均权重；空列表返回 0
   */
  static calculateAvgWeight(nodes: KnowledgeNode[]): number {
    if (nodes.length === 0) return 0;
    const sum = nodes.reduce((acc: number, n: KnowledgeNode) => acc + (n.weight ?? 0), 0);
    return sum / nodes.length;
  }

  /**
   * 查找与指定节点关联的所有边（source 或 target 任一匹配）
   * @param nodeId 节点 ID
   * @param edges 边列表
   * @return 关联边列表（保持原顺序）
   */
  static findRelatedEdges(nodeId: string, edges: KnowledgeEdge[]): KnowledgeEdge[] {
    return edges.filter((e: KnowledgeEdge) => e.source === nodeId || e.target === nodeId);
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

/** 节点类型筛选 Tab 列表（顺序即展示顺序） */
const NODE_TYPE_FILTERS: NodeTypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'concept', label: '概念' },
  { value: 'entity', label: '实体' },
  { value: 'event', label: '事件' },
  { value: 'fact', label: '事实' },
];

@Component
export struct KnowledgeGraphPage {
  // 知识图谱数据（节点+边）
  @State graph: KnowledgeGraph = { nodes: [], edges: [] };
  // 加载态
  @State loading: boolean = true;
  // 当前激活的节点类型筛选值：'all' 或具体类型
  @State activeType: string = 'all';
  // 详情弹窗控制：showDetail 控制显隐，detailNode 持有当前查看的节点
  @State showDetail: boolean = false;
  @State detailNode: KnowledgeNode | null = null;

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
  private getFilteredNodes(): KnowledgeNode[] {
    if (this.activeType === 'all') {
      return this.graph.nodes;
    }
    return this.graph.nodes.filter((n: KnowledgeNode) => n.type === this.activeType);
  }

  /**
   * 打开节点详情弹窗
   */
  private openDetail(node: KnowledgeNode): void {
    this.detailNode = node;
    this.showDetail = true;
  }

  /** 关闭节点详情弹窗 */
  private closeDetail(): void {
    this.showDetail = false;
    this.detailNode = null;
  }

  /**
   * 删除节点（后端 removeKnowledgeNode 待 M5 实现，当前提示"功能开发中"）
   */
  private handleDelete(node: KnowledgeNode): void {
    this.msg.info('节点删除功能开发中');
  }

  /**
   * 计算节点属性数量
   * @param node 节点
   * @return 属性数量；无 properties 返回 0
   */
  private getPropertiesCount(node: KnowledgeNode): number {
    if (!node.properties) return 0;
    return Object.keys(node.properties).length;
  }

  /**
   * 获取节点关联边列表（直接复用 ViewHelper 纯函数）
   */
  private getRelatedEdges(nodeId: string): KnowledgeEdge[] {
    return KnowledgeGraphViewHelper.findRelatedEdges(nodeId, this.graph.edges);
  }

  /**
   * 格式化权重为百分比字符串
   */
  private formatWeight(weight?: number): string {
    if (weight === undefined) return '—';
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
            size: 'small',
            onClick: () => { this.loadGraph(); }
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
        } else if (this.graph.nodes.length === 0) {
          Column() {
            Text('暂无图谱数据')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '重新加载',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.loadGraph(); }
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
            ForEach(this.getFilteredNodes(), (node: KnowledgeNode) => {
              ListItem() {
                this.buildNodeCard(node)
              }
            }, (node: KnowledgeNode) => node.id)
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

  /** 图谱概览卡：节点数 + 边数 + 平均权重 */
  @Builder
  buildOverviewCard() {
    GlassCard() {
      Row() {
        // 节点数
        Column() {
          Text(`${this.graph.nodes.length}`)
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('primary'))
          Text('节点数')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Center)

        // 边数
        Column() {
          Text(`${this.graph.edges.length}`)
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('info'))
          Text('边数')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Center)

        // 平均权重
        Column() {
          Text(this.formatWeight(KnowledgeGraphViewHelper.calculateAvgWeight(this.graph.nodes)))
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
    }
    .width('100%')
  }

  // ===========================================================================
  // 节点卡片构建器
  // ===========================================================================

  /** 单个节点卡片：图标 + label + type 徽章 + weight + 属性数 + 操作按钮 */
  @Builder
  buildNodeCard(node: KnowledgeNode) {
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

        // type 徽章
        Row() {
          Text(KnowledgeGraphViewHelper.getNodeTypeLabel(node.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(KnowledgeGraphViewHelper.getNodeTypeColor(node.type)))
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
        .margin({ top: this.sm.getSpacing('sm') })

        // 底部行：weight + 属性数 + 关联边数
        Row() {
          Text(`权重: ${this.formatWeight(node.weight)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`属性: ${this.getPropertiesCount(node)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
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

        // 操作按钮：查看详情 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '查看详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetail(node); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.handleDelete(node); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
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

  /** 详情弹窗：完整属性 + 关联边列表 */
  @Builder
  buildDetailDialog(node: KnowledgeNode) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', padding: 20 }) {
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

          // 属性列表（可滚动）
          Text('属性')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Medium)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: this.sm.getSpacing('md') })
          Scroll() {
            Column() {
              if (this.getPropertiesCount(node) === 0) {
                Text('暂无属性')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_disabled'))
              } else {
                ForEach(Object.entries(node.properties ?? {}), ([k, v]: [string, Object]) => {
                  Row() {
                    Text(`${k}:`)
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_secondary'))
                      .layoutWeight(1)
                    Text(typeof v === 'object' ? JSON.stringify(v) : String(v))
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_primary'))
                      .maxLines(2)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                  }
                  .width('100%')
                  .margin({ top: 4 })
                  .alignItems(VerticalAlign.Center)
                }, ([k]: [string, Object]) => k)
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
                ForEach(this.getRelatedEdges(node.id), (edge: KnowledgeEdge) => {
                  Row() {
                    Text(`${edge.source} → ${edge.target}`)
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_primary'))
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                    Text(edge.relation)
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_secondary'))
                      .margin({ left: 8 })
                  }
                  .width('100%')
                  .margin({ top: 4 })
                  .alignItems(VerticalAlign.Center)
                }, (edge: KnowledgeEdge) => edge.id)
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
            size: 'medium',
            block: true,
            onClick: () => { this.closeDetail(); }
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
