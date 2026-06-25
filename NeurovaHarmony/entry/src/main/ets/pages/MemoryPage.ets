/**
 * MemoryPage - 记忆管理页
 *
 * 职责：按类型分类展示当前 Agent 的记忆列表，支持搜索、删除、查看详情
 * 设计：
 *   - MemoryViewHelper（导出）：纯视图模型，封装类型颜色映射、类型过滤、温度格式化、内容截断，
 *     无 UI 运行时依赖，可独立单元测试；
 *   - MemoryPage（@Component）：Column [TopNavMenu(标题+返回+搜索)] + [可折叠搜索栏]
 *     + [类型筛选 Tab 横向滚动胶囊] + [加载态/空态/列表]；列表项 GlassCard 含类型标签、
 *     内容（最多 3 行省略）、温度条 + 重要性 + 创建时间、详情/删除按钮；
 *     删除需 AlertDialog 二次确认；详情弹窗展示完整内容与元数据；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.memory，状态走 AgentsStore
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（memory.list/remove/search）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Memory、MemoryType
 *
 * 用法：
 *   由 Router.push(RouteNames.MEMORY) 跳转进入；
 *   aboutToAppear 加载当前 Agent 的记忆列表；
 *   类型筛选 Tab 切换 → 本地 filterByType 过滤；
 *   搜索按钮展开搜索栏 → 调用 api.memory.search；
 *   详情按钮 → 弹出 Dialog 展示完整内容；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.memory.remove → 刷新列表
 *
 * TDD：MemoryViewHelper 各方法按红绿灯垂直切片逐步实现，详见 MemoryPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Memory, MemoryType } from '../libs/types';
import { SimpleDataSource } from '../libs/perf/SimpleDataSource';

/** 日志标签 */
const TAG = 'MemoryPage';

// ===========================================================================
// MemoryViewHelper - 记忆视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MemoryViewHelper {
  /**
   * 获取记忆类型对应的颜色 token 名
   * 映射：episodic→primary，semantic→info，procedural→success，
   *       emotional→warning，preference→secondary，其他→text_secondary
   * @param type 记忆类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: MemoryType): string {
    if (type === 'episodic') return 'primary';
    if (type === 'semantic') return 'info';
    if (type === 'procedural') return 'success';
    if (type === 'emotional') return 'warning';
    if (type === 'preference') return 'secondary';
    return 'text_secondary';
  }

  /**
   * 按记忆类型过滤
   * @param memories 记忆列表
   * @param type 类型；为 null 时返回全部
   * @return 过滤后的记忆列表
   */
  static filterByType(memories: Memory[], type: MemoryType | null): Memory[] {
    if (!type) return memories;
    return memories.filter(m => m.type === type);
  }

  /**
   * 格式化温度为百分比字符串
   * @param t 温度值 0-1
   * @return 百分比字符串，如 0.5 → "50%"
   */
  static formatTemperature(t: number): string {
    return `${Math.round(t * 100)}%`;
  }

  /**
   * 截断内容，超长时截取 maxLen 字符并追加省略号
   * @param content 原始内容
   * @param maxLen 最大字符数
   * @return 截断后的内容；未超长则原样返回
   */
  static truncateContent(content: string, maxLen: number): string {
    if (content.length <= maxLen) return content;
    return content.substring(0, maxLen) + '...';
  }
}

// ===========================================================================
// 类型标签映射表（17 种 MemoryType → 中文短名）
// ===========================================================================

const MEMORY_TYPE_LABELS: Record<string, string> = {
  episodic: '情景',
  semantic: '语义',
  procedural: '程序',
  emotional: '情感',
  preference: '偏好',
  fact: '事实',
  skill: '技能',
  event: '事件',
  relationship: '关系',
  context: '上下文',
  reflection: '反思',
  plan: '计划',
  goal: '目标',
  dream: '梦想',
  insight: '洞察',
  association: '联想',
  pattern: '模式',
};

/** 全部 MemoryType（用于筛选 Tab 顺序） */
const ALL_MEMORY_TYPES: MemoryType[] = [
  'episodic', 'semantic', 'procedural', 'emotional', 'preference',
  'fact', 'skill', 'event', 'relationship', 'context',
  'reflection', 'plan', 'goal', 'dream', 'insight', 'association', 'pattern',
];

@Component
export struct MemoryPage {
  // 当前展示的记忆列表（由 API 加载或搜索结果，驱动列表渲染）
  @State memories: Memory[] = [];
  // M5.2.2 LazyForEach 数据源（经 type 过滤后的列表）
  private filteredDs: SimpleDataSource<Memory> = new SimpleDataSource<Memory>();
  // 加载态（控制"加载中..."占位与列表切换）
  @State loading: boolean = true;
  // 搜索栏可见性（TopNavMenu 搜索按钮切换）
  @State searchVisible: boolean = false;
  // 搜索关键词（受控输入）
  @State searchKeyword: string = '';
  // 当前筛选类型（null = 全部）
  @State activeType: MemoryType | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadMemories();
  }

  /**
   * 加载当前 Agent 的全部记忆
   * 流程：取 currentAgentId → 调用 api.memory.list → 写入 memories
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadMemories(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId;
      const res = await this.api.memory.list(agentId || undefined);
      if (res.code === 0 && res.data) {
        this.memories = res.data.items;
        // M5.2.2 更新 LazyForEach 数据源（经 type 过滤）
        this.applyFilter();
      }
    } catch (e) {
      this.logger.error(TAG, '加载记忆失败', e as Error);
      this.msg.error('加载记忆失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 关键词搜索记忆
   * 流程：调用 api.memory.search → 替换 memories 为搜索结果
   * 空关键词：重新加载全部
   * 异常：记录日志并提示用户
   */
  private async handleSearch(): Promise<void> {
    const keyword = this.searchKeyword.trim();
    if (!keyword) {
      this.loadMemories();
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.memory.search({
        keyword,
        agentId: this.agentsStore.currentAgentId,
        limit: 20,
      });
      if (res.code === 0 && res.data) {
        this.memories = res.data;
        this.activeType = null;
        // M5.2.2 更新 LazyForEach 数据源（搜索后无 type 过滤）
        this.applyFilter();
      }
    } catch (e) {
      this.logger.error(TAG, '搜索记忆失败', e as Error);
      this.msg.error('搜索记忆失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换类型筛选
   * 同一类型再次点击 → 取消筛选（null）
   * M5.2.2：切换时同步刷新 LazyForEach 数据源
   */
  private handleTypeFilter(type: MemoryType): void {
    this.activeType = this.activeType === type ? null : type;
    this.applyFilter();
  }

  /**
   * M5.2.2 应用当前 type 过滤到 LazyForEach 数据源
   * 规则：activeType 为 null 时显示全部；否则按类型过滤
   */
  private applyFilter(): void {
    this.filteredDs.setData(this.getFilteredMemories());
  }

  /**
   * 切换搜索栏显隐
   */
  private toggleSearch(): void {
    this.searchVisible = !this.searchVisible;
    if (!this.searchVisible) {
      this.searchKeyword = '';
    }
  }

  /**
   * 获取经当前类型筛选后的列表
   */
  private getFilteredMemories(): Memory[] {
    return MemoryViewHelper.filterByType(this.memories, this.activeType);
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(memory: Memory): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除这条${this.getTypeLabel(memory.type)}记忆吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteMemory(memory.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.memory.remove → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteMemory(memoryId: string): Promise<void> {
    try {
      const res = await this.api.memory.remove(memoryId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadMemories();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除记忆失败', e as Error);
      this.msg.error('删除记忆失败');
    }
  }

  /**
   * 展示记忆详情（AlertDialog：完整内容 + 元数据）
   */
  private showDetail(memory: Memory): void {
    const temp = memory.temperature !== undefined ? MemoryViewHelper.formatTemperature(memory.temperature) : '未知';
    const imp = memory.importance !== undefined ? memory.importance.toFixed(2) : '未知';
    const message =
      `类型：${this.getTypeLabel(memory.type)}\n\n` +
      `内容：\n${memory.content}\n\n` +
      `温度：${temp}\n` +
      `重要性：${imp}\n` +
      `创建时间：${this.formatTime(memory.createdAt)}`;
    AlertDialog.show({
      title: '记忆详情',
      message,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  /** 获取类型中文标签，未知类型回退 '其他' */
  private getTypeLabel(type: MemoryType): string {
    return MEMORY_TYPE_LABELS[type] ?? '其他';
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无效值回退 '未知' */
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
    Column() {
      // 顶部导航栏：标题"记忆管理" + 返回 + 搜索按钮（右侧插槽）
      TopNavMenu({
        title: '记忆管理',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      }) {
        GlassButton({
          text: '搜索',
          type: 'default',
          size: 'small',
          onClick: () => { this.toggleSearch(); }
        })
      }

      // 可折叠搜索栏：GlassInput + 搜索按钮
      if (this.searchVisible) {
        Row() {
          GlassInput({
            placeholder: '搜索记忆关键词...',
            value: this.searchKeyword,
            onChange: (v: string) => { this.searchKeyword = v; },
            onSubmit: (v: string) => { this.handleSearch(); }
          })
            .layoutWeight(1)
          GlassButton({
            text: '搜索',
            type: 'primary',
            size: 'small',
            onClick: () => { this.handleSearch(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
        .alignItems(VerticalAlign.Center)
      }

      // 类型筛选 Tab：横向滚动胶囊（全部 + 17 种 MemoryType）
      Scroll() {
        Row({ space: 8 }) {
          // 全部
          Text('全部')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.activeType === null ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.activeType === null ? this.sm.getColor('primary') : Color.Transparent)
            .onClick(() => { this.activeType = null; })

          // 17 种类型
          ForEach(ALL_MEMORY_TYPES, (t: MemoryType) => {
            Text(this.getTypeLabel(t))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.activeType === t ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_primary'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .backgroundColor(this.activeType === t
                ? this.sm.getColor(MemoryViewHelper.getTypeColor(t))
                : Color.Transparent)
              .onClick(() => { this.handleTypeFilter(t); })
          }, (t: MemoryType) => t)
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

      // 主体：加载态 / 空态 / 列表
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
      } else if (this.filteredDs.totalCount() === 0) {
        Column() {
          Text('暂无记忆')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          // M5.2.2 改用 LazyForEach 惰性渲染，仅渲染可见区域 + 缓存项
          LazyForEach(this.filteredDs, (memory: Memory) => {
            ListItem() {
              this.buildMemoryCard(memory)
            }
          }, (memory: Memory) => memory.id)
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
  // 记忆卡片构建器
  // ===========================================================================

  /** 单条记忆卡片：类型标签 + 内容 + 温度条/重要性/时间 + 操作按钮 */
  @Builder
  buildMemoryCard(memory: Memory) {
    GlassCard() {
      Column() {
        // 上部：类型标签（彩色胶囊）
        Row() {
          Text(this.getTypeLabel(memory.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(MemoryViewHelper.getTypeColor(memory.type)))
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)

        // 内容（最多 3 行，超出省略；截断到 150 字符避免过长）
        Text(MemoryViewHelper.truncateContent(memory.content, 150))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 底部行：温度条 + 重要性 + 创建时间
        Row() {
          // 温度条容器（固定宽度 60，内部按温度填充）
          Row() {
            Row()
              .width(`${Math.round((memory.temperature ?? 0) * 100)}%`)
              .height(4)
              .borderRadius(2)
              .backgroundColor(this.sm.getColor('primary'))
          }
          .width(60)
          .height(4)
          .borderRadius(2)
          .backgroundColor(this.sm.getColor('divider'))
          .alignItems(VerticalAlign.Start)

          Text(`温度 ${MemoryViewHelper.formatTemperature(memory.temperature ?? 0)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })

          Text(`重要性 ${(memory.importance ?? 0).toFixed(2)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })

          Text(this.formatTime(memory.createdAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 8 })
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(memory); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(memory); }
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
}
