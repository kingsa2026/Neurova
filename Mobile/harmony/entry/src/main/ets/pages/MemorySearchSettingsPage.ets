/**
 * MemorySearchSettingsPage - 记忆搜索设置页
 *
 * 职责：记忆搜索设置表单（策略选择 semantic/keyword/hybrid/temporal、topK 滑块、
 *       minScore 滑块、过滤器配置）
 * 设计：
 *   - MemorySearchSettingsViewHelper（导出）：纯视图模型，封装策略颜色映射、策略中文标签、
 *     topK 格式化、minScore 颜色、minScore 格式化（1 位小数）、过滤器格式化（JSON），
 *     无 UI 依赖，可独立单元测试；
 *   - MemorySearchSettingsPage（@Component）：Stack [主内容列]
 *     主内容列：TopNavMenu(标题"记忆搜索设置"+返回+保存) + [加载态/表单]；
 *     表单：策略选择（4 个胶囊单选）、topK 滑块、minScore 滑块、
 *     过滤器（types 多行、tags 多行、dateRange 起止）、enabled 开关；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无记忆搜索设置专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 接入真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MemorySearchSettings、MemorySearchStrategy
 *
 * 用法：
 *   由 Router.push(RouteNames.MEMORY_SEARCH_SETTINGS) 跳转进入；
 *   aboutToAppear 加载当前 Agent 的搜索设置（TODO M6 接入真实 API api.memorySearchSettings.*）；
 *   修改表单 → 保存按钮 → TODO M6 接入 api.memorySearchSettings.update。
 *
 * TDD：MemorySearchSettingsViewHelper 各方法按红绿灯垂直切片逐步实现，详见 MemorySearchSettingsPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MemorySearchSettings, MemorySearchStrategy } from '../libs/types';

/** 日志标签 */
const TAG = 'MemorySearchSettingsPage';

/** 全部策略（用于选择胶囊顺序） */
const ALL_STRATEGIES: MemorySearchStrategy[] = ['semantic', 'keyword', 'hybrid', 'temporal'];

/** 默认搜索设置（用于新建 Agent） */
const DEFAULT_SETTINGS: MemorySearchSettings = {
  agentId: '',
  strategy: 'hybrid',
  topK: 10,
  minScore: 0.5,
  filters: undefined,
  enabled: true,
  updatedAt: '',
};

// ===========================================================================
// MemorySearchSettingsViewHelper - 记忆搜索设置视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class MemorySearchSettingsViewHelper {
  /**
   * 获取搜索策略对应的颜色 token 名
   * 映射：semantic→primary, keyword→info, hybrid→success, temporal→warning
   * @param strategy 搜索策略
   * @return StyleManager 颜色 token 名
   */
  static getStrategyColor(strategy: MemorySearchStrategy): string {
    if (strategy === 'semantic') return 'primary';
    if (strategy === 'keyword') return 'info';
    if (strategy === 'hybrid') return 'success';
    return 'warning';
  }

  /**
   * 获取搜索策略对应的中文标签
   * 映射：semantic→语义搜索, keyword→关键词搜索, hybrid→混合搜索, temporal→时间搜索
   * @param strategy 搜索策略
   * @return 中文标签
   */
  static getStrategyLabel(strategy: MemorySearchStrategy): string {
    if (strategy === 'semantic') return '语义搜索';
    if (strategy === 'keyword') return '关键词搜索';
    if (strategy === 'hybrid') return '混合搜索';
    return '时间搜索';
  }

  /**
   * 格式化 topK
   * 规则：返回 "N 条结果"
   * @param topK 返回结果数
   * @return topK 文案
   */
  static formatTopK(topK: number): string {
    return `${topK} 条结果`;
  }

  /**
   * 获取 minScore 对应的颜色 token 名
   * 规则：< 0.3 → text_secondary；0.3-0.7 → info；> 0.7 → success
   * @param score 最小分数（0-1）
   * @return StyleManager 颜色 token 名
   */
  static getMinScoreColor(score: number): string {
    if (score < 0.3) return 'text_secondary';
    if (score > 0.7) return 'success';
    return 'info';
  }

  /**
   * 格式化 minScore（1 位小数）
   * 规则：返回 "0.X" 格式
   * @param score 最小分数（0-1）
   * @return minScore 文案
   */
  static formatMinScore(score: number): string {
    return score.toFixed(1);
  }

  /**
   * 格式化过滤器
   * 规则：undefined → "无过滤器"；非空 → JSON.stringify
   * @param filters 过滤器对象或 undefined
   * @return 过滤器文案
   */
  static formatFilters(filters?: Object): string {
    if (!filters) return '无过滤器';
    return JSON.stringify(filters);
  }
}

/**
 * Mock 搜索设置数据
 * TODO M6 阶段：替换为 api.memorySearchSettings.get(agentId) 真实 API
 */
const MOCK_SETTINGS: MemorySearchSettings = {
  agentId: 'agent_1',
  strategy: 'hybrid',
  topK: 10,
  minScore: 0.5,
  filters: {
    types: ['long_term', 'short_term'],
    tags: ['important'],
    dateRange: { start: '2025-01-01', end: '2025-06-01' },
  },
  enabled: true,
  updatedAt: '2025-06-01T00:00:00Z',
};

/** 过滤器表单数据（独立维护，便于输入） */
interface FiltersFormData {
  typesText: string;       // 多行文本，每行一个 type
  tagsText: string;        // 多行文本，每行一个 tag
  dateStart: string;       // 起始日期 YYYY-MM-DD
  dateEnd: string;         // 结束日期 YYYY-MM-DD
}

/** 默认过滤器表单 */
const DEFAULT_FILTERS_FORM: FiltersFormData = {
  typesText: '',
  tagsText: '',
  dateStart: '',
  dateEnd: '',
};

@Component
export struct MemorySearchSettingsPage {
  // 搜索设置（嵌套属性变更需整体重新赋值）
  @State settings: MemorySearchSettings = { ...DEFAULT_SETTINGS };
  // 加载态
  @State loading: boolean = true;
  // 当前 Agent ID
  @State agentId: string = '';
  // 过滤器表单（独立维护）
  @State filtersForm: FiltersFormData = { ...DEFAULT_FILTERS_FORM };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadSettings();
  }

  /**
   * 加载当前 Agent 的搜索设置
   * TODO M6 阶段：替换为真实 API（api.memorySearchSettings.get）
   */
  private async loadSettings(): Promise<void> {
    this.loading = true;
    try {
      this.agentId = this.agentsStore.currentAgentId || '';
      // TODO M6 阶段补充真实 API
      // const res = await this.api.memorySearchSettings.get(this.agentId);
      // if (res.code === 0 && res.data) { this.settings = res.data; }
      this.settings = { ...MOCK_SETTINGS, agentId: this.agentId };
      // 同步过滤器到表单
      this.syncFiltersToForm();
    } catch (e) {
      this.logger.error(TAG, '加载搜索设置失败', e as Error);
      this.msg.error('加载搜索设置失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 将 settings.filters 同步到 filtersForm（便于编辑）
   */
  private syncFiltersToForm(): void {
    const f = this.settings.filters;
    this.filtersForm = {
      typesText: f && f.types ? f.types.join('\n') : '',
      tagsText: f && f.tags ? f.tags.join('\n') : '',
      dateStart: f && f.dateRange ? f.dateRange.start : '',
      dateEnd: f && f.dateRange ? f.dateRange.end : '',
    };
  }

  /**
   * 将 filtersForm 合并回 settings.filters
   */
  private mergeFormToFilters(): void {
    const types = this.splitLines(this.filtersForm.typesText);
    const tags = this.splitLines(this.filtersForm.tagsText);
    const hasDate = this.filtersForm.dateStart || this.filtersForm.dateEnd;
    if (types.length === 0 && tags.length === 0 && !hasDate) {
      this.settings = { ...this.settings, filters: undefined };
      return;
    }
    this.settings = {
      ...this.settings,
      filters: {
        types: types.length > 0 ? types : undefined,
        tags: tags.length > 0 ? tags : undefined,
        dateRange: hasDate
          ? { start: this.filtersForm.dateStart, end: this.filtersForm.dateEnd }
          : undefined,
      },
    };
  }

  /**
   * 保存设置
   * TODO M6 阶段：调用真实 API（api.memorySearchSettings.update）
   */
  private async saveSettings(): Promise<void> {
    try {
      this.mergeFormToFilters();
      // TODO M6 阶段：const res = await this.api.memorySearchSettings.update(this.agentId, this.settings);
      this.msg.success('保存成功');
    } catch (e) {
      this.logger.error(TAG, '保存搜索设置失败', e as Error);
      this.msg.error('保存失败');
    }
  }

  /** 选择策略（嵌套属性变更：整体重新赋值） */
  private selectStrategy(strategy: MemorySearchStrategy): void {
    this.settings = { ...this.settings, strategy };
  }

  /** 滑动 topK（嵌套属性变更：整体重新赋值） */
  private slideTopK(value: number): void {
    this.settings = { ...this.settings, topK: Math.floor(value) };
  }

  /** 滑动 minScore（嵌套属性变更：整体重新赋值） */
  private slideMinScore(value: number): void {
    this.settings = { ...this.settings, minScore: value };
  }

  /** 切换 enabled（嵌套属性变更：整体重新赋值） */
  private toggleEnabled(): void {
    this.settings = { ...this.settings, enabled: !this.settings.enabled };
  }

  /** 输入 typesText（嵌套属性变更：整体重新赋值） */
  private inputTypesText(v: string): void {
    this.filtersForm = { ...this.filtersForm, typesText: v };
  }

  /** 输入 tagsText（嵌套属性变更：整体重新赋值） */
  private inputTagsText(v: string): void {
    this.filtersForm = { ...this.filtersForm, tagsText: v };
  }

  /** 输入 dateStart（嵌套属性变更：整体重新赋值） */
  private inputDateStart(v: string): void {
    this.filtersForm = { ...this.filtersForm, dateStart: v };
  }

  /** 输入 dateEnd（嵌套属性变更：整体重新赋值） */
  private inputDateEnd(v: string): void {
    this.filtersForm = { ...this.filtersForm, dateEnd: v };
  }

  /**
   * 将多行文本拆分为非空字符串数组
   */
  private splitLines(text: string): string[] {
    if (!text) return [];
    return text
      .split('\n')
      .map(s => s.trim())
      .filter(s => s.length > 0);
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"记忆搜索设置" + 返回 + 保存
        TopNavMenu({
          title: '记忆搜索设置',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '保存',
            type: 'primary',
            size: 'small',
            onClick: () => { this.saveSettings(); }
          })
        }

        // 主体内容：加载态 / 表单 二选一
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
        } else {
          Scroll() {
            Column() {
              // 启用开关
              this.buildEnabledRow()
              // 策略选择
              this.buildStrategyRow()
              // topK 滑块
              this.buildTopKRow()
              // minScore 滑块
              this.buildMinScoreRow()
              // 过滤器
              this.buildFiltersRow()
            }
            .width('100%')
            .padding({
              left: this.sm.getSpacing('md'),
              right: this.sm.getSpacing('md'),
              top: this.sm.getSpacing('sm'),
              bottom: this.sm.getSpacing('sm'),
            })
            .alignItems(HorizontalAlign.Start)
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Off)
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
  // 表单行构建器
  // ===========================================================================

  /** 启用开关行 */
  @Builder
  buildEnabledRow() {
    GlassCard() {
      Row() {
        Column() {
          Text('启用搜索')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
          Text('关闭后将无法使用记忆搜索')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Toggle({ type: ToggleType.Switch, isOn: this.settings.enabled })
          .onChange((isOn: boolean) => { this.toggleEnabled(); })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 策略选择行（4 个胶囊单选） */
  @Builder
  buildStrategyRow() {
    GlassCard() {
      Column() {
        Text('搜索策略')
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')

        Flex({ wrap: FlexWrap.Wrap }) {
          ForEach(ALL_STRATEGIES, (strategy: MemorySearchStrategy) => {
            Text(MemorySearchSettingsViewHelper.getStrategyLabel(strategy))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.settings.strategy === strategy
                ? this.sm.getColor('text_on_primary')
                : this.sm.getColor('text_primary'))
              .padding({ left: 12, right: 12, top: 6, bottom: 6 })
              .borderRadius(16)
              .backgroundColor(this.settings.strategy === strategy
                ? this.sm.getColor(MemorySearchSettingsViewHelper.getStrategyColor(strategy))
                : this.sm.getColor('divider'))
              .margin({ right: 8, top: 8 })
              .onClick(() => { this.selectStrategy(strategy); })
          }, (strategy: MemorySearchStrategy) => strategy)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** topK 滑块行 */
  @Builder
  buildTopKRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('返回结果数')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySearchSettingsViewHelper.formatTopK(this.settings.topK))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('primary'))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Slider({
          value: this.settings.topK,
          min: 1,
          max: 50,
          step: 1,
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .onChange((value: number, mode: SliderChangeMode) => {
            this.slideTopK(value);
          })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** minScore 滑块行 */
  @Builder
  buildMinScoreRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('最小分数')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySearchSettingsViewHelper.formatMinScore(this.settings.minScore))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor(MemorySearchSettingsViewHelper.getMinScoreColor(this.settings.minScore)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        Slider({
          value: this.settings.minScore,
          min: 0,
          max: 1,
          step: 0.1,
        })
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
          .onChange((value: number, mode: SliderChangeMode) => {
            this.slideMinScore(value);
          })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
    .margin({ bottom: 12 })
  }

  /** 过滤器行（types/tags/dateRange） */
  @Builder
  buildFiltersRow() {
    GlassCard() {
      Column() {
        Row() {
          Text('过滤器')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)

          Text(MemorySearchSettingsViewHelper.formatFilters(this.settings.filters))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // types 多行文本
        Text('类型（每行一个）')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
        TextArea({
          placeholder: 'long_term\nshort_term',
          text: this.filtersForm.typesText,
        })
          .width('100%')
          .height(80)
          .fontSize(this.sm.getFontSize('caption'))
          .margin({ top: 4 })
          .onChange((v: string) => { this.inputTypesText(v); })

        // tags 多行文本
        Text('标签（每行一个）')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
        TextArea({
          placeholder: 'important\nwork',
          text: this.filtersForm.tagsText,
        })
          .width('100%')
          .height(80)
          .fontSize(this.sm.getFontSize('caption'))
          .margin({ top: 4 })
          .onChange((v: string) => { this.inputTagsText(v); })

        // 日期范围
        Text('日期范围')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('info'))
          .width('100%')
          .margin({ top: this.sm.getSpacing('sm') })
        Row() {
          GlassInput({
            placeholder: '开始 YYYY-MM-DD',
            value: this.filtersForm.dateStart,
            type: 'text',
            onChange: (v: string) => { this.inputDateStart(v); },
          })
            .layoutWeight(1)
          Text('至')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8, right: 8 })
          GlassInput({
            placeholder: '结束 YYYY-MM-DD',
            value: this.filtersForm.dateEnd,
            type: 'text',
            onChange: (v: string) => { this.inputDateEnd(v); },
          })
            .layoutWeight(1)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: 4 })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }
}
